"""guestfs – acesso programático ao console do guest (head unit virtual).

O orquestrador expõe o tty do guest como um socket unix stream; este módulo
fala com ele:

  * GuestSession / run(): executa um comando no shell do guest usando
    marcadores únicos (captura a saída e o código de retorno);
  * push() / pull(): transferem arquivos pequenos/médios pelo shell do guest
    (base64 quando existir no guest; senão printf octal / od hexadecimal);
  * lock de arquivo para serializar o uso do tty (um único tty compartilhado).

Somente biblioteca padrão (Python 3.9). Sem dependências do pacote `idemu`
para poder ser carregado direto pelo sshshell.py (ForceCommand).
"""
import base64
import binascii
import fcntl
import hashlib
import os
import re
import select
import shlex
import socket
import tempfile
import time
import uuid

DEFAULT_TIMEOUT = 30.0
EOL = b"\r"          # o tty do guest aceita '\r' ou '\n'


class GuestError(Exception):
    """Erro de comunicação/execução com o console do guest."""


class GuestTimeout(GuestError):
    def __init__(self, msg, partial=b""):
        GuestError.__init__(self, msg)
        self.partial = partial


def lock_path_for(sock_path):
    h = hashlib.sha1(os.path.abspath(sock_path).encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "idemu-console-%s.lock" % h)


def shquote(s):
    return shlex.quote(s)


def normalize_output(b):
    """\\r\\n -> \\n (o tty do guest traduz NL em CRLF)."""
    return b.replace(b"\r\n", b"\n")


class GuestSession(object):
    """Conexão exclusiva (lock de arquivo) ao console do guest.

    with GuestSession(sock) as g:
        rc, out = g.run("ls /")
    """

    def __init__(self, sock_path, timeout=DEFAULT_TIMEOUT, lock=True, shared=False,
                 lock_path=None, lock_timeout=None):
        self.sock_path = sock_path
        self.timeout = float(timeout)
        self.use_lock = lock
        self.shared = shared
        self.lock_path = lock_path or lock_path_for(sock_path)
        self.lock_timeout = self.timeout if lock_timeout is None else lock_timeout
        self._lockfd = None
        self.sock = None

    # --- ciclo de vida -------------------------------------------------
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *a):
        self.close()

    def open(self):
        if self.use_lock:
            self._acquire_lock()
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(5.0)
            try:
                s.connect(self.sock_path)
            except (OSError, socket.error) as e:
                s.close()
                raise GuestError("console do guest indisponível (%s): %s" % (self.sock_path, e))
            s.setblocking(False)
            self.sock = s
        except Exception:
            self._release_lock()
            raise

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self._release_lock()

    def _acquire_lock(self):
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        mode = (fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX) | fcntl.LOCK_NB
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                fcntl.flock(fd, mode)
                break
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise GuestError("console do guest ocupado (outra sessão/comando em uso)")
                time.sleep(0.05)
        self._lockfd = fd

    def _release_lock(self):
        if self._lockfd is not None:
            try:
                fcntl.flock(self._lockfd, fcntl.LOCK_UN)
            finally:
                os.close(self._lockfd)
                self._lockfd = None

    # --- I/O baixo nível -----------------------------------------------
    def send(self, data):
        view = memoryview(data)
        deadline = time.monotonic() + self.timeout
        while len(view):
            try:
                n = self.sock.send(view)
                view = view[n:]
            except (BlockingIOError, InterruptedError):
                r = deadline - time.monotonic()
                if r <= 0:
                    raise GuestTimeout("timeout enviando dados ao guest")
                select.select([], [self.sock], [], min(r, 0.5))
            except (OSError, socket.error) as e:
                raise GuestError("conexão com o console perdida: %s" % e)

    def drain(self, quiet=0.15, maxtime=2.0):
        """Descarta o que estiver chegando até haver silêncio."""
        end = time.monotonic() + maxtime
        last = time.monotonic()
        while time.monotonic() < end and time.monotonic() - last < quiet:
            r, _, _ = select.select([self.sock], [], [], 0.05)
            if r:
                try:
                    d = self.sock.recv(65536)
                except (BlockingIOError, InterruptedError):
                    continue
                if not d:
                    break
                last = time.monotonic()

    # --- execução ------------------------------------------------------
    def run(self, cmd, timeout=None):
        """Executa `cmd` no shell do guest. Devolve (rc:int, saida:bytes)."""
        c = cmd.rstrip("\r\n")
        sep = " " if re.search(r"(?<!&)&\s*$", c) else "; "
        return self.run_lines(None, timeout, inner=c, sep=sep)

    def run_lines(self, lines, timeout=None, inner=None, sep="; "):
        """Envia várias linhas (script/heredoc) entre marcadores. Devolve (rc, saida)."""
        timeout = self.timeout if timeout is None else float(timeout)
        tok = uuid.uuid4().hex[:10]
        # '' no meio do marcador: o eco do tty não casa com o marcador real
        begin = "echo __IDEMU_B''_%s__" % tok
        endm = "echo __IDEMU_RC''_%s_$?__" % tok
        if inner is not None:
            payload = "%s; { %s%s} </dev/null; %s" % (begin, inner, sep, endm)
            data = payload.encode("utf-8") + EOL
        else:
            data = (begin.encode("utf-8") + EOL +
                    b"".join(l.encode("utf-8") + EOL for l in lines) +
                    endm.encode("utf-8") + EOL)
        re_begin = re.compile(("__IDEMU_B_%s__\r?\n" % tok).encode())
        re_end = re.compile(("__IDEMU_RC_%s_(\\d+)__" % tok).encode())
        self.send(data)
        buf = b""
        deadline = time.monotonic() + timeout
        sync_deadline = time.monotonic() + min(timeout, 10.0)
        started = None
        while True:
            now = time.monotonic()
            if started is None and now >= sync_deadline:
                self._abort()
                raise GuestTimeout("o guest não respondeu (sem prompt de shell no console?)", buf)
            if now >= deadline:
                self._abort()
                raise GuestTimeout("timeout (%.0fs) aguardando o comando terminar" % timeout,
                                   normalize_output(buf))
            r, _, _ = select.select([self.sock], [], [], min(0.25, deadline - now))
            if not r:
                continue
            try:
                chunk = self.sock.recv(65536)
            except (BlockingIOError, InterruptedError):
                continue
            except (OSError, socket.error) as e:
                raise GuestError("conexão com o console perdida: %s" % e)
            if not chunk:
                raise GuestError("o console do guest fechou a conexão")
            buf += chunk
            if started is None:
                m = re_begin.search(buf)
                if m:
                    started = m.end()
            if started is not None:
                m = re_end.search(buf, started)
                if m:
                    out = normalize_output(buf[started:m.start()])
                    return int(m.group(1)), out

    def _abort(self):
        try:
            self.send(b"\x03")
            self.drain(0.3, 1.5)
        except GuestError:
            pass


