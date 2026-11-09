#!/usr/bin/env python3
"""Aplica no rootfs do RSE (pasta extraída) os patches binários do emulador:
 * ioclcproxy e udpnm: mantêm a rede (NM) acordada;
 * HmiMain3D: o toque que o HMI monta a partir do ponteiro do mouse (CHmiWindowInputHandler -> CTouchDataClient::forwardTouchDataSync) (1) só segue para os
   ouvintes se o serviço de toque achar o dispositivo habilitado ("forwardTDSync: not forwarding data (false)") e (2) chega com o byte `send` (+0x20 do CTouchData) em 1,
   o que faz o reconhecedor de gestos tratar todo evento como início. Os 24 bytes do `cmp`/`jne`/log viram: zera o byte e salta para o encaminhamento;
   (3) o reconhecedor de gestos (0x659a6d0) descarta o evento se `IHmiTouchService::isEnabled(1)` (0x653b4d0) der falso: a função passa a devolver 1 (ver docs/OUTRAS_GERACOES.md).
Sem eles a NM do ioclcproxy e do udpnm volta ao sono, o NodeStateManager entra em ShutdownActive e o HMI não mostra nada.
Cada patch troca por `ret` o início dos slots busSleepState / prepareBusSleepState / readySleepState de NetworkManagementServer.
Uso: patch_rse.py PASTA_ROOTFS   (offsets válidos para RSE_MGU_01 030_016_002)"""
import sys, os
PATCHES = {'usr/bin/ioclcproxy': (0x6e070, 0x6e0c0, 0x6e1b0), 'usr/bin/udpnm': (0x18110, 0x18160, 0x18250)}
HMI_PATCHES = [('usr/bin/HmiMain3D', 0x6e8777b, bytes.fromhex('80bdd0fdffff000f85f803000041807f25600f86dd040000'), bytes.fromhex('498b0424c6402000e9f80300009090909090909090909090')),
               ('usr/bin/HmiMain3D', 0x653b4d0, bytes.fromhex('0fb647495548'), bytes.fromhex('b801000000c3'))]
root = sys.argv[1]
for rel, offs in PATCHES.items():
    p = os.path.join(root, rel); d = bytearray(open(p, 'rb').read())
    for o in offs:
        assert d[o:o + 4] == bytes.fromhex('4883ec28'), f'{rel}: prólogo inesperado em {o:#x} (versão diferente?)'
        d[o] = 0xC3
    open(p, 'wb').write(d); print('patch ok:', rel)
for rel, off, old, new in HMI_PATCHES:
    with open(os.path.join(root, rel), 'r+b') as f:
        f.seek(off); cur = f.read(len(old))
        assert cur == old, f'{rel}: bytes inesperados em {off:#x} ({cur.hex()}; versão diferente?)'
        f.seek(off); f.write(new)
    print('patch ok:', rel, hex(off))
