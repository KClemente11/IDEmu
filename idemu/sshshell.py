#!/usr/bin/env python3
"""sshshell – ForceCommand do sshd do IDEmu: liga a sessão SSH ao console do guest.

Uso (ForceCommand):   python3 sshshell.py <socket-do-console>
Uso interno/CLI:      python3 sshshell.py <socket> push <local> <remoto>
                      python3 sshshell.py <socket> pull <remoto> <local>
                      python3 sshshell.py <socket> exec '<comando>'

  * sem comando (sessão interativa): tty do ssh em modo raw, bytes crus nos dois
    sentidos; Ctrl-] encerra (o guest faz o eco);
  * com comando (`ssh host 'ls /'`): executa no guest com marcadores únicos,
    escreve a saída em stdout e sai com o código de retorno do guest;
  * scp/sftp: não suportados (o guest não tem rede) -> use `idemu push/pull`.

Variáveis: IDEMU_SSH_TIMEOUT (s, padrão 30), IDEMU_STTY_WINCH=1 (envia
`stty rows/cols` ao guest em SIGWINCH), IDEMU_NUDGE=0 (não manda Enter ao conectar).
"""
import os
import re
import select
import signal
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guestfs  # noqa: E402

CTRL_RB = b"\x1d"   # Ctrl-]

UNSUPPORTED_RE = re.compile(r"^\s*(\S*/)?(scp|sftp|sftp-server|internal-sftp|idemu-sftp-unsupported|rsync)(\s|$)")
UNSUPPORTED_MSG = (
    "IDEMU: scp/sftp/rsync não são suportados: o console do guest não tem rede nem "
    "servidor de arquivos.\n"
    "       Use:  idemu push <arquivo-local> <caminho-no-guest>\n"
    "             idemu pull <caminho-no-guest> <arquivo-local>\n"
)


def _timeout():
    try:
        return float(os.environ.get("IDEMU_SSH_TIMEOUT", "30"))
    except ValueError:
        return 30.0


def err(msg):
    sys.stderr.write(msg if msg.endswith("\n") else msg + "\n")
    sys.stderr.flush()


def do_exec(sock, cmd):
    t = _timeout()
    try:
        with guestfs.GuestSession(sock, timeout=t) as g:
            rc, out = g.run(cmd, t)
    except guestfs.GuestTimeout as e:
        if e.partial:
            sys.stdout.buffer.write(e.partial)
            sys.stdout.buffer.flush()
        err("IDEMU: %s" % e)
        return 124
    except guestfs.GuestError as e:
        err("IDEMU: %s" % e)
        return 255
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()
    return rc & 0xFF if rc >= 0 else 1


def do_interactive(sock_path):
    import termios
    import tty
    t = _timeout()
    g = guestfs.GuestSession(sock_path, timeout=t, shared=True)
    try:
        g.open()
    except guestfs.GuestError as e:
        err("IDEMU: %s" % e)
        return 255
    s = g.sock
    fd_in, fd_out = 0, 1
    is_tty = os.isatty(fd_in)
    old = None
    if is_tty:
        try:
            old = termios.tcgetattr(fd_in)
            tty.setraw(fd_in)
        except termios.error:
            old = None

    def winch(*_):
        if os.environ.get("IDEMU_STTY_WINCH") == "1":
            try:
                sz = os.get_terminal_size(fd_in)
                s.send(("stty rows %d cols %d\r" % (sz.lines, sz.columns)).encode())
            except (OSError, ValueError):
                pass
    try:
        signal.signal(signal.SIGWINCH, winch)
    except (ValueError, AttributeError):
        pass
    try:
        os.write(fd_out, b"[IDEMU] console do guest conectado. Ctrl-] para sair.\r\n")
        if os.environ.get("IDEMU_NUDGE", "1") != "0":
            s.send(b"\r")
        rc = 0
        stdin_open = True
        while True:
            rl = [s] + ([fd_in] if stdin_open else [])
            try:
                r, _, _ = select.select(rl, [], [], 1.0)
            except InterruptedError:
                continue
            except (OSError, ValueError):
                break
            if s in r:
                try:
                    d = s.recv(65536)
                except (BlockingIOError, InterruptedError):
                    d = None
                except OSError:
                    break
                if d == b"":
                    os.write(fd_out, "\r\n[IDEMU] o console do guest fechou a conexão.\r\n".encode("utf-8"))
                    rc = 1
                    break
                if d:
                    _write_all(fd_out, d)
            if fd_in in r:
                try:
                    d = os.read(fd_in, 4096)
                except OSError:
                    break
                if not d:
                    if is_tty:
                        break
                    stdin_open = False      # stdin em pipe: continua só lendo o guest um instante
                    _drain_then_exit(s, fd_out)
                    break
                i = d.find(CTRL_RB)
                if i >= 0:
                    if i:
                        s.send(d[:i])
                    break
                try:
                    s.send(d)
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError:
                    break
        return rc
    finally:
        if old is not None:
            termios.tcsetattr(fd_in, termios.TCSADRAIN, old)
            os.write(fd_out, "\r\n[IDEMU] sessão encerrada.\r\n".encode("utf-8"))
        g.close()


