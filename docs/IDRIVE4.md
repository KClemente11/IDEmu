# iDrive 4 (CIC High, Harman "BMW L6") — estado em 2026-11-09

**Atualização 2026-11-09 (2): roda no app.** Em **Novo ambiente → iDrive 4** o IDEmu cria um ambiente `kind: cic`; **Compilar** monta a imagem
compartilhada em `<IDEmu>/cic` (`ifs.bin`, `flash.img`, `efs.ifs`, a partir de `swfl_000003a6` e `swfl_00000417` 008_090_002 da PSdZData; alguns
segundos) e **Iniciar** sobe `bin/qemu-system-sh4` (`idemu/cic.py`). A tela do carro mostra o Hauptmenü real; o boot leva ≈ 70 s até `running`.
* **Windows nativo**: o instalador inclui `bin/windows/qemu-system-sh4.exe`. O app lê o mesmo `frame.rgb` por um mapeamento Win32 e troca
  os telegramas do controlador por UDP em `127.0.0.1`. Nessa plataforma, `CIC_INPUT` aponta para o arquivo com a porta escolhida pelo QEMU e
  `CIC_OUTPUT` contém a porta do app. Veja a [instalação no Windows](WINDOWS.md#native-windows-installer).
* **Vídeo no app**: o QEMU grava a tela composta em `frame.rgb` (formato `IDFR` dos outros ambientes) quando `CIC_FRAME` está definido, no
  máximo ~30 quadros/s e só quando a VRAM das camadas muda (dirty log). Não depende da janela do QEMU.
* **Composição**: ignora o alpha da camada (o `libffb` não grava alpha no blend, então ele é inconsistente) e trata só a cor de limpeza
  `0xffffff00` como transparente. Isso eliminou o retângulo claro e a faixa escura perto do ícone.
* **Boot ≈ 2× mais rápido**: o log de depuração do QEMU (`-d guest_errors,unimp`, uma linha por acesso ao FPGA) fica desligado no app
  (`qemu_cmd(..., debug_log='')`; no `run.py` continua ligado, `CIC_D=` desliga) e o SCIF transmite em 1 µs por caractere em vez de 57.600 baud
  (o kernel esperava ativamente cada caractere do console; `CIC_SCIF_SLOW=1` volta ao antigo). `HMIReady` caiu de ~80 s para ~40 s do guest.
  O resto do tempo são esperas do plano do Root por dispositivos ausentes (entretenimento ~11 s, rádio ~4 s, navegação sem HD).
* **Rotor e teclas funcionam** (atualização 2026-11-09 (3)). O HMI recebe o controlador como mensagens MOST do FBlock
  `CentralControlSystem` = **0xE5** (instância 1 = ZGW_01) vindas do Root pelo canal MTP. Sem MOST (o `dev-mlb` nunca sai de `POST_STARTING`),
  o IDEmu faz o papel do controlador (ZBE) e injeta os telegramas no próprio HmiMain:
  * **Patch do HmiMain** (`tools/cic/hmiinput.py`, aplicado ao IFS2 da `flash.img` em `run.build_flash` e, nas imagens já montadas, por
    `patch_flash_file` ao iniciar): a thread receptora do MTP (laço em `0x08d086e8`, `recv` em `0x08d08534`) passa a chamar um stub em
    `CA4ADataProxyDispatch::onA4AOpenSession` (`0x08d871a4`, função sem uso no emulador). Na 1ª chamada o stub cria uma 2ª thread (128 KB
    de pilha) que roda o mesmo laço; nela, em vez de ler do Root, o stub pede telegramas ao QEMU a cada 20 ms. Assim o telegrama injetado
    segue exatamente o caminho de um telegrama real (evento `CSvcHBPlatformEvent` → `handleMostMessage` → proxy → controlador). Na thread
    real o stub descarta os erros do Root para 0xE5 (OpType 0x0F, "FBlock indisponível"). O envio (`sendMsg` em `0x08d0c1e4`, chamado em
    `0x08d084fa`) também passa pelo stub, que copia ao QEMU os telegramas do HMI para 0xE5.
  * **Hypercall do QEMU**: `trapa #0xC3` com `r0 = 0x1DE30000|op` (`build.sh` em `helper_trapa`, tratador em `src/cic/cic.c`): op 0 classifica
    a thread, op 1/2 entregam o próximo telegrama da fila (tamanho, depois palavras de 32 bits), op 3/4/5 recebem um telegrama enviado pelo
    HMI. A fila chega por `CIC_INPUT` (socket Unix de datagramas, linhas `t <hex>`) e o que o HMI envia sai por `CIC_OUTPUT` (`x <hex>`);
    `CIC_INPUT_DEBUG=1` mostra tudo no stderr.
  * **Controlador virtual** (`VirtualZBE` em `idemu/cic.py`): ao ficar `running`, manda o *registry changed* (tipo 7) anunciando E5.01 no
    endereço 0x0102; o HMI registra o proxy e pede notificação de 0xC10/0xC20/0xC30. Telegrama MOST: `[0..1]` tamanho, `[2]=2`, `[4..5]` origem,
    `[6]` FBlock, `[7]` instância, `[8..9]` FktID, `[10]` OpType (0x0C Status), `[11]=1`, dados. O 1º byte de dados é o controlador (1) e o 2º o
    HMI (0x1D); `cnt` é o contador de mensagens do controlador, comum a todas as funções (o HMI descarta repetições).
    | FktID | função | dados |
    |---|---|---|
    | 0xC10 | RotaryEncoder | `01 1D cnt pos_hi pos_lo 1E 00`: posição absoluta; o HMI anda pela diferença (eventos 13/14) |
    | 0xC20 | PushButton | `01 1D cnt estado dir campo bits`: estado 1 apertado / 0 solto; campo `1E` + bits 1 = aperto do controlador; campo `1D` + dir (1 cima, 2 direita, 4 baixo, 8 esquerda; os eventos do HMI são 9 cima, 12 direita, 10 baixo, 11 esquerda) = inclinação; campo 0 + bits = teclas (1 MENU, 2 BACK, 4 OPTION, 8 RADIO, 16 CD, 32 NAV, 64 TEL) |
    | 0xC30 | RotaryEncoderConfig | o HMI manda `Set` `1D 01 nn 00 00 00 7F FF 1E`; a resposta `01 1D nn 00` (mesmo `nn`) habilita o rotor |
  * Testado no app: o rotor percorre o Hauptmenü, o aperto abre Radio e CD/Multimedia, BACK/MENU/OPTION, inclinação para a direita/esquerda
    (entra/sai de submenus) e as teclas RADIO e CD (MAP e MEDIA no app). NAV e TEL não reagem nesta configuração (sem navegação nem telefone).
    A tela leva alguns segundos para reagir (emulação lenta do desenho).
  * **Flash por execução**: o app passa ao QEMU um clone APFS da `flash.img` (`qemu_cmd(..., flash=...)`) em vez de `snapshot=on`. Com o
    overlay qcow2 temporário o QEMU travou uma vez numa gravação da flash (vCPU parado em `pflash_write → blk_pwrite → aio_poll`).


**Atualização 2026-11-08 (noite): a GUI do HMI aparece.** O `HmiMain` fica vivo, o Root chega ao modo 4 (operação completa, `Executor state: Current=4`) e a tela
mostra o **Hauptmenü** real (Radio / Fahrzeuginfo / Einstellungen, relógio `--:--`), captura em `docs/idrive4-hmi.png`. O que destravou, nesta ordem:
1. **Crash aleatório do `devc-sersci`** (`SIGSEGV ip=88009162`): o handler de instrução ilegal do procnto faz `pref @spc` para carregar a TLB antes de uma janela com
   SSR/SPC/banco 1 já carregados; no QEMU o `PREF` não fazia nada, o TLB miss acontecia dentro da janela e destruía r1. Agora `PREF` privilegiado carrega a TLB (`build.sh`).
2. **Por que o `HmiMain` saía**: a thread do `CHmiICProcUnit` (painel de instrumentos) não rodava porque `CHmiInstrumentClusterApp::init()` falhava em
   `CPrcMenu::loadGui` (recurso de GUI 2014 inexistente). Os `ResDB.*` do HMI (`menu`, `bitmap`, `text`, `model`, `colors`...) estão em `/usr/Hmi/data/ro` ->
   `/mnt/EFS_RO/Hmi/data/ro`, **dentro do FFS3 original do EFS_RO** (segmento `0x04D80000` do pacote 3a6), que tínhamos trocado por um imagefs só com os tar.gz do HD.
   Novo `tools/cic/ffs3.py` (extrator de QNX FFS3) e o `efs.py` agora juntam o FFS3 original (prioridade) com o conteúdo do HD; das imagens `ResDB.vehicle-*` só
   entram as que cabem na flash livre (até a partição HBpersistence). Apague `/tmp/cic/efs.ifs` para reconstruir.
3. **`23ecu` (reset de ECU) logo após o boot**: era o `CPAudioWrapper` ("DSP heartbeat failed"/"DSP didn't start": não há DSP de áudio). Patch `CIC_NODSPRESET`
   (padrão 1) tira as duas chamadas de reset. `CIC_CLAMP` passou a ter padrão 1 (configuração testada).
4. Depuração: o gdbstub esvazia o cache de tradução ao inserir breakpoint (`build.sh`), senão breakpoints reinseridos eram perdidos.

**Atualização 2026-11-09: artefatos de desenho corrigidos.** Captura nova em `docs/idrive4-hmi.png` (sem retângulos brancos; aro cromado,
moldura laranja de foco e "CD/Multimedia" corretos). O que era:
* **Scanout** (`src/cic/cic_pci.c`): agora compõe as camadas L0..L5 do display 0 (registradores do MB86297: `Ln_EXT_MODE` bit 31 =
  ligada, `Ln_MODE_W_H`, `Ln_ORG_ADR`) sobre fundo preto com o alpha por pixel; `0x10008c` era o `L5_ORG_ADR`. O `libffb` não grava alpha
  no blend, então pixel com alpha 0 que não seja a cor `0xffffff00` é tratado como opaco. Só recompõe quando a configuração das camadas
  muda ou a VRAM delas é escrita (dirty log), porque a composição roda com o lock global.
* **`CIC_HMISRCM1`** (padrão 1, patch no HmiMain do IFS2): o HMI mistura imagens em duas passadas, RGB (planemask `0x00ffffff`, modo
  `SRC_M1/DST_1mM1`) e só alpha (planemask `0xff000000`, `SRC_1/DST_1mM1`). O `libffb` ignora o planemask e a 2ª passada vira, no RGB,
  `src + dst*(1-As)`: onde a imagem tem branco transparente satura em branco. A 2ª passada passa a usar `SRC_M1` (um "over" normal).
* **`CIC_NOESSENTIAL`** (padrão 1, patch no Root): sem HD o `PNaviWrapper` só fica pronto por timeout (~45 s), o HMI registra depois e
  o plano `pre2 -> 2` estoura o prazo de componentes essenciais (`PPersistencyWrapper`, `PDiagnosisWrapper`), levando a
  `STATE_EXECUTOR_ERROR`/`23err`. O tratamento de componente essencial vira o de não essencial; o Root fica em `pre2` e o HMI no ar.
* Restam detalhes pequenos: um retângulo levemente mais claro atrás do ícone redondo e uma faixa escura no alto à esquerda.
* Ferramentas: `CIC_VRAM_TRACE=0xVALOR` (QEMU) registra quem grava um valor na VRAM; o gdbstub esvazia o cache de tradução ao inserir
  breakpoint.

Pendências do HMI: (a) os dois detalhes acima; (b) não há entrada: o controlador iDrive (ZBE) e as teclas chegam por CAN/MOST, que não
são emulados; (c) o boot até o HMI leva ~80 s de tempo do guest por causa dos timeouts de navegação/HD.

**Atualização 2026-11-08 (tarde):** o Root agora chega a `PHMIWrapper::RegistrationComplete`/`HMIReady`, o starter monta o IFS2 sozinho (`multicored`/`pipe` sobem), e
o `HmiMain` inicia e registra o displayable (`cid 256 1280x480`), mas **sai com EXIT_FAILURE ~4 s depois** (causa não achada; o log dele mostra só `GF CALL: gf_dev_select_zone id=2`
e `MTP:Channel connect succeeded`), então a tela continua no splash. Dois problemas de estabilidade restam (ver "Pendências").

**Resumo:** o iDrive 4 **já mostra vídeo no emulador**: a tela de abertura **BMW (splash)** do firmware original aparece em 1280x480, decodificada pelo
`layermanager` e desenhada pelo `libffb` (renderizador por software do QNX) direto na VRAM do Carmine emulado. A **interface (HMI)** ainda **não** aparece:
depois de `DM642::Loaded` o `CicHighEceUsaSecond`/HMI sobe e o sistema fica em CPU 100 % sem novos logs. Captura em `docs/idrive4-splash.png`; gerada com `python3 tools/cic/screen.py`.

## Como o vídeo chega à tela (resumo do que foi feito em 2026-11-08)
* **Carmine** (`src/cic/cic_pci.c`): BAR2 = VRAM de 128 MB (RAM), BAR3 = registradores de 8 MB; janela PCI idêntica ao físico (o `build.sh` alarga o PPN da UTLB para 32 bits);
  FIFO/sincronização/ISR/I2C simulados só o suficiente para o `devg-carmine.so` inicializar; saída pela camada 4 (`0x10008c` = endereço na VRAM), palavras de 32 bits `R<<24|G<<16|B<<8|A`.
  **Não há interpretador das display lists do Carmine**: o `devg-carmine.so` é alterado em memória (patch no IFS, `CIC_SWDRAW`, padrão 1) para que `devg_get_corefuncs` e
  `devg_get_contextfuncs` não sobrescrevam as rotinas de desenho do `libffb` (software) com as do hardware; `wait_idle`, `nlfuncs`, `isr` e o gerenciador de memória continuam os do Carmine.
* **Interrupção do FPGA** em IRL 10 (`INTEVT 0x340`) com máscara `INT2MSKR`; **RAM** acima de 256 MB em `0x58000000` (`CIC_RAM`, padrão 384 MB; o IFS2 de 34 MB precisa dela).
* **O Root (`CicHighEceUsaRoot`) é remendado em memória** (`tools/cic/run.py`, todos ligados por padrão; `=0` desliga) porque não há MOST, Ethernet nem decodificador de vídeo:

| variável | o que faz |
|---|---|
| `CIC_EMPTYMODE` | `CPOnOffRequestorCic`: o pedido de modo interno vazio (`''`) deixa de pedir um estado ao executor (era ele que levava ao `23ecu`/ECU reset) |
| `CIC_MOSTSKIP` | `CMOSTStateFSM::fullyOperable()` vai de `Unloaded` direto para `FullyOperable` (o `dev-mlb` nunca chega a `RUN`, falta o núcleo MLB/INIC) |
| `CIC_NOETH` | `CEthernetStateFSM::triggerStartIONet()` vai direto para `IONetStarted` (o `io-net` espera o NIC Micrel e `/etc/IFS2Ready`) |
| `CIC_NOVIDEO` | `CPVideoWrapper::triggerFullyOperable()` chama o setter de estado direto (o `dev-videoctrl` morre: falta o decodificador SAA717x no I2C do Carmine) |
| `CIC_SWDRAW` | `1` (padrão) = os dois patches do `devg-carmine.so`; `core` ou `ctx` = só um (para diagnóstico) |
| `CIC_NORESET`, `CIC_NOECURESET` | só depuração: ignora o pedido de reset à IOC (canal 2) e transforma `executeReset()` em `rts` |
| `CIC_NODSPRESET` | `CPAudioWrapper` não pede mais reset de ECU (`23ecu`) quando o DSP de áudio não responde (padrão 1) |
| `CIC_CLAMP` | timeout do estado de bornes vale Clamp15 (ignição ligada); padrão 1 |
| `CIC_NOESSENTIAL` | componente essencial que estoura o prazo do plano é tratado como não essencial (padrão 1) |
| `CIC_HMISRCM1` | HmiMain: a passada "só alpha" das misturas usa SRC_M1 (o libffb ignora planemask; padrão 1) |
| `CIC_NOHEARTBEAT` | experimento antigo (padrão desligado) |
| `CIC_WUR`, `CIC_IOC3`, `CIC_E2P_FILL` | (QEMU) motivo de wake-up, estado externo e preenchimento da E2P enviados pela IOC emulada |
| `CIC_DISPLAY=cocoa` | abre a janela do QEMU (o padrão é sem janela) |

* Ferramentas novas: `elfx.py` (strings/xref/desmontagem de ELF SH-4), `dll_trace.py` (acha a base de um DLL pelo `dlopen`), `vram.py` (VRAM -> PNG), `screen.py` (tela -> PNG), `trace_ipc.py`.
* Como achar o que o Root espera (útil para o próximo passo): plano do `COnOffExecutor`: breakpoints no gdbstub (`CIC_XARGS="-gdb tcp:127.0.0.1:1234"`) na rotina de log
  `0x8070740` (formato em `r5`) mostram `COnOffCtrlPlanRequestStep/SyncStep`, as transições das FSMs e `Executor state`; o plano que não termina é o que falta.

## Novidades da tarde (patches em `run.py`, todos com padrão ligado)
| variável | o que faz |
|---|---|
| `CIC_NOWDOG` | watchdog do Root, do Second e do HmiMain (`started (watchdog is enabled)`) desligado: o padrão do parser de argumentos vira "disabled"; sem isto uma thread atrasada derrubava o Root e o starter (`FinalAction SHUTDOWN_SYSTEM`) reiniciava o sistema em ciclo |
| `CIC_IFS2` (`0`) | o IFS2 é montado pelo starter (processo `memifs2`, que fornece o interface `/etc/IFS2Ready`); o roteiro de boot só copia `memifs2` para `/tmp` e o `starter.cfg` aponta para a cópia (`/tmp/////memifs2`) — antes o starter não achava `/usr/bin/memifs2` e `multicored`, `pipe`, `HmiMain` etc. ficavam em `PRE_STARTING` |
| `CIC_IONET` | o roteiro de boot inicia `io-net -ptcpip-v4` depois que `/etc/IFS2Ready` existe (sem sockets o Second/HmiMain entravam em laço de `socket: Address family not supported`) |
| `CIC_IFS2READY` (`0`) | experimento: renomear o interface 33 no `starter.cfg` (não funciona: o starter só reage a eventos) |

QEMU: o `build.sh` agora corrige a **busca do delay slot de um RTE**: o `get_physical_address` usava o SR já restaurado (modo usuário) e dava `Unauthorized access` quando a página do kernel
não estava no TLB do softmmu, matando o processo com `SIGSEGV ip=<RTE> ref=<RTE+2>` (era o que derrubava o `HmiMain` numa das execuções). `CIC_XARGS="-accel tcg,one-insn-per-tb=on"` elimina
essa classe de erro mas deixa o guest lento demais (timeouts do IPC).

## Pendências conhecidas (depois do vídeo)
0. **Estabilidade**: `devc-sersci` (e às vezes `vdev-tunnelipc`) morrem com `SIGSEGV ip=88009162 ref=cfff7f0f` (ou `ip=88048e9a`): `mov.w @r1,r0` no tratador de exceção do kernel (lê a instrução do
   usuário em SPC) com `r1` ímpar (`0xcfff7f0f`/`0xcfff7fff`). Sem o `devc-sersci` o console e o log (`slog`) param. Causa provável: outro caso de TLB/SPC no QEMU. `HmiMain` sai com EXIT_FAILURE
   mesmo sem esses SIGSEGV; precisa de depuração (ver os `__assert`/`_exit` via gdbstub com `libc.so.2` em `0x70300000`).
1. **HMI**: depois de `DM642::Loaded` o guest fica sem logs com a CPU a 100 % (memória? loop?). Falta descobrir o que o `CicHighEceUsaSecond`/`HmiMain` faz ali.
2. **Reinicializações**: com a flash recém-gravada o boot reinicia uma vez (formata `HBpersistence`/`logistics`, esperado). Em execuções mais longas aparecem
   `devf ... f3s_aCFI_v2write ... program verify error` (gravação em buffer na partição `fs1p1`) e o Root pede reset: a emulação da gravação em buffer da NOR (`pflash_cfi02`) precisa de revisão.
3. **MOST/INIC, Ethernet, SAA717x, DM642/DRA300, HDD**: ficaram só "contornados" pelos patches acima.
4. A saída de vídeo mostra só a camada 4; falta combinar as camadas (HMI usa várias) e o segundo display.

(O texto abaixo descreve o estado de 2026-11-07 e está desatualizado nas partes de Carmine/PCI/RAM.)

## O que é
Os pacotes de `~/Downloads/System files/ID4` (SWFL `008_090_002`, conjunto L6 de 11 pacotes) são do **CIC High**:
CPU Renesas **SH7785 (SH-4A)**, **QNX 6.3.2**, imagem de boot **XIP/LZO** (`swfl_000003a6`, "App ECE").
Os outros pacotes são firmwares de periféricos: IO-Controller (`415`, `42b`), FPGA (`416`), HMI (`417`), idioma (`45d`),
DVD (`45e`), DAB (`45f`), IBOC (`460`), SDARS (`7b7`).

O `starter.cfg` da imagem lista 69 processos. Eles mostram a placa: um **FPGA Xilinx** (PCI 10EE:7534) faz de ponte para quase tudo
(`dev-mlb`, `dev-ipc` com o IO-Controller, áudio, SPI, SSI, UARTs 8250, EIDE do HD/DVD, NVRAM), mais o **Fujitsu Carmine** (PCI 10CF:202B,
`io-display`/`devg-carmine`), USB OHCI/EHCI, a placa de rede Micrel KSZ8841, flash NOR (`devf-generic`) e dois DSPs (DRA300 e DM642)
carregados por `dev-dspipc`. O aplicativo principal é `/usr/HBproject/CicHighEceUsaRoot`.

## O que já funciona
* **Placa `cic` do QEMU 11.1.2** (`src/cic/`): SH7785 (modelo `sh7785` do QEMU), RAM em `0x08000000`, registradores da CPU/MMU, controlador de interrupções
  **INT2** (tabela de vetores lida do próprio QNX), TMU (tick do sistema), duas SCIF (`cic_scif.c`, com a semântica de FIFO do SH7785, inclusive a contagem de RX
  em `+0x20`), **PCI** (`cic_pci.c`: ponte do SH7785 em `0xFE040000`, janela de memória PCI `0xD8000000..` → físico `0x18000000..`), **FPGA** Xilinx 10EE:7534
  (16 MB de registradores com log), **Carmine** 10CF:202B (só memória) e uma **NOR CFI de 128 MB** em `0x0` com IFS, IFS2, EFS_RO e HMI dos pacotes.
  Os periféricos on-chip aparecem em P4 (`0xE0000000+`) e no físico `0x1C000000+` (área 7), como no chip.
  Correções no QEMU, aplicadas por `src/cic/build.sh`: `-d int` mostra TEA/TRA; **o contador URC da UTLB não pode chegar a URB** (senão o QEMU sobrescrevia a entrada fixa
  da página da CPU do QNX e os processos morriam em `0x7bff0000`); o `movua.l` do SH-4A passa a poder cruzar páginas (antes abortava o QEMU).
* **Startup e kernel do QNX 6.3**: o `startup-sh7785` da Harman roda inteiro com `-vvv`; o `procnto-instr` sobe e o **shell responde** (`echo`, `pidin`).
* **O starter da Harman (69 processos) anda e chega ao aplicativo principal**: sobem `pci-sh7785` (acha a ponte, o FPGA e o Carmine), `dev-sysregs`
  (com `PCIDMA_TEST_MODVER`), `dev-ipc` (canais `ioc/ch2,5,6`), `dev-mlb`, `io-audio`, `dev-mv2trace`, `devf-generic` (identifica a flash) e, do IFS2,
  `vdev-tunnelipc` etc. O **`CicHighEceUsaRoot` inicia** ("### Starting CicHighEceUsaRoot") e sai porque ninguém responde do outro lado do IPC (ver abaixo).
* **EFS_RO**: o original é um FFS3 de flash cuja tabela de partições não vem nos pacotes (o `devf-generic` cria só uma partição crua). O `tools/cic/efs.py` monta a
  árvore a partir dos três `tar.gz` do pacote `3a6` (fontes, `res`, `opt`, `usr`...; sem mapas e sem voz por falta de espaço) num imagefs (`mkimagefs.py`),
  que o `run.py` grava na flash em `0x4D80000` e monta com `memifs2 -D ... /mnt/EFS_RO` (o `-D` desliga o DMA, que o DMAC não emula). O IFS2 também sobe sem DMA
  (o `run.py` troca `-3` por `-D` no `starter.cfg`, em memória).
* O IPL da Harman não existe nos pacotes. O IDEmu faz o papel dele: carrega o IFS em `0x08010000`, entra em `0x880138e0` e grava na cabeça do IFS a lista de
  parâmetros (tag `0x8004` = RAM) e os argumentos do startup (`-vvv -D0xFFEB0000...`).

## Como rodar
```bash
src/cic/build.sh                      # compila o qemu-system-sh4 (precisa do código-fonte do QEMU 11.1.2 em ~/id4-qemu)
python3 tools/cic/run.py start        # sobe o CIC; o console QNX fica em /tmp/cic/ser1.sock e o log em /tmp/cic/ser1.log
python3 tools/cic/console.py 'echo oi' 'pidin'
python3 tools/cic/run.py stop
CIC_CMDS=comandos.sh python3 tools/cic/run.py start   # roda o arquivo no boot (no lugar do slogger) e depois dá o shell
```
Para ver o starter da Harman trabalhando, o `comandos.sh` pode ter `slogger -s128 &` e `srv-starter-QNX -c /etc/starter.cfg -vvv -g -u &`;
depois `python3 tools/cic/console.py 'sloginfo' 'pidin'`. (`CIC_STARTER=1` roda o starter no lugar do shell, sem console.)
Variáveis de depuração do QEMU: `CIC_FPGA_INIT="off=val,..."` (valores iniciais do FPGA), `CIC_CATCHALL=1` (loga acessos a endereços sem dispositivo),
`CIC_NOFPGA`, `CIC_NOCARMINE`.
`tools/cic/` também tem: `ifsx.py` (extrai o IFS LZO), `dis.py` (desmontador SH-4A completo), `gdbc.py` e `trace_fault.py`/`trace_isr.py`
(depurador pelo gdbstub do QEMU, passo a passo), `bootinfo.py` (monta a imagem de boot e edita o IFS) e `qrun.py` (execução curta com log).
O `run.py` troca a senha do root por `root`, o `login` por um `ksh`, o starter por `echo` e põe `PCIDMA_TEST_MODVER=1` no ambiente **na cópia em memória**;
os pacotes não são alterados.

## O que falta (nesta ordem)
1. **IO-Controller** (botões, rotor, CAN, liga/desliga): é um microcontrolador **ST10** (o `sysregs-l6-7534.cfg` diz "controlled by ST10") com firmware nos pacotes
   `415`/`42b`. **O enlace IPC com a IOC já funciona**: o `CicHighEceUsaRoot` imprime `Got ext. clients` e conversa com a IOC emulada (modelo em `src/cic/cic_pci.c`).
   * **Registradores** (`dev-ipc -A 0xB0000`, desmontado com `tools/cic/dis.py` e `tools/cic/elfx.py`): `+0x34` é um registrador indexado (grava 0,4,5,6 e lê: módulo `0x0A`,
     versão `04 49 2A`; gravar 0 marca um novo boot do SH4 e reinicia a IOC); `+0x10` é a janela de dados (4 bytes por palavra); `+0x14` é o comando (`0x02` zera o TX, `0x10` envia,
     `0x01` começa a ler um quadro, `0x40` libera o quadro lido, `0x20`/`0x80` reconhecem os bits 5/7); `+0x18` é o status (bit 5 = quadro recebido, bit 7 = envio concluído) e `+0x1C` a máscara.
   * **Quadro**: `[len][canal]` + `len` bytes de payload (total `len+2`). Canal 0 = controle, tipo `0x10` = lista de clientes (`[0x10, n]` + `n` entradas `[canal, clientes, fluxo=1, 0]`).
   * **Interrupção**: o `-i 1` do `dev-ipc` é só o pino PCI; o IRQ real do QNX é o **10** (vetor 106 do kernel, o ISR `0x08043060`). O callout `id` das IRL calcula `vetor = 96 + (INTEVT-0x200)/0x20`,
     então o FPGA é a **IRL 10 = INTEVT `0x340`**. Ligar o FPGA ao INT2 (`0x600`/`0x620`) não funciona: `0x600` cai num nível sem handlers e `0x620..` aciona os `InterruptAttachEvent` do DMA.
     O modelo implementa `INT2MSKR/MSKCR` (`0xffd40080/84`: o callout mascara a fonte ao entrar e a libera no eoi) e o status do INTC (`0xffd00024`, precisa ser > `0x0f000000`).
     `CIC_FPGA_IRQ=0` desliga a interrupção; `CIC_XARGS="..."` passa argumentos extras ao QEMU; o `build.sh` faz o `sh_intc` respeitar o nível das IRL.
   * **Canal 2 (on/off)**: mensagens de 9 bytes nos dois sentidos: `[0]=0x12` (versão), `[1]` motivo de wake-up (6), `[3]` estado externo, `[4]` Ethernet da IOC, `[5]` tensão bruta,
     `[6]` evento (0 = nenhum), `[7]` parâmetro. A IOC publica o status a cada 250 ms (senão o `ipcRead` do app dá timeout em 1,5 s e ele pede reset).
   * **Canal 6 (túnel, `vdev-tunnelipc`)**: o primeiro byte do payload escolhe o subcanal (3 = **E2P**, a EEPROM que fica atrás da IOC). `vdev-eeprom` manda `03 01 end_lo end_hi len 01`
     (1 = ler, 2 = gravar) e espera um ACK de 5 bytes (`03 AA 00 00 00 01`) e uma mensagem de dados `03 03 end_lo end_hi len <dados>`. A EEPROM emulada tem 4 KB zerados.
   * **Logs do app**: o app escreve no `slogger`; o boot do `run.py` faz `sloginfo -w > /dev/ser2`, que vai para `/tmp/cic/ser0.txt` (muito mais informativo que o console).
2. **DSPs**: `dev-dspipc` falha com `FpgaEmifAttach: Module 040506 not known` (módulo EMIF do FPGA que o stub não tem) e depois precisaria carregar `DRA300` e `DM642`.
3. **Carmine (GPU/display)**: `io-display` e o `layermanager` só sobem depois do que está acima, e `devg-carmine.so`, `libGLES_CM.so.1` e `libgf` desenham pelo hardware. Sem
   compilador SH no Mac, a opção é um modelo do Carmine no QEMU (registradores e listas de desenho) ou trocar essas bibliotecas por montagem manual.
4. **Partições graváveis**: criadas pelo boot do `run.py` com `flashctl` nos 3 MB livres do fim da flash (`HBpersistence` 2 MB em `127872K`, `logistics` 1,1 MB em `129920K`); o `efs.ifs`
   (49,6 MB) ocupa a flash até `0x7CD9543`, por isso o segmento HMI do pacote não é mais gravado. Para o `devf-generic` apagar/gravar foi preciso ensinar ao QEMU o conjunto de comandos de
   proteção de setor do S29GL (PPB, `AA 55 C0` ... `90 00`; patch do `build.sh` em `pflash_cfi02.c`): sem ele o FFS3 monta a partição como somente leitura. Os dados que ficaram de fora do EFS_RO
   (mapas, voz, o FFS3 original de 32 MB) continuam faltando.
5. **FPGA**: o IDE (`devb-eide-hbfpga`) desiste por falta de disco (esperado). **O módulo de DMA do FPGA (`pcidma`, versão `040506`) não existe**: o `deva-ctrl-hb_fpga.so` (áudio) entra num loop
   infinito ao calcular o tamanho do buffer (limite 0) e, com prioridade igual à do `dev-ipc`, esgota a CPU; por isso o `run.py` desliga o `io-audio` (`CIC_AUDIO=1` reativa).

**Onde o app para hoje** (`/tmp/cic/ser0.txt`): chega a `OPERATING STATE REACHED::1`, `PSystemWrapper::IPCReady`, `PPersistencyWrapper::EarlyPersistency`, `PPDCWrapper::Loaded`, mas
(a) o `layermanager` e o `dev-videoctrl` falham em `gf_dev_attach()` (sem driver do Carmine), (b) o `PHDDShutdownWrapper` (essencial) dá timeout porque não há HDD e (c) o app tenta lançar
`CicHighEceUsaSecond`, que fica no IFS2, e esse IFS2 (pacote `SECOND_PHASE`) o starter só monta quando o Root pede. O estado de ECU reset (`23err`) é consequência de (a)/(b).
