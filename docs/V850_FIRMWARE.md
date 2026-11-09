# Firmware do V850 / RH850 (IOC) na PSdZData

A PSdZData traz o firmware **completo** do microcontrolador da head unit (o que `docs/V850.md` chama de V850) e as tabelas de
gateway que ele usa. O IDEmu ainda não executa esse firmware (o V850 virtual de `idemu/v850.py` imita o comportamento), mas ele é a
referência do que o V850 real sabe fazer. Este documento registra o que foi achado e como reproduzir.

Legenda: **[lido]** = está nos arquivos; **[inferido]** = conclusão minha a partir de nomes e comportamento, sem confirmação direta.

## Onde está

Nos pacotes SWFL da NBT Evo (versão `007_051_002`; os mesmos ids existem em versões mais antigas), como blocos com
`Tag=IOC_FLASH` ou `Tag=GATEWAY_FLASH` (o nome interno do microcontrolador é **IOC**). Cada bloco tem `Address=` (endereço na
flash do V850) e `SEL_HWINDEX=` (revisão de hardware em que vale). **[lido]**

| Bloco | Pacote | Tamanho | Endereço | `SEL_HWINDEX` |
|---|---|---|---|---|
| `v850ApplicationFlash` | `swfl_0000271a` | 786.367 B | `0xA0040` | `2-3` |
| `rh850ApplicationFlash` | `swfl_0000271a` | 772.970 B | `0xA0200` | `4-*` |
| `v850ApplicationRseFlash` | `swfl_00002734` | 1.179.583 B | `0x40040` | `3-*` |
| `v850GWTableFlash` / `rh850GWTableFlash` | `swfl_0000271f` | 655.360 B cada | `0x160000` | `2-3` / `4-*` |

* As duas tabelas de gateway são **idênticas byte a byte** (sha1 `797c74e9…`); 113 das 160 páginas de 4 KB têm dados, o último byte
  útil está no offset `0x70547`, o cabeçalho começa com `03 00 14 09 08 12 39 1a 5d 23 e5 2b e1 34 19 42`. **[lido]**
* As imagens de aplicação são código em claro (entropia 5,2 a 5,4, sem criptografia). **[lido]**
* Existem também tabelas parecidas em `swe/gwtb/` (22 arquivos de 131 KB a 556 KB, de outros módulos). Não foram abertas. **[lido: só os tamanhos]**
* `SEL_HWINDEX` = índice de hardware interno do IOC: o `ipc-version-check` do QNX lê `internal_hardware_index` do `IOC_BM_INFO`
  (ver abaixo). Daí `2-3` = V850 e `4-*` = RH850 (família mais nova). **[inferido]**

## O que o firmware diz de si (strings)

| | V850 (`2-3`) | RH850 (`4-*`) | RSE |
|---|---|---|---|
| Aplicação | `8140_APPL` | `8140_APPL` | `8173_APPL` |
| Compilação | 8 jun 2017 15:20:16 | 27 jan 2020 12:37:11 | 24 mai 2021 07:58:47 |
| Dispositivo | `Headunit C1` | `Headunit D6` | `RSE C1` |
| Componentes | `BMW UGW2 V2.1.007`, `BMW DiagnosticsRouter V2.1.005` | os mesmos (datas de jan/2017) | (sem gateway) |
| Base do gateway | `V000-009-051-00337` (`K2L Composer/BMW ZGW`, 27/08/2013) | igual | — |
| Identificadores de boot | `DV850T05xxxxxV107` / `…V108` | — | `DV850T05xxxxxV107` |
| Chips reconhecidos | — | — | `UPD70F3554`, `UPD70F3558`, `UPD70F4006` |

**[lido]** O bootloader embutido (`BIOSControl V850`) tem console de depuração por UART com: interpretador de roteiros
(`@start`, `@loop`, `@sleep`, `@label`), estatística por interface de comunicação (recebidos/transmitidos/repetidos/perdidos/erro de TX),
modo gateway com log filtrável, leitura dos fatores de wake-up (`WUFL0…WUFH1`), causa do reset (power-up, externo, watchdog), blocos
de ajuste do usuário com contagem de apagamentos e CRC, SPI (`CSIG`/`CSIH`), CAN e ASC (UART). Há roteiros de inicialização em
texto na própria imagem (`// start CAN; init TJA1043`, `// set Fan PWM to 7000`).

## Canais e filas do `io-ipc` que o firmware registra **[lido]**

35 nomes na imagem da head unit (25 na RSE), nesta ordem de tabela:

`IpcTest` `cfDsi` `cfSp` `IpcEnv` `IpcDGW` `IpcSGW` `IpcWatchDog` `IpcTouch_O5` `IpcTestSend` `cfDsiData` `cfAmpData` `IpcSysSet`
`IpcAmpControl` `IpcFANControl` `IpcSGW_O5` `IpcO5WatchDog` `IpcTestO5` `IpcWatchDogJ5Send` `IpcWatchDogO5Send` `IpcSysSetSend`
`cfMbxEvent` `cfDrData` `IpcOnOff` `IpcRes03` `IpcRes07` `IpcRes12` `IpcErrMemAppClient` `IpcErrMemApp` `IpcNBTGwDiag` `IpcPGWCtrl`
`IpcSGWCtrl` `IpctrustedVIN_Ctrl` `IpcOnOffSend` `IpcEnvSend` `IpctrustedVIN_CtrlSend`

Funções que o firmware implementa: gateway de sinais (SGW) e de diagnóstico (DGW), roteador de diagnóstico (`DiagRouter`), serviço CAN
(`CanService`), controle do amplificador (liga/desliga, curto à terra, curto à bateria, carga aberta), controle do ventilador (`FanCtrl`),
memória de erros (`ErrMem`), ponte DSI/MOST (`DsiBridge`), VIN confiável.

