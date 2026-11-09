# Ferramentas de análise do MGU22 (iDrive 8) e dos pacotes HAR (iDrive 7)

**iDrive 7:** `har.py` (extrator HAR), `extract_rse.sh`, `mkext2.py` (imagem ext2 sem e2fsprogs), `tscfix.py` (contorno do pânico do relógio do kernel), `boot_mgu.sh` e `idemu-init.sh` (boot de teste). Ver `docs/OUTRAS_GERACOES.md`.


Não fazem parte do emulador web. Montam e rodam o iDrive 8 como descrito em `docs/OUTRAS_GERACOES.md`, partindo da PSdZData.

* `build_image.py`: monta `mgu22/` (kernel, initramfs, bibliotecas do guest).
* `run.py [--seconds N] [--debug]`: roda fora da interface web; a tela vai para `mgu22/screen.png`, o console para `mgu22/cli/logs/console.log`. `--debug` liga o log do HMI em `/tmp/hmi.log` no guest.
* `gsh.py 'comando'`: roda no console do guest. `inp.py 'd x y' 'u' 'r 1' 'k 7 1 0 1'`: toque, rotor e teclas. `inp.py 'x px py'`: sonda de pixel do `mguhost`.
* `guest_boot.sh`: init do guest.
* `gencoding.py`: gera `coding.tab`.
* `virt_mgu22.dtb`: árvore de dispositivos (fonte em `.dts`).

* `simg2raw.py entrada.simg.bin.gz saida.raw`: gzip + Android sparse para imagem crua.
* `ext4ls.py img ls|cat|find CAMINHO`: leitura de ext4 sem montar.
* `ext2cpio.py img saida.cpio [ORIGEM] [PREFIXO]`: árvore ext4 para cpio newc (initramfs).
* `mkcpio.py saida.cpio nome:modo:arquivo nome:dir ...`: cpio pequeno, para o script de teste.

O kernel do MGU22 não tem virtio nem disco que o QEMU `virt` ofereça, então o sistema vai todo no initramfs (mais de 2 GB precisa ir comprimido com gzip).
A árvore de dispositivos do `virt` precisa de dois nós, senão o kernel entra em pânico em `place_marker`: `qcom,msm-imem-boot_stats` e `qcom,mpm2-sleep-counter`,
ambos em memória reservada.
