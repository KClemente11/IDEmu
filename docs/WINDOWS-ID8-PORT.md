# iDrive 8 native Windows port

Status: native iDrive 8 boots and renders BMW's HMI on Windows x64. It is enabled
in the normal **New environment** list when its native executables are installed.
No preview launcher or opt-in environment variable is needed. Three cold boots
passed during the initial port, including one from the frozen Windows app.

The baseline is the fork at `e5d34e3`. Unlike iDrive 7's x86-64 guest, MGU22 runs
Linux ARM64. The existing Mac runtime uses HVF with `-cpu host`, 12 GiB of POSIX
shared RAM, a `DYLD_INSERT_LIBRARIES` shim, a FIFO console, Unix datagrams for
input, and an ANGLE renderer using Metal. Those host facilities need replacements.

## Install and create an environment

Run `IDEmu-Native-Setup.exe`, then open **IDEmu Native** from the Start menu.
The local 0.2.3 build is `dist/native-installer-0.2.3/IDEmu-Native-Setup.exe`.
The native installer includes the ARM64 QEMU, renderer and original guest helpers.
Native packaging fails if any of these are missing or invalid. This uses the normal IDEmu user data
directory; the installer contains no firmware. Validate `C:\BMW\PSdZData` in System
Files, then create/build/start an iDrive 8 environment. The `id8/swe/swfl` and
`id8/swe/swfk` subfolders are recognized.

The port was tested with the x64 ANGLE DLLs already installed by NVIDIA App.
For another ANGLE installation, set `IDEMU_ANGLE` before launching IDEmu Native.

Images built by the packaged 0.2.1 app can be truncated because the ext-to-cpio
helper did not explicitly flush its output before process exit. This causes a
kernel initramfs error and panic while the old UI continues waiting for frames.
After upgrading to 0.2.3, stop and **Rebuild** affected iDrive 8 environments.
The installer preserves generated images; installing the update alone does not
repair an existing image.

The fixed converter closes its output explicitly. The builder validates all six
archives before atomically publishing the image, and startup rejects corrupt
images before allocating guest RAM. Fatal kernel boot errors are also reported
immediately instead of waiting for the first-frame timeout. A full image built
by the frozen 0.2.2 app passed validation and matched the known-good source image
byte for byte (SHA-256 `2ab0dda23acedd69c098e1c7f729471a84f2924e37627debd5fdccf65872916f`).
Evidence: `scratch/mgu8-cpio-fix-3kkp55bq/verification.json`.

Version 0.2.3 also fixes shared-image reuse: deleting an environment does not
delete the shared MGU22 image, and older versions could skip rebuilding it merely
because its files existed. Readiness now requires six valid archives, with the
result cached only until the file changes. Create and build rebuilds an invalid
cache; the explicit Rebuild button and CLI build command always perform a real
build. Build completion is checked before reporting success, and the packaged
tools flush progress messages immediately. Environment deletion is not required
to repair the image.

The packaged 0.2.3 regression test started with a corrupt shared image and all
other cache files present, deleted/recreated the environment, and used the
wizard's normal build request. It observed real progress at 10/25/55/75/90%,
validated six complete archives matching the known-good hash, then booted the
rebuilt HMI (first swaps at 93.3 s, zero HMI exits) and stopped cleanly.
Evidence: `scratch/mgu8-rebuild-flow-result.json` and
`scratch/mgu8-rebuild-validation.png`. The targeted checks pass: 24 Windows MGU22,
12 coding and 2 System Files tests.

## Image preparation

`tools/mgu/build_image.py` can now prepare the kernel, initramfs, coding dictionary
and Linux ARM64 helpers on Windows. It reads ext filesystems directly into cpio;
Linux filenames, permissions and links do not need to exist on NTFS. Both the
original package names and names ending in `.tar` are accepted. All six required
packages are checked before extraction starts.

For development, install native LLVM with `clang` and `ld.lld` on PATH, or set
`IDEMU_CLANG` and `IDEMU_LLD` to their executable paths. Run from the repository:

```powershell
.\.build-tools\Scripts\python.exe tools/mgu/build_image.py C:\BMW\PSdZData\id8 --build-guest --output-dir .\mgu22
```

Alternatively, pass `--guest-dir <folder>` containing the nine Linux ARM64 binaries
listed in `tools/mgu/build_guest8.py`. Their ELF class, byte order and architecture
are checked before copying. The coding table is generated from the supplied
firmware, rather than copied from the precompiled helper folder.

`--output-dir` overrides `IDEMU_MGU8_OUT`; otherwise output goes to
`<IDEMU_STATE_DIR>/mgu22` or `<repository>/mgu22`. The existing Mac build remains
the default on macOS, including its host renderer and QEMU shim.

Native LLVM 23.1.5 compiled all nine runtime helpers against the user's firmware
libraries. The linker explicitly selects the GNU ELF driver and AArch64 emulation;
MinGW's default linker driver produces PE files. A complete `007_034_003` image
build succeeded from the six local archives. `base.cpio` is 4,028,167,984 bytes;
allow at least 20 GB of free disk space for the build's temporary raw images.

The package catalog now checks all six archives, including the BMW and G70BEV
SWFK data, and accepts `.tar` suffixes. Windows staging copies archives without
requiring permission to create symlinks.

The native renderer passed `tools/mgu/smoke_host8.py` using the ANGLE DLLs from
the locally installed NVIDIA app. The test creates GLES3 contexts with shared
program objects, exercises 64-bit generated replies, clears a pbuffer and checks
every RGB pixel. It also checks touch/controller UDP routing and skips a channel
with invalid physical page pointers. This is a synthetic renderer check, not
evidence that the BMW HMI has booted.