def run(sock_path, cmd, timeout=DEFAULT_TIMEOUT):
    """Atalho: abre sessão, executa e fecha."""
    with GuestSession(sock_path, timeout=timeout) as g:
        return g.run(cmd, timeout)


# ---------------------------------------------------------------------------
# checksum POSIX (cksum) para verificar transferências
# ---------------------------------------------------------------------------
def _make_crc_table():
    tbl = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) if (c & 0x80000000) else (c << 1)
            c &= 0xFFFFFFFF
        tbl.append(c)
    return tbl


_CRC_TABLE = _make_crc_table()


def posix_cksum(data):
    """Mesmo valor que o utilitário `cksum` (CRC POSIX)."""
    crc = 0
    for b in bytearray(data):
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    n = len(data)
    while n:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ n) & 0xFF]
        n >>= 8
    return (~crc) & 0xFFFFFFFF


def _remote_cksum(g, remote):
    rc, out = g.run("cksum %s" % shquote(remote))
    m = re.search(rb"^\s*(\d+)\s+(\d+)\b", out, re.M)
    if rc == 0 and m:
        return int(m.group(1)), int(m.group(2))
    rc, out = g.run("wc -c < %s" % shquote(remote))
    m = re.search(rb"(\d+)", out)
    if rc == 0 and m:
        return None, int(m.group(1))
    return None, None


def detect_codec(g):
    """'base64:-d' | 'base64:-D' | 'printf' (push)  — probe no guest."""
    for flag in ("-d", "-D"):
        rc, out = g.run("echo aGk= | base64 %s 2>/dev/null" % flag)
        if rc == 0 and out.strip() == b"hi":
            return "base64:" + flag
    return "printf"