**A tabela guarda só os nomes, sem os números.** A correspondência com `/dev/ipc/ipcNN` só está confirmada para:

| Canal | Cliente (evidência) |
|---|---|
| 25 | `most` (ponte DSI) — modelado |
| 26 | `watchdog5-omap` (`v850channel=/dev/ipc/ipc26`, `starter.cfg`) — modelado |
| 27 | `touchComDevice` (string `/dev/ipc/ipc27`, "test DSI communication to V850"); o firmware tem `IpcTouch_O5` — **não modelado** |
| 7 | `dev-navsens` (padrão `/dev/ipc/ipc7`, "sensor raw data") — o cliente não roda no IDEmu |
| 5 | `ipc5`, fornecido pelo `dev-spi` (ver abaixo) |

Outros clientes do V850 no QNX: `OnOffHuOmapApp` e `OnOffDSICommander` (`V850OnOffIPC`, `V850Wrapper`: liga/desliga), `CSI_NBT`,
`devu-cdc_tcm-io_amp` (amplificador). Nenhum deles roda no IDEmu hoje.

## Duas variantes de transporte no `starter.cfg` **[lido]**

* `dev-spi-omap543x -c /etc/dev-spi_v850_omap543x.cfg` (processo 50, `VariantCode 0x80000000`, máscara `0x82000000`): SPI2
  (`0x4809A000`, DMA 8/9) com o `ipc-plugin.so` e **os canais 1 a 20** (`1;2;5;3;4;6;…;20`, o 10 e o 18 com `:3:IPC`). Fornece `ipc5`.
* `io-ipc -c /etc/io-ipc-o5.cfg` (processo 51, `VariantCode 0x82000000`): o caminho que o IDEmu usa, canais lógicos 0, 1 e 25 a 28.

As duas variantes se excluem pelo bit 25 do `VariantCode` (qual configuração de carro usa cada uma não foi levantado). O IDEmu só cobre a
segunda; os canais 1 a 20 do `ipc-plugin` nunca aparecem no tráfego.

## Versão do protocolo IPC e informação de boot do IOC **[lido]**

O utilitário `ipc-version-check` do SWFL diz qual protocolo IPC o V850 fala: **0** = IPC inicial, **1** = IPC em blocos no Jacinto,
**2** = IPC em blocos no Jacinto e no OMAP (código de saída 0, 1 ou 2; 3 = erro). Ele lê o resultado de um bloco `IOC_BM_INFO` que o
bootloader do V850 deixa na memória física (endereço vem de `_UCS_BOOTCFG`, que o IPL do QNX passa ao sistema), com
`ioc_boot_info_ipc_protocol_version`, `…internal_hardware_index`, `…boot_loader_active` e `…wakeup_reason`; e de `IOC_BOOTMODE`.
O IDEmu não fornece `_UCS_BOOTCFG` nem esse bloco. Nenhum serviço do `starter.cfg` chama o utilitário.

## O que o IDEmu usa e o que não usa

* **Usa:** nada do firmware em execução. O V850 virtual conhece os canais 0, 25 e 26 (`docs/V850.md`).
* **Novo:** `idemu/v850fw.py` lê os blocos IOC/gateway dos pacotes, identifica o firmware e extrai os nomes dos canais;
  `idemu/data/v850_firmware.json` guarda o resultado para a versão `007_051_002` (só metadados, sem as imagens) e `GET /api/v850`
  devolve um resumo em `firmware` (variantes, endereços, versões, nomes de canal e tabela do gateway); a aba **V850** mostra as variantes.
* **Não modelado:** canal 27 (toque), os 35 canais/filas do firmware, o gateway de sinais (`IpcSGW`), o VIN confiável, o amplificador,
  o ventilador, a memória de erros, o `IOC_BM_INFO`. Não inventei respostas: o formato das mensagens desses canais não foi decifrado.

## Reproduzir

```bash
python3 -m idemu.v850fw ~/Downloads/psdzdata                       # resumo em JSON (versão mais nova de cada pacote)
python3 -m idemu.v850fw ~/Downloads/psdzdata --extract /tmp/ioc    # grava os blocos (v850ApplicationFlash.<versão>.bin etc.)
python3 -m idemu.v850fw ~/Downloads/psdzdata --json idemu/data/v850_firmware.json
strings -a -n 6 /tmp/ioc/v850ApplicationFlash.*.bin | less         # as strings citadas acima
python3 -m unittest tests.test_v850fw
```

## Próximos passos (hipóteses, nada disso foi testado)

1. **Itens cinzas do menu "Meu Veículo"** (`docs/V850.md`): MOST, codificação e Kombi já foram descartados. O V850 real também serve
   `IpcSGW`/`IpcSGWCtrl`, `IpcPGWCtrl`, `IpctrustedVIN_Ctrl` e `IpcEnv`; o `OnOffHuOmapApp` (`V850Wrapper`) depende do V850 e não roda aqui.
2. **Tabela do gateway:** abrir o formato (cabeçalho com CRC, endianness e alinhamento, como pedem as mensagens de erro do
   `DiagRouter`) mostraria quais sinais CAN o gateway roteia para a head unit, e permitiria alimentar o HMI como o carro faz.
3. **Canal 27:** o firmware tem `IpcTouch_O5`; o protocolo do `touchComDevice` só sai desmontando os dois lados.
4. **Rodar o firmware de verdade:** as imagens estão inteiras. Faltaria um núcleo V850E2/RH850 (o QEMU não tem) e desmontar o código.
