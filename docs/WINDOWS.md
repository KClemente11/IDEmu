# IDEmu on Windows

The Windows launcher runs the iDrive 5/6 backend in Ubuntu under WSL2. It opens the web interface in the Windows browser. QEMU, Unix sockets and the OpenGL renderer run in WSL. The launcher also exposes iDrive 4 (CIC) when the custom Linux `bin/qemu-system-sh4` binary is installed. iDrive 7 and 8 are unavailable on WSL.

## Build the backend

Use an x64 Windows 11 machine with an Ubuntu WSL2 distro and WSLg. In Ubuntu, change into the IDEmu source folder. A Windows path such as `C:\Projects\IDEmu` appears as `/mnt/c/Projects/IDEmu`.

```sh
sudo apt update
sudo apt install build-essential ca-certificates curl git ninja-build pkg-config python3-venv xz-utils \
  libglib2.0-dev libpixman-1-dev libfdt-dev libglut-dev libgl-dev libx11-dev libgdk-pixbuf-2.0-dev

curl -fLO https://download.qemu.org/qemu-11.1.2.tar.xz
sh tools/qemu/build-evo.sh "$PWD/qemu-11.1.2.tar.xz"
sh src/glhost/build.sh
```

The scripts place both helpers in `bin/`. Rebuild QEMU if you already have an IDEmu ARM binary from before this port. The shim disk now uses a separate physical address from the graphics command buffer.

For iDrive 4, configure QEMU 11.1.2 in a separate build folder with `--target-list=sh4-softmmu --disable-slirp --enable-fdt=system` and the same headless options as above. Run `src/cic/build.sh` with `CIC_QEMU` set to the QEMU source folder and `CIC_BUILD` set to the configured build folder. The Windows packager includes `bin/qemu-system-sh4` if present. System Files can discover the CIC firmware under `CIC/swe/swfl` inside your selected PSdZData folder.

## Start from Windows

Run from the IDEmu folder in PowerShell.

```powershell
.\Start-Windows.ps1
```

If the browser does not open, visit [IDEmu on localhost](http://127.0.0.1:8765/). Use `-Distro` to select a different Ubuntu distribution, `-Port` to change the HTTP port, or `-NoBrowser` to leave browser launch to you. Press Ctrl+C to stop the server and its VM. By default the launcher stores environments under `~/.local/share/idemu/environments` on the Linux filesystem.

In the browser, create an iDrive 6 or 5 environment. In the firmware picker, enter a WSL path such as `/mnt/c/Firmware/psdzdata` or the path to your SWFL folder. For the first BMW Evo boot, use the upstream profile with `swfl_0000271a` (OS), `swfl_00002719` (BMW resources), and `swfl_00002720` (HMI), all at `007_051_002`. Upstream records one validated HMI hash in [known_hmi.json](../idemu/data/known_hmi.json). Disable fast boot for initial validation so the run exercises a cold start.

The workspace's `006_017_006` packages have a different QNX startup script. Extraction succeeded, but the builder rejected the boot IFS because the expected serial-login command was absent. The HMI shims also use revision-specific addresses.

The Windows launcher was verified with a cold boot of the `007_051_002` F30 BMW ID6 Light profile. The native Home screen rendered at 1440×540, and rotary and select commands from Windows opened My Vehicle. The environment build creates a shader index from the firmware so the renderer can recognize cursor materials. If an older environment displays a white rectangle over the selected label, rebuild its images and start it again.

If a VM fails to start, check `qemu.log`, `renderer.log`, and `console.log` under the environment's `logs/` folder.
If QEMU was linked against `libslirp.so.0` in a temporary build directory, that dependency can disappear after a WSL shutdown. Rebuild with the current Evo build script, which disables the unused networking backend, or keep the matching library in `bin/lib/` with that older binary. The launcher reports the QEMU log when the process exits before its monitor opens.

## Build a Windows executable

From the IDEmu folder in x64 Windows PowerShell, build the WSL backend above first. Then run:

```powershell
python -m venv .build-tools
.\.build-tools\Scripts\python.exe -m pip install pyinstaller==6.22.3
.\.build-tools\Scripts\python.exe .\build_windows.py
.\dist\IDEmu\IDEmu.exe
```

Keep the `dist\IDEmu` folder together. The launcher includes its Windows Python runtime, the IDEmu application and the compiled Linux helpers. It runs the head unit in the installed Ubuntu WSL2 distribution with WSLg and its graphics libraries. Pass `--distro` to choose another distribution, `--port` to change the localhost port, or `--no-browser` to open the web UI manually. The launcher keeps settings and environments in the user's WSL data directory. Supply your own SWFL files.

To build the native Windows firmware-preparation application:

```powershell
.\.build-tools\Scripts\python.exe .\build_windows.py --backend native-prep
.\dist\IDEmu-Prep\IDEmu-Prep.exe
```

`IDEmu-Prep.exe` opens System Files and builds iDrive 5/6 images on Windows. It stores data under `%LOCALAPPDATA%\IDEmu`. Booting the VM from this application requires the Windows QEMU and renderer port. To keep multiple builds, pass `--output-dir` with a new directory.

## Path to a native Windows runtime

Use the native prep app as the Windows entry point. System Files should accept a Windows folder such as `C:\BMW\PSdZData`, validate the exact SWFL versions for the selected head unit, and keep references to the source files. Put generated images, settings and logs under `%LOCALAPPDATA%\IDEmu` by default.

1. Build the patched OMAP5 QEMU machine as a Windows x64 executable. Use loopback endpoints for its monitor and guest serial connections; adapt the custom graphics bridge and controller transport for Windows.
2. Build a Windows renderer, using a native OpenGL context and Windows frame sharing. Check the reference iDrive 6 profile from cold boot through the first HMI frame, controller input, and clean shutdown before adding iDrive 5.
3. Ship the native helpers with the app in one installer. On a clean Windows machine with no WSL distro, verify that a user can select firmware in System Files, build an environment, boot it, and close it without installing Python or QEMU. Keep additional generations gated until their native backends pass the same checks.
