# Arquitetura do IDEmu

```
 SWFL (psdzdata, somente leitura)
        │  idemu/swfl.py  (extrai)        idemu/ifs.py (boot1.ifs → boot.ifs)
        ▼
 builder.py ──► boot.ifs  sda.img (QNX4)  sdb.img (QNX6)  shim.img (QNX4)
                 │            │               │               │
                 └────────────┴───────────────┴───────────────┘  carregados na RAM pelo QEMU (-device loader)
                                      │
   QEMU 11.1.2 + placa omap5-uevm (src/qemu) ── UART3 console ──► runtime.py (sequência de boot)
        │  ponte MMIO                 ── UART2 (/dev/ser4) ──────► ShellMux ► sshbridge.py ► sshd do macOS
        │  (OpenGL ES do guest)       ── UART1 (/dev/ser5) ──────► DataChannel ◄ canbus.py / gps.py
        ▼
   glhost (renderizador macOS, GLSL decompilado dos shaders SGX) ──► frame.rgb ──► /api/run/screen.png
                                          ▲
              entrada (rotor/teclas) ─────┘  ctl/glinput.cmd  ◄── /api/input/*
```

## Camadas e o que cada uma "traduz"
| Hardware real | Substituto | Onde |
|---|---|---|
| GPU PowerVR SGX544 (EGL/GLES2 binário) | ponte MMIO + `glhost` (OpenGL 2.1 do Mac) + shaders decompilados | `bin/`, `src/shim`, `src/glhost` |
| Gerenciador de tela QNX Screen / LayerManager (ILM) | bibliotecas `libscreen/libEGL/libGLESv2/libilmClient` do shim | `idemu/shim/lib` |
| Codificação do veículo (CAFD, 17 blocos) | `coding.tab` gerado do perfil do ambiente, aplicado por hook em memória; editor com backups e flash na interface | `codegen.py`, `coding.py`, `web/coding.js`, `src/shim/hook.c` |
| Entrada do guest | `input.sock` → glhost → thread de entrada no HMI | `runtime.py`, `src/glhost/host.c`, `src/shim/hook.c` |
| `starter` + watchdog originais | lista mínima de serviços resolvida do `starter.cfg` do próprio SWFL | `builder.py` (SERVICES), `guest/boot.sh` |
| Superfície e compositor do mapa (LayerManager + processo de navegação) | `hk_mapsurf`, `ilm.c`, `OP_MAPBIND`/`OP_MAPLAYER`, `map.c`, `mapsvc.py` | `src/shim`, `src/glhost`, `idemu/mapsvc.py` |
| Rotor/teclas iDrive | eventos injetados no processo HMI | `runtime.py`, `src/shim/hook.c` |
| V850 (SPI + DMA + GPIO) | transporte `ioipc-idemu.so` no lugar do SPI; io-ipc e decodificador originais; V850 emulado no host | `v850.py`, `src/v850/` (`docs/V850.md`) |
| CAN (V850 via SPI) | barramento virtual no host; estado entregue em `/var/idemu/can/<ID>` | `canbus.py`, `guest/agent.sh` |
| GPS u-blox (UART) | NMEA/UBX no host; sentenças em `/var/idemu/gps/<TIPO>` | `gps.py`, `guest/agent.sh` |
| Rede Ethernet/OBD (SSH) | `sshd` do macOS → console serial do guest | `sshbridge.py`, `sshshell.py` |

## Imagens do sistema intactas
`sda.img`/`sdb.img` só contêm arquivos dos SWFL (`build.json` lista o que foi omitido por tamanho ou por nome
longo demais para QNX4). O guest nunca grava nos arquivos de imagem: o QEMU copia cada imagem para a RAM.
Tudo que é "tradução" vive em `shim.img` e em symlinks do pathmgr criados na partida
(`ln -sP /fs/shim/lib/... /lib/...`), sem alterar nenhum arquivo do sistema.

## Limites conhecidos
* Só uma versão do HMI foi validada (sha256 em `idemu/data/known_hmi.json`); outras compilam, mas os patches
  em memória do shim usam endereços fixos desse binário e podem falhar.
* O CAN e o GPS chegam ao guest (arquivos em `/var/idemu`), mas o HMI **não** os consome: o iDrive recebe dados
  do carro por DSI/MOST (`most` + `NBTCarHU`), cujo servidor não está emulado. O V850 já existe (canais 0 e 26: controle
  de fluxo e watchdog), mas esses canais não levam dados do carro — ver `docs/V850.md`. Combustível, velocidade e relógio
  continuam "--".
* Sem rede no guest (o `sshd` do QNX não é usado); SSH leva ao console. `scp/sftp` não funcionam: use `push/pull`.
* Motor de navegação da BMW fora (o PSdZData não traz dados de mapa): o mapa é desenhado no host (`src/glhost/map.c`, `idemu/mapsvc.py`), sem rotas. Sem áudio e câmeras. Toque no display não é suportado.
* IDs CAN: nenhum sinal tem fonte pública de F-series; veja `source`/`confidence` em `idemu/data/can_signals.json`.
* O arquivo `libsys_data_prj_nbt_systemsettings2_cbmapping.cpp-ne.so` (nome > 48 caracteres) não cabe no QNX4.
* Boot: ≈ 0,8 s com o estado salvo; ≈ 24–31 s o boot completo; ≈ 33–45 s quando também salva o estado. Ver `docs/V850.md`, seção "Velocidade do boot e da emulação".

## iDrive 8
Outra placa QEMU (`virt`, ARM64 com HVF) e ponte gráfica própria sobre o ANGLE, com a mesma interface web (`idemu/mgu.py`). Ver `docs/OUTRAS_GERACOES.md`, código em `src/mgu22` e `tools/mgu`.