def push(sock_path, local, remote, timeout=DEFAULT_TIMEOUT, codec=None, verify=True,
         batch_lines=10, progress=None):
    """Copia um arquivo local para o guest. Devolve dict {bytes, codec, crc}."""
    with open(local, "rb") as f:
        data = f.read()
    crc = posix_cksum(data)
    rq = shquote(remote)
    with GuestSession(sock_path, timeout=timeout) as g:
        codec = codec or detect_codec(g)
        rc, out = g.run(": > %s" % rq)
        if rc != 0:
            raise GuestError("não consegui criar %s no guest: %s" % (remote, out.decode("utf-8", "replace").strip()))
        if codec.startswith("base64"):
            flag = codec.split(":", 1)[1] if ":" in codec else "-d"
            b64 = base64.b64encode(data).decode("ascii")
            lines = [b64[i:i + 76] for i in range(0, len(b64), 76)]
            done = 0
            for i in range(0, len(lines), batch_lines):
                part = lines[i:i + batch_lines]
                script = ["base64 %s >> %s << 'IDEMU_EOF'" % (flag, rq)] + part + ["IDEMU_EOF"]
                rc, out = g.run_lines(script, timeout)
                if rc != 0:
                    raise GuestError("falha gravando no guest (rc=%d): %s" % (rc, out.decode("utf-8", "replace").strip()))
                done += sum(len(p) for p in part) * 3 // 4
                if progress:
                    progress(min(done, len(data)), len(data))
        else:
            per = 40
            done = 0
            step = per * batch_lines
            for i in range(0, len(data), step):
                script = []
                for j in range(i, min(i + step, len(data)), per):
                    seg = data[j:j + per]
                    script.append("printf '%s' >> %s" % ("".join("\\%03o" % b for b in bytearray(seg)), rq))
                rc, out = g.run_lines(script, timeout)
                if rc != 0:
                    raise GuestError("falha gravando no guest (rc=%d)" % rc)
                done += min(step, len(data) - i)
                if progress:
                    progress(done, len(data))
        if verify:
            rcrc, rsize = _remote_cksum(g, remote)
            if rsize is not None and rsize != len(data):
                raise GuestError("verificação falhou: tamanho no guest %s != %d" % (rsize, len(data)))
            if rcrc is not None and rcrc != crc:
                raise GuestError("verificação falhou: cksum no guest %d != %d" % (rcrc, crc))
    return {"bytes": len(data), "codec": codec, "crc": crc}


def pull(sock_path, remote, local, timeout=120.0, codec=None, verify=True):
    """Copia um arquivo do guest para o host. Devolve dict {bytes, codec, crc}."""
    rq = shquote(remote)
    with GuestSession(sock_path, timeout=timeout) as g:
        codec = codec or detect_codec(g)
        rc, out = g.run("test -f %s" % rq)
        if rc != 0:
            raise GuestError("arquivo inexistente no guest: %s" % remote)
        if codec.startswith("base64"):
            rc, out = g.run("base64 < %s" % rq, timeout)
            if rc != 0:
                raise GuestError("falha lendo %s no guest (rc=%d)" % (remote, rc))
            try:
                data = base64.b64decode(b"".join(out.split()))
            except (binascii.Error, ValueError) as e:
                raise GuestError("resposta base64 inválida do guest: %s" % e)
        else:
            rc, out = g.run("od -An -v -tx1 %s" % rq, timeout)
            if rc != 0:
                raise GuestError("falha lendo %s no guest (rc=%d)" % (remote, rc))
            try:
                data = binascii.unhexlify(b"".join(out.split()))
            except (binascii.Error, ValueError) as e:
                raise GuestError("resposta hexadecimal inválida do guest: %s" % e)
        crc = posix_cksum(data)
        if verify:
            rcrc, rsize = _remote_cksum(g, remote)
            if rsize is not None and rsize != len(data):
                raise GuestError("verificação falhou: tamanho no guest %s != %d recebidos" % (rsize, len(data)))
            if rcrc is not None and rcrc != crc:
                raise GuestError("verificação falhou: cksum no guest %d != %d" % (rcrc, crc))
    tmp = local + ".idemu-part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, local)
    return {"bytes": len(data), "codec": codec, "crc": crc}
