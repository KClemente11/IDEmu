# ID8 BMW M asset investigation

Local inspection on 2026-11-13. No firmware, environment, coding, or runtime
settings were changed. The M interface has not been boot-tested.

## Supplied filesystem

Source: `C:\Users\kclemente\Documents\MEGA downloads\bmw mgu22 filesystem`.

The folder contains these separate PSdZData SWFK asset images:

| Package | Contents | Version |
| --- | --- | --- |
| `0000a6b0` | `hmi-data.bmw-shared` | `007_023_004` |
| `0000a6b1` | `hmi-data.bmw` | `007_023_004` |
| `0000a6b2` | `hmi-data.bmwm` | `007_023_004` |
| `0000a691` | `hmi-vehicles.g80lci` | `007_023_004` |
| `0000aed4` | `hmi-vehicles.g26bev` | `007_023_004` |

Read-only ext4 traversal of `swfk-0000a6b2.hmi-data.bmwm.ext4` found
3,625 files, totaling 183,626,983 bytes, with `hmi_version` equal to
`ID8_2507-2446ZC`. Actual resources include:

- `id8/widgetasset/TricoloreBackground/`
- `id8/widgetasset/CP_MMode_BG/`
- `id8/widgetasset/deliveries/01_Home/MainMenu/CID_LiveCar_MSetup_Tricolore/`
- `id8/widget/WelcomeAnimation.pbw`
- M lap-timer icons and M Mode HUD/cluster illustrations.

The supplied `ivi_fs.zip` contains
`usr/share/hmi/data/ro/config.bmwm_id8_display14_9_2880x960.pbr`, whose resource
paths reference those BMW M assets. Its filesystem metadata restores
`usr/share/hmi/data/ro/bmwm` as a symlink to `/var/begu/hmi-data/bmwm`.
The G80LCI image separately contains vehicle meshes, textures, and scene data.

## Current emulator image

The current `mgu22/base.cpio` includes the BMW M configuration and the symlink
to `/var/begu/hmi-data/bmwm`, but no files at that destination. The builder
currently imports BMW data (`0000a6b1`), shared data (`0000a6b0`), and G70BEV
vehicle data (`0000a6a6`). The inspected `C:\BMW\PSdZData\id8\swe\swfk`
folder contains those three packages, but no `0000a6b2` or `0000a691` package.

The generated coding dictionary already offers `HMI_BRAND = bmw_m` (value 4)
and M-series choices, including `SERIES = G080LCI` (value 73). A coding change
alone would not supply the missing BMW M resources or vehicle image.

The current packages are `007_034_003`, with HMI resource version
`ID8_2607-2626A`, whereas the supplied M assets are `007_023_004` /
`ID8_2507-2446ZC`. Compatibility across those versions is unverified.

## Implication

BMW M is supported by the shared HMI configuration, with a separate BMW M
SWFK resource package and vehicle-specific SWFK images. This is not evidence
that an entirely different PSdZData distribution is required. For the current
emulator, obtain matching `007_034_003` BMW M and desired vehicle packages, or
test a separate, consistently versioned older firmware environment. Supporting
that profile also requires builder/catalog changes to import its resources and
select appropriate coding; the present builder is fixed to BMW G70BEV.

Local read-only inventories are retained in ignored scratch files
`scratch/mega-a6b2-listing.json` and `scratch/mega-a691-listing.json`.
