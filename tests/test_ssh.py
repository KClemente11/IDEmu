"""Testes do SshBridge/sshshell/guestfs com um "guest falso" (shell em pty atrás de um socket unix)
e o cliente ssh real do macOS. O sshd roda como usuário atual, em porta alta, e é sempre encerrado."""
import os
import pty
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import guestfs                      # noqa: E402
from idemu.sshbridge import SshBridge          # noqa: E402

FAKE_GUEST = r'''
import os, pty, select, socket, sys, termios
path, shell = sys.argv[1], sys.argv[2]
pid, master = pty.fork()
if pid == 0:
    env = dict(os.environ, PS1="# ", TERM="dumb", ENV="")
    os.execve(shell, [shell, "-i"], env)
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(path); srv.listen(8)
conns = []
import fcntl
fcntl.fcntl(master, fcntl.F_SETFL, fcntl.fcntl(master, fcntl.F_GETFL) | os.O_NONBLOCK)
pending = bytearray()
sys.stdout.write("ready\n"); sys.stdout.flush()
while True:
    rl = [srv, master] + conns
    wl = [master] if pending else []
    r, w, _ = select.select(rl, wl, [], 1.0)
    if w:
        try:
            n = os.write(master, bytes(pending[:512]))
            del pending[:n]
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            sys.exit(0)
    for f in r:
        if f is srv:
            c, _ = srv.accept(); conns.append(c)
        elif f == master:
            try:
                d = os.read(master, 65536)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                sys.exit(0)
            if not d:
                sys.exit(0)
            for c in list(conns):
                try: c.sendall(d)
                except OSError:
                    conns.remove(c)
        else:
            try:
                d = f.recv(65536)
            except OSError:
                d = b""
            if not d:
                conns.remove(f); f.close()
            else:
                pending.extend(d)
'''


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class SshTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists("/usr/sbin/sshd"):
            raise unittest.SkipTest("/usr/sbin/sshd ausente")
        cls.tmp = tempfile.mkdtemp(prefix="idemu ssh ")      # espaço no caminho de propósito
        cls.sock = os.path.join(cls.tmp, "console.sock")
        cls.guest_py = os.path.join(cls.tmp, "fake_guest.py")
        with open(cls.guest_py, "w") as f:
            f.write(FAKE_GUEST)
        shell = "/bin/dash" if os.path.exists("/bin/dash") else "/bin/sh"
        cls.guest = subprocess.Popen([sys.executable, cls.guest_py, cls.sock, shell],
                                     stdout=subprocess.PIPE, universal_newlines=True)
        line = cls.guest.stdout.readline()
        assert line.strip() == "ready", line
        cls.port = free_port()
        cls.bridge = SshBridge(os.path.join(cls.tmp, "env"), cls.port, cls.sock)
        ok, msg = cls.bridge.start()
        if not ok:
            cls.tearDownClass()
            raise AssertionError("sshd não subiu: " + msg)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.bridge.stop()
        except Exception:
            pass
        g = getattr(cls, "guest", None)
        if g is not None:
            g.kill()
            g.wait()
            g.stdout.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ssh_args(self, *extra):
        i = self.bridge.info()
        return (["ssh", "-i", i["key_path"], "-p", str(i["port"]), "-o", "StrictHostKeyChecking=no",
                 "-o", "UserKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                 "-o", "LogLevel=ERROR"] + list(extra) + ["%s@%s" % (i["user"], i["host"])])

    def ssh(self, cmd, timeout=40, extra=()):
        return subprocess.run(self.ssh_args(*extra) + ([cmd] if cmd is not None else []),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                              stdin=subprocess.DEVNULL)


class TestBridgeInfo(SshTestBase):
    def test_info(self):
        i = self.bridge.info()
        self.assertEqual(i["state"], "up")
        self.assertEqual(i["port"], self.port)
        self.assertTrue(os.path.exists(i["key_path"]))
        self.assertIn("-p %d" % self.port, i["command"])
        self.assertIn("note", i)
        for k in ("host", "user", "command", "key_path"):
            self.assertTrue(i[k])

    def test_files_created(self):
        d = os.path.join(self.tmp, "env", "ssh")
        for n in ("ssh_host_ed25519_key", "id_ed25519", "id_ed25519.pub", "authorized_keys", "sshd_config"):
            self.assertTrue(os.path.exists(os.path.join(d, n)), n)


class TestExec(SshTestBase):
    def test_exec_output_and_rc(self):
        r = self.ssh("echo oi; false")
        self.assertEqual(r.stdout, b"oi\n", r)
        self.assertEqual(r.returncode, 1, r)

    def test_exec_rc_zero_and_nonewline(self):
        r = self.ssh("printf abc")
        self.assertEqual(r.stdout, b"abc")
        self.assertEqual(r.returncode, 0)

    def test_exec_rc_value(self):
        r = self.ssh("echo x; (exit 7)")
        self.assertEqual(r.stdout, b"x\n")
        self.assertEqual(r.returncode, 7)

    def test_exec_multiline_output(self):
        r = self.ssh("echo a; echo b; echo c")
        self.assertEqual(r.stdout, b"a\nb\nc\n")

    def test_exec_state_persists_between_calls(self):
        # o shell do guest é o mesmo: variáveis exportadas persistem
        self.ssh("IDEMU_T=42")
        r = self.ssh("echo $IDEMU_T")
        self.assertEqual(r.stdout, b"42\n")

    def test_exec_concurrent_serialised(self):
        procs = [subprocess.Popen(self.ssh_args() + ["echo n%d; sleep 0.2; echo m%d" % (i, i)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
                 for i in range(4)]
        for i, p in enumerate(procs):
            out, err = p.communicate(timeout=60)
            self.assertEqual(out, ("n%d\nm%d\n" % (i, i)).encode(), (out, err))

    def test_scp_unsupported(self):
        r = self.ssh("scp -t /tmp/x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"idemu push", r.stderr)

    def _client(self, prog, extra, tail, inp=None):
        i = self.bridge.info()
        flag = "-P" if prog in ("scp", "sftp") else "-p"
        cmd = [prog] + list(extra) + [flag, str(i["port"]), "-i", i["key_path"], "-o", "StrictHostKeyChecking=no",
                                      "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
                                      "-o", "LogLevel=ERROR"] + tail(i)
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, input=inp or b"", timeout=30)

    def test_real_scp_legacy_gives_clear_error(self):
        f = os.path.join(self.tmp, "a.txt")
        with open(f, "w") as fh:
            fh.write("x")
        r = self._client("scp", ["-O"], lambda i: [f, "%s@%s:/tmp/a.txt" % (i["user"], i["host"])])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"idemu push", r.stdout)

    def test_real_scp_sftp_mode_fails(self):
        f = os.path.join(self.tmp, "a2.txt")
        with open(f, "w") as fh:
            fh.write("x")
        r = self._client("scp", [], lambda i: [f, "%s@%s:/tmp/a2.txt" % (i["user"], i["host"])])
        self.assertNotEqual(r.returncode, 0)          # (o scp novo só mostra "Failure")

    def test_sftp_gives_clear_error(self):
        r = self._client("sftp", [], lambda i: ["%s@%s" % (i["user"], i["host"])], inp=b"ls\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"idemu push", r.stdout)

    def test_wrong_key_rejected(self):
        k = os.path.join(self.tmp, "other")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", k], check=True)
        i = self.bridge.info()
        r = subprocess.run(["ssh", "-i", k, "-p", str(i["port"]), "-o", "StrictHostKeyChecking=no",
                            "-o", "UserKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes",
                            "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
                            "%s@%s" % (i["user"], i["host"]), "echo no"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, stdin=subprocess.DEVNULL)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(b"no\n", r.stdout)


class TestInteractive(SshTestBase):
    def test_interactive_pty(self):
        p = subprocess.Popen(self.ssh_args("-tt"), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        try:
            buf = self._read_until(p, b"conectado", 15)
            p.stdin.write(b"echo $((20+22))zz\r")
            p.stdin.flush()
            buf += self._read_until(p, b"42zz\r\n", 15)
            self.assertIn(b"42zz", buf)
            p.stdin.write(b"\x1d")                     # Ctrl-]
            p.stdin.flush()
            p.wait(timeout=15)
            self.assertEqual(p.returncode, 0)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdin.close(); p.stdout.close(); p.stderr.close()

    @staticmethod
    def _read_until(p, needle, timeout):
        buf = b""
        end = time.time() + timeout
        fd = p.stdout.fileno()
        while needle not in buf and time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                d = os.read(fd, 4096)
                if not d:
                    break
                buf += d
        if needle not in buf:
            raise AssertionError("não apareceu %r em %r" % (needle, buf))
        return buf


class TestPushPull(SshTestBase):
    def _roundtrip(self, data, codec=None):
        src = os.path.join(self.tmp, "src.bin")
        dst = os.path.join(self.tmp, "dst.bin")
        with open(src, "wb") as f:
            f.write(data)
        remote = os.path.join(self.tmp, "remote file.bin")
        r = guestfs.push(self.sock, src, remote, codec=codec)
        self.assertEqual(r["bytes"], len(data))
        with open(remote, "rb") as fh:
            self.assertEqual(fh.read(), data)      # o "guest" é o próprio Mac
        if os.path.exists(dst):
            os.remove(dst)
        r2 = guestfs.pull(self.sock, remote, dst, codec=codec)
        with open(dst, "rb") as fh:
            self.assertEqual(fh.read(), data)
        self.assertEqual(r2["bytes"], len(data))

    def test_push_pull_base64(self):
        self._roundtrip(bytes(bytearray(range(256))) * 40 + b"fim")

    def test_push_pull_printf_od_fallback(self):
        self._roundtrip(bytes(bytearray(range(256))) * 3 + b"\x00\x00%s%d'\"$`", codec="printf")

    def test_push_pull_empty(self):
        self._roundtrip(b"")

    def test_pull_missing(self):
        with self.assertRaises(guestfs.GuestError):
            guestfs.pull(self.sock, "/nao/existe/xyz", os.path.join(self.tmp, "n"))

    def test_cli_push_pull(self):
        src = os.path.join(self.tmp, "cli_src.txt")
        with open(src, "w") as fh:
            fh.write("olá guest\n" * 50)
        remote = os.path.join(self.tmp, "cli_remote.txt")
        sh = os.path.join(ROOT, "idemu", "sshshell.py")
        r = subprocess.run([sys.executable, sh, self.sock, "push", src, remote], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(r.returncode, 0, r)
        dst = os.path.join(self.tmp, "cli_back.txt")
        r = subprocess.run([sys.executable, sh, self.sock, "pull", remote, dst], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(r.returncode, 0, r)
        with open(dst) as a, open(src) as b:
            self.assertEqual(a.read(), b.read())

    def test_cksum_matches_system(self):
        data = b"hello world\n" * 7
        f = os.path.join(self.tmp, "ck.bin")
        with open(f, "wb") as fh:
            fh.write(data)
        out = subprocess.run(["cksum", f], stdout=subprocess.PIPE).stdout.split()
        self.assertEqual(int(out[0]), guestfs.posix_cksum(data))


class TestNoGuest(unittest.TestCase):
    def test_unavailable_socket(self):
        with self.assertRaises(guestfs.GuestError):
            guestfs.run("/nonexistent/sock", "echo hi", timeout=2)


if __name__ == "__main__":
    unittest.main()
