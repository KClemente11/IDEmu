#!/usr/bin/env python3
"""Sobe o CIC (iDrive 4) em segundo plano: console QNX no socket /tmp/cic/ser1.sock (SCIF1) e SCIF0 em arquivo.
uso: run.py [start|stop]   — depois: console.py 'comando' ..."""
import os, subprocess, sys, time, signal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootinfo, efs
HOME = os.path.expanduser('~')
QEMU = os.environ.get('CIC_QEMU', HOME + '/id4-qemu/build/qemu-system-sh4')
IFS = os.environ.get('CIC_IFS', HOME + '/Downloads/System files/ID4/swfl_000003a6.bin.008_090_002')
D = os.environ.get('CIC_DIR', '/tmp/cic')

FULL_BOOT = '''cp /usr/bin/memifs2 /tmp/memifs2
slogger -s128 &
sloginfo -w > /dev/ser2 2>&1 &
devf-generic -t10 -r -b9 -s0x0,128m,,,,,,1000,20 -p400,16 &
waitfor /dev/fs0p0 10
if waitfor /mnt/HBpersistence 3 2>/dev/null; then
  echo "partições graváveis já existem"
else
  flashctl -p /dev/fs0p0 -F -o 127872K -l 2048K -e -f -n /mnt/HBpersistence
  flashctl -p /dev/fs0p0 -F -o 129920K -l 1152K -e -f -n /mnt/logistics
  slay -f devf-generic
  devf-generic -t10 -r -b9 -s0x0,128m,,,,,,1000,20 -p400,16 &
  waitfor /mnt/HBpersistence 10
  waitfor /mnt/logistics 10
fi
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if mkdir /mnt/HBpersistence/early 2>/dev/null; then break; fi
  waitfor /nonexistent 1 2>/dev/null
done
mkdir /mnt/HBpersistence/normal
for i in 1 2 3 4 5 6 7 8 9 10; do
  if echo "HBpersistence recovery on startup" > /mnt/logistics/v.6 2>/dev/null; then break; fi
  waitfor /nonexistent 1 2>/dev/null
done
memifs2 -D -L -C 8 -o 0x04d80000 /mnt/EFS_RO &
waitfor /mnt/EFS_RO/fonts 30
@IFS2@
@IONET@
srv-starter-QNX -c /etc/starter.cfg -vvv -g -u &
'''

FLASH_SEGS = [('swfl_000003a6.bin.008_090_002', [(0x280000, 4980736), (0x740000, 73662464), (0x4d80000, 33554432)]),
              ('swfl_00000417.bin.008_090_002', [(0x6d80000, 0x40000)])]