```powershell
.\.build-tools\Scripts\python.exe tools/mgu/smoke_host8.py "C:\Program Files\NVIDIA Corporation\NVIDIA App\CEF"
.\.build-tools\Scripts\python.exe tools/mgu/smoke_ram8.py
.\.build-tools\Scripts\python.exe tools/mgu/smoke_windows8.py --timeout 1800
```

The RAM check verifies both directions between Python and QEMU's physical RAM.
The cold-boot check retains logs and screenshots under `scratch/mgu8-boot-smoke`.
It sends controller input after the first frames; inspect the screenshots to
confirm a response. Both checks stop their child processes on exit.

## Windows runtime

`tools/qemu/build-windows-native.sh` now builds `aarch64-softmmu` and
`mguhost.exe`. `tools/qemu/install-mgu8-backend.py` installs the GPL QEMU backend
`memory-backend-idemu`, which opens the named mapping Python has initialized.
QEMU uses TCG with `cortex-a76`, four vCPUs, and a TCP serial console.

Each run uses a unique local mapping name. The parent retains the mapping until
both children have exited. Initrd bounds are checked before allocation, and the
DTB's initrd end is patched after the environment's coding overlay is appended.

The renderer uses Win32 mapping and DLL APIs, D3D11 ANGLE, and a loopback UDP
input socket. `chan.h` has fixed-width 64-bit fields with size/offset assertions;
generated reply values and pointer-sized GL arguments also retain their Linux
ARM64 widths on Windows x64. The Mac POSIX/HVF/Metal path remains separate.

Set `IDEMU_ANGLE` to an absolute folder containing **x64** `libEGL.dll` and
`libGLESv2.dll`, or use one of the installed-app locations searched by
`idemu.mgu.find_angle`. DLLs from third-party apps are not copied into the bundle.

The native packager requires the ARM64 QEMU, renderer and validated guest helpers
in `idemu/guest8` (or `bin/windows/guest8`). It
copies only the nine original helper binaries, not the sysroot, coding table,
or firmware. The runtime also accepts helpers under `idemu/guest8`.

```powershell
$env:IDEMU_ANGLE = 'C:\path\to\x64\ANGLE'
python -m idemu gui
```

The Windows guest uses 12 GiB of RAM. Its initial renderer scans that RAM to find
guest channel headers; residency filtering is still specific to the Mac path.
The TCG boot timeout is 30 minutes to allow slower hosts.

## Verified locally

The three cold boots reached their first swaps at 101.7 s, 108.3 s and 107.8 s
on the development PC. Full 2880×960 Home screens were visually inspected.
Every run reported zero HMI exits, and QEMU/renderer processes stopped with the
test driver. The frozen app run also verified rotary selection, push opening
Connect new device, Back returning Home, and touch changing navigation focus.
The Apps page itself was not retained after its transition.

The frozen app extracted all 1,264 coding parameters; its dictionary matched the
source build exactly. Its web UI and experimental catalog entry were exercised
using an isolated test profile. No installer was installed into the user's
existing application or profile during these checks.

The 0.2.1 installer integration removes the preview flag from both the catalog
and runtime. The environment API also recognizes native MGU22 independently of
Evo's HMI version. A validation compile of Setup, using the release build's exact
225-file application payload with isolated installation metadata and no shortcuts
or uninstall registration, installed successfully in a workspace test folder.
The installed normal app exposed iDrive 8 without an opt-in, created a new MGU22
environment with Start enabled, cold-booted it to a full 2880×960 Home screen
(first swaps at 98.7 s), and stopped it cleanly with zero HMI exits.

Installer checks passed: 16 Windows MGU22 tests, 12 coding tests and 2 System Files
tests. Evidence is retained under `scratch/mgu8-setup-validation-1ad86333` and
`scratch/mgu8-installed-app-validation.log`. The normal release installer keeps
its existing production identity, Start menu shortcut and uninstaller.

Local evidence (ignored, not shipped): `scratch/mgu8-boot-smoke*`,
`scratch/mgu8-frozen-boot-smoke`, `scratch/mgu8-frozen-ui-smoke`,
`scratch/mgu8-host-smoke` and `scratch/mgu8-ram-smoke`.

The initial port regression run covered 272 tests: 233 passed, 3 skipped and 36 failed or
errored. Every failing test name also fails on the unchanged `e5d34e3` baseline
under this Windows environment; MGU22 archive staging now passes. Focused port
checks pass. Retained logs: `scratch/mgu8-regression-tests-final.log` and
`scratch/mgu8-baseline-tests.log`.

## Remaining validation

### Deferred: Windows power throttling during image builds

Shelved at the user's request on 2026-11-13. ID8 and ID7 already launch QEMU
and their renderers through `Runtime._spawn`, which calls `winproc.contain`
and `winproc.unthrottle`. Controlled child-process probes through both launch
paths read back `ControlMask = 5`, `StateMask = 0`.

Their image-building subprocesses bypass that protection. A future Windows-only
change should cover the build tools, verify their live power-policy state, and
measure build times before claiming a speed improvement. A host timer probe
measured median `Sleep(1)` at 15.5 ms with timer-resolution requests explicitly
ignored, versus 2.0 ms with throttling disabled; image-build impact is unverified.
This is separate from the fixed corrupt-initramfs and false-success cache bugs.
Shipping the host-only change requires a native installer rebuild and reinstall,
but does not itself require an environment image rebuild. Leave macOS unchanged.

Exercise coding changes through the app, controlled clock/climate updates,
additional menus and touch gestures, long runs, and upgrade/uninstall flows.
Maps, CAN, audio/media, cluster and USB retain the existing iDrive 8 backend's limitations. The initial
RAM scan and TCG performance also need broader hardware coverage.

Firmware, generated images and linked libraries stay in ignored local folders.