def _write_all(fd, data):
    while data:
        try:
            n = os.write(fd, data)
        except InterruptedError:
            continue
        data = data[n:]


def _drain_then_exit(s, fd_out, wait=1.0):
    import time
    end = time.monotonic() + wait
    while time.monotonic() < end:
        r, _, _ = select.select([s], [], [], 0.1)
        if r:
            try:
                d = s.recv(65536)
            except (BlockingIOError, InterruptedError):
                continue
            if not d:
                return
            _write_all(fd_out, d)


def sftp_stub():
    """Servidor SFTP mínimo que responde FALHA com uma mensagem clara a qualquer pedido
    (o sshd não repassa o stderr de subsistemas; a mensagem do status chega ao cliente)."""
    import struct
    msg = ("IDEMU: sftp/scp nao suportado (console do guest sem rede). "
           "Use: idemu push <local> <remoto> / idemu pull <remoto> <local>").encode()
    rin, rout = sys.stdin.buffer, sys.stdout.buffer

    def read_exact(n):
        b = b""
        while len(b) < n:
            c = rin.read(n - len(b))
            if not c:
                return None
            b += c
        return b

    while True:
        h = read_exact(4)
        if h is None:
            return 1
        (n,) = struct.unpack(">I", h)
        body = read_exact(n) if 0 < n < (1 << 20) else None
        if not body:
            return 1
        typ = body[0]
        if typ == 1:                                    # SSH_FXP_INIT -> VERSION 3
            out = struct.pack(">BI", 2, 3)
        elif len(body) >= 5:
            (rid,) = struct.unpack(">I", body[1:5])
            out = struct.pack(">BIII", 101, rid, 4, len(msg)) + msg + struct.pack(">I", 0)
        else:
            return 1
        rout.write(struct.pack(">I", len(out)) + out)
        rout.flush()


def cli(sock, args):
    cmd = args[0]
    try:
        if cmd == "push" and len(args) == 3:
            r = guestfs.push(sock, args[1], args[2], timeout=_timeout())
            print("push ok: %d bytes (%s)" % (r["bytes"], r["codec"]))
            return 0
        if cmd == "pull" and len(args) == 3:
            r = guestfs.pull(sock, args[1], args[2], timeout=max(_timeout(), 120.0))
            print("pull ok: %d bytes (%s)" % (r["bytes"], r["codec"]))
            return 0
        if cmd == "exec" and len(args) >= 2:
            return do_exec(sock, " ".join(args[1:]))
    except guestfs.GuestError as e:
        err("IDEMU: %s" % e)
        return 1
    except OSError as e:
        err("IDEMU: %s" % e)
        return 1
    err("uso: sshshell.py <socket> [push <local> <remoto> | pull <remoto> <local> | exec <cmd>]")
    return 2


def main(argv):
    if len(argv) < 2:
        err("uso: sshshell.py <socket-do-console> [subcomando...]")
        return 2
    sock = argv[1]
    if len(argv) > 2:
        if argv[2] == "--unsupported":
            sys.stderr.write(UNSUPPORTED_MSG)
            return 1
        return cli(sock, argv[2:])
    orig = os.environ.get("SSH_ORIGINAL_COMMAND")
    if orig is None or not orig.strip():
        return do_interactive(sock)
    if "idemu-sftp-unsupported" in orig:
        return sftp_stub()
    if UNSUPPORTED_RE.search(orig):
        sys.stderr.write(UNSUPPORTED_MSG)
        sys.stderr.flush()
        return 1
    return do_exec(sock, orig)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(130)