def build_flash(path):
    """Imagem da NOR de 128 MB: segmentos dos pacotes nos endereços de flash (IFS, IFS2, EFS_RO, HMI)."""
    base = os.path.dirname(IFS)
    with open(path, 'wb') as out:
        out.truncate(128 << 20)
        out.seek(0); out.write(b'\xff' * (128 << 20))
        efs_end = 0
        for name, segs in FLASH_SEGS:
            with open(os.path.join(base, name), 'rb') as f:
                for addr, n in segs:
                    data = f.read(n)
                    if addr == 0x6d80000 and os.environ.get('CIC_EFS_FLASH'):
                        continue                        # o imagefs gerado já ocupa essa faixa; o segmento HMI o corromperia
                    if addr == 0x740000 and os.environ.get('CIC_NOWDOG', '1') == '1':    # IFS2: mesmo patch do watchdog no CicHighEceUsaSecond
                        pat = bytes.fromhex('01e1962fa62f436ab62fe62f224f1224')
                        assert data.count(pat) >= 1, 'padrão do watchdog não achado no IFS2'
                        data = data.replace(pat, b'\x00' + pat[1:])          # Second e HmiMain (mesmo código de startup)
                    if addr == 0x740000 and os.environ.get('CIC_HMISRCM1', '1') == '1':
                        # HmiMain mistura imagens em duas passadas: RGB (planemask 0x00ffffff, modo 0x?0102 = SRC_M1/DST_1mM1) e só alpha
                        # (planemask 0xff000000, modo 0x?0602 = SRC_1/DST_1mM1). O libffb ignora o planemask e a 2ª passada vira, no RGB,
                        # src + dst*(1-As): onde a imagem tem branco transparente (0x00ffffff) satura em branco (retângulos brancos/laranja).
                        # Aqui a 2ª passada usa SRC_M1 (um "over" normal); o canal alpha o libffb não grava de qualquer jeito.
                        for old, new in (('5a4d70ff02060400', '5a4d70ff02010400'),
                                          ('02060500', '02010500'),
                                          ('322b70ff02060100', '322b70ff02010100')):
                            old, new = bytes.fromhex(old), bytes.fromhex(new)
                            assert data.count(old) == 1, 'padrão do HmiMain (modo de alpha) não achado'
                            data = data.replace(old, new)
                    if addr == 0x740000 and os.environ.get('CIC_HMIINPUT', '1') == '1':
                        # entrada do controlador iDrive: o HmiMain pede telegramas MTP ao QEMU (tools/cic/hmiinput.py, src/cic/cic.c)
                        import hmiinput
                        data = hmiinput.patch_ifs2(data)
                    if addr == 0x4d80000:               # FFS3 original (EFS_RO) o devf não monta: vira o imagefs gerado
                        efs = os.environ.get('CIC_EFS_FLASH')
                        if efs:
                            data = open(efs, 'rb').read()
                            assert 0x4d80000 + len(data) <= 0x7ce0000, 'imagefs invade as partições graváveis (HBpersistence/logistics)'
                    out.seek(addr); out.write(data)

