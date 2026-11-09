# Pen drive virtual: por que não existe (ainda) e o que faltaria (2026-11-07)

Pedido: escolher uma pasta do Mac e a head unit enxergar um pen drive espetado. **Não está funcionando**: nenhuma das duas gerações emuladas tem o que um pen drive precisa. No iDrive 8 a cadeia do firmware foi montada até o `devicemanager` (seção abaixo); o HMI ainda não mostra o dispositivo. Abaixo, o que foi conferido.

## iDrive 5 e 6 (QEMU `omap5-uevm`, QNX 6.5)

* A placa do QEMU não tem controlador USB host (`-device help` do `qemu-system-arm` só lista `usb-host` e `usb-hub`, e o `omap5-uevm.c` não modela o EHCI do OMAP5).
* O guest só roda a lista mínima de serviços (`pidin`: `io-ipc`, `most`, `servicebroker`, `someip_sddaemon`, `watchdog5-omap`, `HmiMain3D`...). Não há `io-usb`, `devb-umass` nem o motor de mídia.
* Mesmo com um disco montado em `/fs/usb0`, o HMI não o mostraria: as fontes de mídia (`CDevExternalUSBBase`, `CDevMediaPlayerAbstract`) vêm de serviços DSI do motor de mídia da head unit, que não faz parte dos SWFL que o IDEmu usa. O log do HMI mostra a fonte USB criada, mas sem câmera nem player (`ASSERTION FAILED: nullptr != m_pDevCamera at CDevExternalUSBBase.cpp:155`).

## iDrive 8 (QEMU `virt` aarch64)

* O kernel do firmware (5.15.123, Qualcomm) não tem PCI genérico, virtio nem `xhci-pci`; o USB dele é `dwc3` de SoC, que a máquina `virt` não tem. Assim o `qemu-xhci` + `usb-storage` (hot-plug por QMP com a pasta como disco `vvfat`) não teria driver no guest.
* O firmware tem a pilha real: `udevd`, `udisks2`, `usbDaemon` (fala com o UDisks2 por D-Bus e publica os dispositivos por CommonAPI/vsomeip), `usbmond` e o `mediaapp`. O init do IDEmu sobe `mediaapp` e `devicemanager`; `usbDaemon` e NSM só com a pilha experimental ligada.

## iDrive 8: o que foi feito e onde parou (2026-11-08)

Uma pilha experimental de USB para o iDrive 8, **desligada por padrão**. Para ligar: iniciar o servidor com `IDEMU_MGU_USB=1` (e `IDEMU_MGU_DLT=1` para ver o log DLT dos daemons do firmware em `/tmp/dlt.txt` do guest). Código: `src/mgu22/idemuusb.c`, `src/mgu22/usbfake/`, `src/mgu22/usb_proto.h`, bloco "pen drive virtual" de `tools/mgu/guest_boot.sh`.

Cadeia real do firmware, e o que cada etapa precisou:

| Etapa | Estado |
|---|---|
| `NodeStateManagerFRONT` (NSM) real | Roda no guest depois de criar `/var/data/node0/node-state`, `/run/lifecycle`, `/var/run/nsm`. O `usbDaemon` só segue com o NSM no ar |
| `idemuusb` (udisks falso) | Serviço `org.freedesktop.UDisks2` no barramento de **sessão** (`/run/dbus/session`), que é o que `usbDaemon` e `devicemanager` usam aqui. Responde `GetManagedObjects`, `Properties.Get/GetAll`, `Filesystem.Mount/Unmount`, emite `InterfacesAdded/Removed` e `PropertiesChanged` |
| `usbDaemon` real | Enxerga o pen drive, chama `Mount` e publica o caminho (`/media/<rótulo>`) pelo serviço `RemovableStorageManager` |
| `devicemanager` real | Aceita o dispositivo (papéis `FILE_PLAYER` e `TRACE_STORE`, `Connected`) |
| `libusb`/`libudev` falsas (`usbfake/`, só para o `devicemanager`) | Sem elas o `devicemanager` esconde o dispositivo (`isMergedRecord` falso): ele só mostra um USB que o udisks **e** o libusb viram. As falsas disparam o hotplug e descrevem um dispositivo de armazenamento em massa na porta `1-1`; o `SiblingId` do drive aponta para o mesmo caminho sysfs, e o `devicemanager` funde os dois registros ("Fuse") |
| `mediaonoff`, `mediaindexer`, `mediaengine` | **Não funcionam.** O `mediaapp` cria as fontes `ExternalMassStorage_Front_A/B` em modo `DUMMY` e espera o `mediaonoff` ativá-las. O `mediaonoff` só liga o resto quando as condições do sistema estão cumpridas ("HDD partitions are not ready", "Some lifecycle clients are not connected", NSM pronto) e sobe os processos pelo systemd por D-Bus, que o guest não tem. Também depende de Keystore, Grim e HDCP |

Resultado: o HMI ainda **não** mostra o pen drive no menu Mídia. Teste manual (sem o host): no console do guest, criar `/media/ROTULO/...` e escrever `ROTULO` em `/tmp/idemuusb.attach` (`/tmp/idemuusb.eject` remove).

Falta, em ordem: (1) um systemd falso (`org.freedesktop.systemd1`: `StartUnit`, `JobRemoved`) e as condições de sistema do `mediaonoff` (partman, clientes de ciclo de vida); (2) subir `mediaindexer` e `mediaengine` (este usa PulseAudio e o motor Cinemo); (3) o lado do Mac: `mguhost` lendo a pasta e mandando os arquivos pelo canal de papel 3 (protocolo já definido em `usb_proto.h`, o guest já os grava em `/media/<rótulo>`), seletor de pasta (`/api/pick`) e `POST /api/usb/attach|eject`. Os itens (1) e (2) são os incertos.

Dois cuidados: com o NSM real a tela do HMI apaga por inatividade ("sem operação") e um toque a acorda; e o arquivo `/tmp/usbfake.log` do guest registra cada chamada das bibliotecas falsas.

## iDrive 5/6

Sem equivalente sem emular o motor de mídia da head unit.
