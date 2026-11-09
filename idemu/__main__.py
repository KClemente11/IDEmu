import sys, os, json
from . import server

USAGE = """IDEmu - emulador de head unit BMW iDrive 6 (NBT Evo)
  python3 -m idemu gui [--port N] [--no-browser]   abre a interface gráfica
  python3 -m idemu list                            lista ambientes
  python3 -m idemu build <id>                      compila o ambiente a partir dos SWFL
  python3 -m idemu run <id>                        inicia o ambiente (Ctrl+C encerra)
  python3 -m idemu ssh <id>                        abre o shell da head unit (ambiente em execução via 'gui' ou 'run')
"""

def main(argv):
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(USAGE); return 0
    cmd = argv[0]
    if cmd == 'gui':
        port = 8765
        if '--port' in argv: port = int(argv[argv.index('--port') + 1])
        server.serve(port=port, open_browser='--no-browser' not in argv); return 0
    A = server.APP
    if cmd == 'list':
        for e in A.list_envs(): print('%-20s %-6s %-5s %s' % (e['id'], e['chassis'], e['brand'], e['build']['state']))
        return 0
    if cmd == 'build':
        A.start_build(argv[1])
        import time
        last = None
        while True:
            b = A.build_info(argv[1]) if argv[1] not in A.builds else A.builds[argv[1]]
            if (b['pct'], b['step']) != last: print('[%3d%%] %s' % (b['pct'], b['step'])); last = (b['pct'], b['step'])
            if b['state'] in ('ready', 'error'): break
            time.sleep(1)
        if b['state'] == 'error': print('ERRO:', b['error']); return 1
        return 0
    if cmd == 'run':
        import time
        A.start(argv[1]); last = None
        try:
            while True:
                s = A.rt.status()
                k = (s['state'], s['boot_step'], s['boot_pct'])
                if k != last: print(k, flush=True); last = k
                if s['state'] == 'error': print(s['error']); break
                time.sleep(2)
        except KeyboardInterrupt: pass
        A.stop(); return 0
    print(USAGE); return 1

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