def prepare(D, pkg=None, log=print):
    """Monta em D as imagens do boot: efs.ifs (EFS_RO), boot.sh, ifs.bin (IFS com os patches) e flash.img (NOR de 128 MB)."""
    global IFS
    if pkg:
        IFS = pkg
    os.makedirs(D, exist_ok=True)
    edits = [bootinfo.root_password_edit('root'),
             (b'MALLOC_MMAP_NOZERO=1', b'PCIDMA_TEST_MODVER=1', 'all')]   # dev-sysregs: segue mesmo com o FPGA virtual
    edits[1] = (edits[1][0], edits[1][1], 'all')
    if os.environ.get('CIC_STARTER', '0') != '1':      # sem o starter da Harman: só kernel + shell (depuração)
        edits.append((b'/usr/bin/srv-starter-QNX', b'/bin/echo' + bytes(15)))
    if os.environ.get('CIC_AUDIO', '0') != '1':      # sem o núcleo de DMA do FPGA o deva-ctrl-hb_fpga entra em loop infinito e esgota a CPU
        edits.append((b'<Name>/sbin/io-audio</Name>', b'<Name>/bin//////echo</Name>'))
    if os.environ.get('CIC_CLAMP', '1') == '1':
        # sem o barramento MOST o estado dos terminais nunca chega e o OnOffVehicleDevCtrl declara "clamp desconhecido": o requestor
        # escolhe então o modo de ECU (23ecu) e reinicia. Aqui o timeout passa a valer Clamp15 (ignição ligada).
        edits.append((bytes.fromhex('c82c0c8f081e'), bytes.fromhex('03ec0900081e')))
    if os.environ.get('CIC_EMPTYMODE', '1') == '1':
        # CPOnOffRequestorCic: o pedido de modo interno vazio ('') vira um pedido para a FSM (ignorado) em vez de pedir um estado ao executor
        edits.append((bytes.fromhex('08202e8dc364'), bytes.fromhex('08202ea0c364')))
    if os.environ.get('CIC_MOSTSKIP', '1') == '1':
        # sem o MOST (dev-mlb/INIC) o CMOSTStateFSM fica em WaitStarter para sempre e o plano 20int nunca termina:
        # fullyOperable() em Unloaded passa a ir direto para FullyOperable (estado 2)
        edits.append((bytes.fromhex('63d18364' '0b41' '07e5' '07e1' '9ea0' '1e18'), bytes.fromhex('63d18364' '0b41' '02e5' '02e1' '9ea0' '1e18')))
    if os.environ.get('CIC_NOETH', '1') == '1':
        # sem Ethernet (io-net depende de /etc/IFS2Ready e do NIC Micrel): triggerStartIONet() vai direto para IONetStarted (estado 8)
        edits.append((bytes.fromhex('17d100e501e60b4107e711a000e1'), bytes.fromhex('17d100e501e60b4108e711a000e1')))
    if os.environ.get('CIC_NOVIDEO', '1') == '1':
        # sem o decodificador de vídeo (SAA717x no I2C do Carmine) o dev-videoctrl sai e o CPVideoWrapper nunca fica FullyOperable:
        # triggerFullyOperable() passa a chamar direto o setter de estado do wrapper (082f6fa0) em vez de pedir o pacote VIDEOCTRL,
        # e o setter (que só entrava se o estado atual fosse o esperado) passa a entrar sempre
        edits.append((bytes.fromhex('d8bf4708247b1808fc000708'), bytes.fromhex('d8bf4708a06f2f08fc000708')))
        edits.append((bytes.fromhex('10d183640b413c74'), bytes.fromhex('10d183640b4101e5')))
        edits.append((bytes.fromhex('1035428ff36e'), bytes.fromhex('1035' '0900' 'f36e')))
    if os.environ.get('CIC_IFS2READY', '0') == '1':
        # o io-net exige /etc/IFS2Ready, que o Root só cria depois de IONetStarted (que espera o io-net): troca por um arquivo que existe
        edits.append((b'<Name>/etc/IFS2Ready</Name>', b'<Name>/dev//////null</Name>'))
    if os.environ.get('CIC_IFS2', '0') == '0':
        # o IFS2 é montado pelo próprio starter (processo memifs2, que fornece /etc/IFS2Ready); o /usr/bin/memifs2 não existe no emulador,
        # então o starter usa a cópia que o roteiro de boot põe em /tmp
        edits.append((b'<Name>/usr/bin/memifs2</Name>', b'<Name>/tmp/////memifs2</Name>'))
    if os.environ.get('CIC_NOWDOG', '1') == '1':
        # watchdog do Root ligado por padrão ("started (watchdog is enabled)"): no emulador (lento) uma thread atrasada derruba o Root e o
        # starter (FinalAction SHUTDOWN_SYSTEM) reinicia o sistema; o padrão do parser de argumentos passa a ser desligado
        edits.append((bytes.fromhex('01e1962fa62f436ab62fe62f224f1224'), bytes.fromhex('00e1962fa62f436ab62fe62f224f1224')))
    if os.environ.get('CIC_NOESSENTIAL', '1') == '1':
        # COnOffExecutor::handleErrorComponents(): um componente "essencial" que estoura o prazo do plano (no emulador:
        # PPersistencyWrapper/PDiagnosisWrapper, porque o HMI só fica pronto depois do timeout da navegação sem HD) leva o Root a
        # STATE_EXECUTOR_ERROR e a 23err (reset). Aqui o caso essencial é tratado como não essencial (o desvio bf/s vira nop).
        edits.append((bytes.fromhex('b82b028f44e0f0a0e651'), bytes.fromhex('b82b090044e0f0a0e651')))
    if os.environ.get('CIC_NODSPRESET', '1') == '1':
        # sem o DSP de áudio (DRA300/FPGA) o CPAudioWrapper loga "DSP heartbeat failed"/"DSP didn't start" e pede ao requestor
        # o estado 23ecu (reset de ECU); com isso o Root nunca entra no modo 2 e o HMI não é mostrado. As duas chamadas viram nop.
        edits.append((bytes.fromhex('0cd50b41e3640bd1a3640b4106e5'), bytes.fromhex('0cd50b41e3640bd1a36409' '0006e5')))
        edits.append((bytes.fromhex('0cd193640b4107e5'), bytes.fromhex('0cd19364090007e5')))
    sw = os.environ.get('CIC_SWDRAW', '1')
    if sw in ('1', 'core', 'ctx'):
        # sem o motor de desenho do Carmine (display lists) o devg-carmine.so passa a usar o renderizador por software do libffb:
        # devg_get_contextfuncs e devg_get_corefuncs deixam de sobrescrever
        # (com as funções do hardware) as entradas de desenho/atualização que o ffb já preencheu (mantém wait_idle, nlfuncs, isr, memória)
        if sw in ('1', 'ctx'): edits.append((bytes.fromhex('03e11638028b28d0ce0002290be11638028b26d0ce0002190fe11638028b24d0ce00031927e11638028b22d0ce00091937e11638028b20d0ce000d1933e11638028b1ed0ce000c191be11638028b1cd0ce0006191fe11638028b1ad0ce00071923e11638028b18d0ce0008192be11638028b16d0ce000a193be11638028b14d0ce000e1913e11638028b12d0ce00041900e0'), bytes.fromhex('03e11638028b28d0ce0009000be11638028b26d0ce0009000fe11638028b24d0ce00090027e11638028b22d0ce00090037e11638028b20d0ce00090033e11638028b1ed0ce0009001be11638028b1cd0ce0009001fe11638028b1ad0ce00090023e11638028b18d0ce0009002be11638028b16d0ce0009003be11638028b14d0ce00090013e11638028b12d0ce00090000e0')))
        if sw in ('1', 'core'): edits.append((bytes.fromhex('0be11639028b30d0ce00021a0fe11639028b2ed0ce00031a13e11639028b2cd0ce00041a2fe11639028b2ad0ce000b1a43e11639048ba361407127d0ce0000113fe11639028b25d0ce000f1a27e11639028b23d0ce00091a2be11639028b21d0ce000a1a33e11639028b1fd0ce000c1a4be11639048ba36140711cd0ce0002114fe11639048ba361407119d0ce00031157e11639048ba361407116d0ce000511'), bytes.fromhex('0be11639028b30d0ce0009000fe11639028b2ed0ce00090013e11639028b2cd0ce0009002fe11639028b2ad0ce00090043e11639048ba361407127d0ce0009003fe11639028b25d0ce00090027e11639028b23d0ce0009002be11639028b21d0ce00090033e11639028b1fd0ce0009004be11639048ba36140711cd0ce0009004fe11639048ba361407119d0ce00090057e11639048ba361407116d0ce000511')))
    if os.environ.get('CIC_NOECURESET', '0') == '1':
        # depuração: executeReset() do CPSystemWrapper vira "rts" (o app segue vivo em vez de se desligar para o reset)
        old = bytes.fromhex('862f962f5369a62f636ab62f436bc62fe62f224f')
        edits.append((old, bytes.fromhex('0b000900') + old[4:]))
    if os.environ.get('CIC_NOHEARTBEAT', '0') == '1':
        # CSPThreadHeartbeatMonitor::executeAction(): no emulador o segundo processo demora a dar o primeiro heartbeat e o monitor
        # pede "ECU error reset"; a função vira "rts"
        old = bytes.fromhex('862f5368962f4369a62fff78e62f224f')
        edits.append((old, bytes.fromhex('0b000900') + old[4:]))
    edits.append((b'/bin/login\0login\0', b'/bin/ksh\0\0\0-ksh\0\0'))   # shell direto no console
    edits.append((b'-q -L -C 8 -3 -o 0x00740000', b'-q -L -C 8 -D -o 0x00740000'))   # IFS2 sem DMA (o DMAC não existe)
    files = []
    cmds = os.environ.get('CIC_CMDS')                  # arquivo com comandos ksh executados no boot (modo lote)
    if not cmds and os.environ.get('CIC_FULL', '1') == '1':
        # padrão: EFS_RO montado do pacote, depois o starter da Harman em segundo plano, e o shell no console
        if not os.path.exists(D + '/efs.ifs'):
            log('EFS_RO (FFS3 original + conteúdo do HD)')
            efs.build(IFS, D + '/efs.ifs')
        os.environ['CIC_EFS_FLASH'] = D + '/efs.ifs'
        ifs2 = '/tmp/memifs2 -q -L -C 8 -D -o 0x00740000 / &\nwaitfor /usr/HBproject/CicHighEceUsaSecond 90\n' if os.environ.get('CIC_IFS2', '0') == '1' else ''
        ionet = '(waitfor /etc/IFS2Ready 600; io-net -ptcpip-v4 forward; waitfor /dev/socket 30; ifconfig lo0 127.0.0.1) &\n' if os.environ.get('CIC_IONET', '1') == '1' else ''
        open(D + '/boot.sh', 'w').write(FULL_BOOT.replace('@IFS2@', ifs2).replace('@IONET@', ionet))
        cmds = D + '/boot.sh'
    if cmds:
        files.append((open(cmds, 'rb').read(), 'etc/hosts', 'c'))
        # o roteiro de boot executa em ordem: troca o slogger (1º) por 'sh /etc/hosts' (nosso arquivo de comandos)
        edits.append((b'/usr/bin/slogger\0slogger\0-s128\0', b'/////////bin/ksh\0' + b'ksh    \0' + b'////c\0'))   # sem NULs extras: o roteiro separa por NUL
    log('IFS de boot')
    bootinfo.build(IFS, D + '/ifs.bin', ram_size=int(os.environ.get('CIC_RAM', '384')) << 20, edits=edits, files=files)
    if os.environ.get('CIC_EFS_FLASH') or not os.path.exists(D + '/flash.img'):
        log('flash NOR de 128 MB')
        build_flash(D + '/flash.img')

