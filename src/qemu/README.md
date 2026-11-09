# QEMU próprio do IDEmu (iDrive 7)

Dois arquivos do QEMU 11.1.2 que o IDEmu modifica/acrescenta; `tools/qemu/build.sh` os copia para a árvore do QEMU, compila e instala `bin/qemu-system-x86_64`.

* `idemu-shm.c` (novo): dispositivo PCI `idemu-shm` (1b36:1d3a). Um BAR de memória apoiado num objeto POSIX `shm_open()` que o `glhost7` também mapeia. O guest o mapeia por
  `/sys/bus/pci/devices/.../resource0` (sem driver) e o usa como anel de comandos GL. O `ivshmem` do QEMU só compila no Linux. O dispositivo registra o BAR como RAM nomeada
  (`vmstate_register_ram`) e o PCI no vmstate, para entrar no snapshot (`savevm`).
* `sdhci-pci.c` (alterado): o vmstate do SDHCI não inclui o espaço de configuração PCI; depois de um `loadvm` o controlador sumia do barramento e o guest recebia erro de E/S no cartão
  SD (`mmcblk0: error -123`). O acréscimo grava só o `PCIDevice`.

Sem este binário o iDrive 7 ainda sobe com o QEMU do Homebrew, mas pela serial (≈ 100x mais lenta) e sem boot rápido.
