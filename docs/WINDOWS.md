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

## Install and update on Windows

Run `IDEmu-Setup.exe`. Setup installs for your Windows account and adds Start menu shortcuts for the WSL2 emulator, the native Windows firmware tool, and **Check for updates**. It does not install or configure WSL. Both tools look for `C:\BMW\PSdZData` on a fresh setup; you can select another directory in System Files. Existing settings take precedence. The installer and uninstaller leave firmware, environments, and user settings in their existing locations.

**Check for updates** looks at the latest stable [GitHub release](https://github.com/KClemente11/IDEmu/releases) from this fork. If it finds a newer version, it asks before downloading, verifies the installer's SHA-256 against GitHub's release metadata, then opens Setup. Close the emulator or firmware tool first so Setup can replace the app files.

To uninstall, use the **Uninstall** Start menu shortcut or **Settings > Apps > Installed apps**. The uninstaller stops any IDEmu processes still running from the installation folder, removes the app, and asks whether to delete `%LOCALAPPDATA%\IDEmu` (settings, built environments, logs and caches). That folder is shared by IDEmu Native and the WSL edition's firmware tool. Firmware in your PSdZData folder and environments inside WSL are never deleted. For scripted test runs, `unins000.exe /VERYSILENT /PURGEDATA` removes the data folder without asking; a silent uninstall without `/PURGEDATA` keeps it.

The native runtime ties QEMU and the renderer to the IDEmu process, so closing the console window also stops the VM.

To build the WSL installer locally, install Inno Setup on the build machine and build the WSL helpers as described above. Then run:

```
.\.build-tools\Scripts\python.exe .\build_installer.py --backend native --version 0.1.3 --output-dir .\dist\native-installer-0.1.3
```
Note: The installer compiler will reject to overwrite any existing installer, so make sure you change the output directory (.\dist\native-installer-0.1.1) everytime you want to run the installer. Or delete the old installer.

Pass `--iscc C:\path\to\ISCC.exe` if the compiler is outside its normal install location. The GitHub **Windows installer** workflow can build test artifacts manually. Pushing a stable `vX.Y.Z` tag to the fork publishes the two Windows installers and the corresponding upstream QEMU source archive. The tag supplies the IDEmu patches and build scripts. The updater uses stable release assets.

## Native Windows installer

The native edition runs iDrive 4 (CIC High) and iDrive 6 (NBT Evo) without WSL. It includes Windows builds of QEMU for both boards and the Evo OpenGL renderer. The app keeps generated images, settings, and logs under `%LOCALAPPDATA%\IDEmu`. Evo requires a Windows OpenGL driver that supports OpenGL 2.1 and framebuffer objects.

Open **System Files** and validate your PSdZData folder. The default is `C:\BMW\PSdZData`. For CIC, put `swfl_000003a6.bin.008_090_002` and `swfl_00000417.bin.008_090_002` in `C:\BMW\PSdZData\CIC\swe\swfl`, or select the two files in System Files. Create an **iDrive 4 (CIC)** environment, then choose **Build** and **Start**. CIC displays its 1280 × 480 interface through the web app and accepts rotor and button input.

Build the native runtime in an x64 MSYS2 UCRT64 shell. Use a Windows build directory without spaces. The installed app ships its Windows executables and DLLs.

```sh
pacman -S --needed git diffutils mingw-w64-ucrt-x86_64-{gcc,python,python-pip,python-setuptools,python-wheel,pkgconf,ninja,glib2,pixman,dtc,freeglut,glew,libpng}
bash tools/qemu/build-windows-native.sh /path/to/qemu-11.1.2.tar.xz
```

Then build Setup from Windows PowerShell using the existing PyInstaller and Inno Setup tools.

```powershell
.\.build-tools\Scripts\python.exe .\build_installer.py --backend native --version 0.1.3 --output-dir .\dist\native-installer
```

`IDEmu-Native-Setup.exe` installs alongside the WSL edition. The update shortcut looks for the native installer asset in the same repository. The native runtime supports cold boot for iDrive 4 and 6. The WSL edition also supports iDrive 5 and provides snapshots and guest SSH for Evo.
