# Original MGU22 guest helpers

These nine Linux ARM64 ELF binaries are compiled from this repository's
`src/mgu22` sources. They contain IDEmu's replacement services and graphics
bridge, not extracted BMW libraries. Firmware, `coding.tab`, the coding
dictionary and the sysroot are supplied or generated locally and are excluded.

Rebuild using native LLVM and a sysroot extracted from your own firmware:

```powershell
python tools/mgu/build_guest8.py mgu22/sysroot bin/windows/guest8
```

Copy only the nine files listed in `tools/mgu/build_guest8.py:GUEST_FILES` into
this directory after validation. The frozen Windows app uses them during image
preparation, so end users do not need a compiler. The native packager validates
their ELF architecture and copies only those files.

Current build: LLVM 23.1.5 targeting `aarch64-linux-gnu`, LLD's GNU ELF driver
with `aarch64linux` emulation, firmware ABI `007_034_003`. See
`docs/WINDOWS-ID8-PORT.md` for validation status. Project license applies.