def qemu_cmd(D, run=None, qemu=None, debug_log=None, flash=None):
    """Linha de comando do QEMU para as imagens em D; sockets e logs vão para run (padrão: D).
    debug_log: flags do -d (None = CIC_D ou 'guest_errors,unimp'; '' = sem log, bem mais rápido).
    flash: cópia gravável da flash.img para esta execução (sem ela usa D/flash.img com snapshot=on, que grava num qcow2 temporário)."""
    run = run or D
    for f in ('ser1.sock', 'mon.sock'):
        try: os.remove(os.path.join(run, f))
        except OSError: pass
    dl = os.environ.get('CIC_D', 'guest_errors,unimp') if debug_log is None else debug_log
    cmd = [qemu or QEMU, '-M', 'cic', '-m', os.environ.get('CIC_RAM', '384'), '-display', os.environ.get('CIC_DISPLAY', 'none'), '-monitor', 'unix:%s/mon.sock,server,nowait' % run,
           '-serial', 'file:%s/ser0.txt' % run, '-chardev', 'socket,id=s1,path=%s/ser1.sock,server=on,wait=off,logfile=%s/ser1.log' % (run, run), '-serial', 'chardev:s1']
    if dl:
        cmd += ['-d', dl, '-D', run + '/log.txt'] + (['-dfilter', os.environ['CIC_FILTER']] if os.environ.get('CIC_FILTER') else [])
    drive = 'if=pflash,format=raw,file=%s' % flash if flash else 'if=pflash,format=raw,file=%s/flash.img,snapshot=on' % D
    cmd += ['-drive', drive, '-device', 'loader,file=%s/ifs.bin,addr=0x08010000,force-raw=on' % D, '-device', 'loader,addr=0x880138e0,cpu-num=0'] + (['-device', 'loader,file=%s,addr=0x12c00000,force-raw=on' % os.environ['CIC_EFS']] if os.environ.get('CIC_EFS') else [])
    if os.environ.get('CIC_XARGS'):
        cmd += os.environ['CIC_XARGS'].split()
    return cmd

def start():
    stop()
    prepare(D)
    cmd = qemu_cmd(D)
    p = subprocess.Popen(cmd, stdout=open(D + '/out.txt', 'w'), stderr=subprocess.STDOUT, start_new_session=True)
    open(D + '/qemu.pid', 'w').write(str(p.pid))
    print('qemu pid', p.pid)

def stop():
    try:
        pid = int(open(D + '/qemu.pid').read())
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass

if __name__ == '__main__':
    (stop if sys.argv[1:] == ['stop'] else start)()
