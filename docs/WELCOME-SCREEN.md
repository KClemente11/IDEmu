# Evo welcome screen

In Execution → CAN → Power / welcome, use **Show welcome** to request the native firmware popup. Enable **Show welcome on wake**, then press **Sleep** and **Wake** to simulate its power-state sequence. Duration is configurable from 1–60 seconds. **Follow ignition** releases the manual override. These actions affect the virtual vehicle only.

Tested with BMW firmware **007_051_002**. In Coding, set **PRODUKTLINIE=35up**, and flash the virtual head unit so HMI starts with that configuration. The successful test also used **STARTUP_TYPE=pwf_welcome**. Both **F30 + id6_light** and **G30 + id6_light/id6** opened the native `CHmiWelcomeActivity`, state 1171. Changing BAUREIHE to G30 alone, retaining `lu_b`, did not initialize the activity in these tests. Product line can affect other native menus too; the trigger does not change it automatically.

The control sends SystemFunctionPowerMode FBlock D1, instance 02, detailed status function 434 = `0x5A` (Welcomescreen), with coarse function 430 = 0. At expiry it restores the prior power policy; awake reports detailed `0x63`. The emulator's previous fixed user-on getter overrides suppressed welcome, so the updated shim now lets native getters expose the incoming status. Existing Evo shim images receive updated emulator libraries on the next launch and use a cold boot when the libraries changed.

The timed interval is emulator policy, not a reconstruction of the vehicle's power controller. Sleep here is a simulated status, not a QEMU suspend. A fresh emulator start does not automatically trigger welcome. Wake opt-in and duration persist; transient manual mode does not.

The welcome text and OK button render, but the 3D vehicle preview currently appears as a malformed yellow surface in the Windows renderer. Activation is verified despite that rendering defect. The popup loads model resources from `bmw/widgetasset/vehicles/F30/vehicle/` in the F30 test, with shared shaders from other model directories; it is not dependent on the j29 home.png asset.

Both 006_017_006 and 007_051_002 contain the native application and the `0x5A`/system-property checks. Runtime success has only been demonstrated on 007_051_002. This is not a validated on-car coding recipe for 006_017_006: initialization, actual vehicle sleep/wake status, property 0x01000048, and display handoff must still be observed on that unit.

Build the guest libraries, when needed, with `python tools/build_evo_shim.py --zig <zig.exe> --libc <extracted-QNX-libc.so.3>`. The script builds ARM libraries; the supplied libc remains local.
