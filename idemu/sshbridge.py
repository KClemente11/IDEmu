"""sshbridge – servidor SSH (sshd do macOS, sem root) que entrega o console do guest.

`ssh -i <chave> -p <porta> <usuario-local>@127.0.0.1` abre um shell no console da
head unit virtual (via sshshell.py como ForceCommand + socket unix do orquestrador).

LIMITAÇÃO (testada no macOS): um sshd sem privilégios só consegue abrir sessão para o
PRÓPRIO usuário que o executa ("Failed to set uids to 0" ao logar como root). Por isso o
login é o usuário local (`getpass.getuser()`); dentro da sessão você está no console do
guest (que normalmente já é root). A autenticação aceita qualquer nome, mas a sessão só
abre para o usuário local.
"""
import getpass
import os
import shlex
import signal
import socket
import subprocess
import sys
import time

SSHD = "/usr/sbin/sshd"
SSH_KEYGEN = "/usr/bin/ssh-keygen"
HERE = os.path.dirname(os.path.abspath(__file__))
SSHSHELL = os.path.join(HERE, "sshshell.py")


def _q(path):
    """Valor entre aspas para o sshd_config (argv_split do sshd: aspas duplas)."""
    p = path.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % p


class SshBridge(object):
    def __init__(self, env_dir, port, shell_sock_path, user="root", bind="127.0.0.1"):
        self.env_dir = os.path.abspath(env_dir)
        self.port = int(port)
        self.shell_sock_path = os.path.abspath(shell_sock_path)
        self.requested_user = user
        self.bind = bind
        self.login_user = getpass.getuser()
        self.dir = os.path.join(self.env_dir, "ssh")
        self.host_key = os.path.join(self.dir, "ssh_host_ed25519_key")
        self.key_path = os.path.join(self.dir, "id_ed25519")
        self.authorized_keys = os.path.join(self.dir, "authorized_keys")
        self.config_path = os.path.join(self.dir, "sshd_config")
        self.client_config = os.path.join(self.dir, "ssh_config")
        self.pid_file = os.path.join(self.dir, "sshd.pid")
        self.log_path = os.path.join(self.dir, "sshd.log")
        self.python = sys.executable or "/usr/bin/python3"
        self.proc = None
        self._logf = None
        self.last_error = None

    # --- geração de arquivos --------------------------------------------
    def _keygen(self, path, comment):
        if os.path.exists(path) and os.path.exists(path + ".pub"):
            return
        for p in (path, path + ".pub"):
            if os.path.exists(p):
                os.remove(p)
        r = subprocess.run([SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", path],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if r.returncode != 0:
            raise RuntimeError("ssh-keygen falhou: %s" % r.stderr.strip())
        os.chmod(path, 0o600)

    def _write_files(self):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        self._keygen(self.host_key, "idemu-host")
        self._keygen(self.key_path, "idemu-client")
        with open(self.key_path + ".pub") as f:
            pub = f.read().strip()
        with open(self.authorized_keys, "w") as f:
            f.write(pub + "\n")
        os.chmod(self.authorized_keys, 0o600)
        force = "%s %s %s" % (shlex.quote(self.python), shlex.quote(SSHSHELL), shlex.quote(self.shell_sock_path))
        sub = "idemu-sftp-unsupported"      # nunca executado: o ForceCommand assume e responde o erro
        cfg = [
            "# gerado pelo IDEmu – sshd sem root, somente loopback",
            "Port %d" % self.port,
            "ListenAddress %s" % self.bind,
            "HostKey %s" % _q(self.host_key),
            "PidFile %s" % _q(self.pid_file),
            "AuthorizedKeysFile %s" % _q(self.authorized_keys),
            "UsePAM no",
            "StrictModes no",
            "PasswordAuthentication no",
            "KbdInteractiveAuthentication no",
            "ChallengeResponseAuthentication no",
            "PubkeyAuthentication yes",
            "PermitRootLogin yes",
            "PermitEmptyPasswords no",
            "PermitTTY yes",
            "AllowTcpForwarding no",
            "X11Forwarding no",
            "AllowAgentForwarding no",
            "PermitTunnel no",
            "PermitUserRC no",
            "PrintMotd no",
            "PrintLastLog no",
            "MaxAuthTries 3",
            "LoginGraceTime 20",
            "ClientAliveInterval 30",
            "LogLevel ERROR",
            "Subsystem sftp %s" % sub,
            "ForceCommand %s" % force,
            "",
        ]
        with open(self.config_path, "w") as f:
            f.write("\n".join(cfg))
        ccfg = [
            "# cliente SSH para o IDEmu:  ssh -F %s idemu" % self.client_config,
            "Host idemu",
            "    HostName %s" % self.bind,
            "    Port %d" % self.port,
            "    User %s" % self.login_user,
            "    IdentityFile %s" % _q(self.key_path),
            "    IdentitiesOnly yes",
            "    StrictHostKeyChecking no",
            "    UserKnownHostsFile /dev/null",
            "    LogLevel ERROR",
            "",
        ]
        with open(self.client_config, "w") as f:
            f.write("\n".join(ccfg))

    # --- ciclo de vida ---------------------------------------------------
    def _port_open(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect((self.bind, self.port))
            return True
        except (OSError, socket.error):
            return False
        finally:
            s.close()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _kill_stale(self):
        """sshd que sobrou de um servidor encerrado à força (segurando a porta): só mata o que este ambiente iniciou (pid salvo + linha de comando com a nossa config)."""
        try:
            with open(self.config_path + ".pid") as f:
                pid = int(f.read().strip())
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], stdout=subprocess.PIPE, universal_newlines=True).stdout
            if self.config_path in cmd:
                os.kill(pid, 15)
                for _ in range(40):
                    if not self._port_open():
                        break
                    time.sleep(0.05)
        except (OSError, ValueError):
            pass

    def start(self):
        """Sobe o sshd. Devolve (ok, mensagem)."""
        if self.running():
            return True, "sshd já em execução (pid %d)" % self.proc.pid
        if not os.path.exists(SSHD):
            return False, "sshd não encontrado em %s" % SSHD
        self._kill_stale()
        if self._port_open():
            return False, "a porta %s:%d já está em uso" % (self.bind, self.port)
        try:
            self._write_files()
        except (OSError, RuntimeError) as e:
            self.last_error = str(e)
            return False, "não foi possível preparar os arquivos do SSH: %s" % e
        r = subprocess.run([SSHD, "-t", "-f", self.config_path], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True)
        if r.returncode != 0:
            self.last_error = r.stdout.strip()
            return False, "configuração do sshd inválida: %s" % r.stdout.strip()
        self._logf = open(self.log_path, "ab")
        try:
            self.proc = subprocess.Popen([SSHD, "-D", "-e", "-f", self.config_path],
                                         stdin=subprocess.DEVNULL, stdout=self._logf,
                                         stderr=self._logf, start_new_session=True)
            with open(self.config_path + ".pid", "w") as f:
                f.write(str(self.proc.pid))
        except OSError as e:
            self.last_error = str(e)
            return False, "falha ao executar o sshd: %s" % e
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                break
            if self._port_open():
                return True, "sshd ouvindo em %s:%d (pid %d)" % (self.bind, self.port, self.proc.pid)
            time.sleep(0.05)
        tail = self._log_tail()
        self.stop()
        self.last_error = tail or "sshd terminou sem abrir a porta"
        return False, "o sshd não subiu: %s" % self.last_error

    def _log_tail(self, n=8):
        try:
            with open(self.log_path, "rb") as f:
                lines = f.read().decode("utf-8", "replace").strip().splitlines()
            return " | ".join(lines[-n:])
        except OSError:
            return ""

    @staticmethod
    def _descendants(pid):
        try:
            out = subprocess.run(["/bin/ps", "-axo", "pid=,ppid="], stdout=subprocess.PIPE,
                                 universal_newlines=True).stdout
        except OSError:
            return []
        kids = {}
        for ln in out.splitlines():
            p = ln.split()
            if len(p) == 2:
                kids.setdefault(int(p[1]), []).append(int(p[0]))
        res, stack = [], [pid]
        while stack:
            for c in kids.get(stack.pop(), []):
                res.append(c)
                stack.append(c)
        return res

    def stop(self):
        p = self.proc
        if p is not None:
            pids = self._descendants(p.pid) if p.poll() is None else []
            try:
                if p.poll() is None:
                    p.terminate()
            except OSError:
                pass
            for pid in pids:                      # sessões já abertas
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            self.proc = None
        if self._logf is not None:
            try:
                self._logf.close()
            except OSError:
                pass
            self._logf = None
        try:
            os.remove(self.pid_file)
        except OSError:
            pass

    # --- informação para a API -------------------------------------------
    def command(self):
        return ("ssh -i %s -p %d -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                "-o IdentitiesOnly=yes %s@%s" % (shlex.quote(self.key_path), self.port,
                                                 self.login_user, self.bind))

    def info(self):
        up = self.running()
        note = ("Entre com o usuário local '%s' (não 'root'): o sshd roda sem privilégios e o macOS "
                "só permite sessão para o próprio usuário ('Failed to set uids to 0' para root). "
                "Dentro da sessão você está no console do guest. Ctrl-] sai. "
                "'ssh host comando' executa um comando no guest e devolve saída e código de retorno. "
                "scp/sftp não funcionam (o guest não tem rede): use 'idemu push/pull'. "
                "Alternativa: ssh -F %s idemu" % (self.login_user, self.client_config))
        if self.requested_user and self.requested_user != self.login_user:
            note = "Usuário '%s' solicitado, mas " % self.requested_user + note[0].lower() + note[1:]
        if not up and self.last_error:
            note += " Último erro: %s" % self.last_error
        return {
            "port": self.port,
            "host": self.bind,
            "user": self.login_user,
            "key_path": self.key_path,
            "command": self.command(),
            "state": "up" if up else "down",
            "note": note,
            "client_config": self.client_config,
            "log_path": self.log_path,
        }
