# UDS diagnostic emulator (iDrive 5/6)

Apps on the head unit that read live data from the car (BoostDeck, ShiftDeck and MHD maps in ID6_apps, for example) open
HSFZ (TCP 6801) to the central gateway at a link-local address (`169.254.x.x`). They send UDS requests to an ECU address
(DME `12`, EGS `18`, ...). The emulator plays that gateway and those ECUs.

```
collector on the guest --HSFZ 169.254.x.x:6801--> src/shim/hsfz.c (thread in HmiMain3D)
    --"Q seq src tgt hex" over UART1 (/dev/ser5)--> runtime.DataChannel --> idemu/uds.py UdsEmulator.handle()
    <--"U seq hex"-- guest agent.sh writes /var/idemu/uds/<seq> <-- hsfz.c sends the HSFZ reply
```

- **On/off:** CAN → UDS → Turn on/off, stored as `uds_gateway` in env.json. It is on by default on Windows and Linux
  and opt-in on macOS. Changing it needs an environment rebuild.
- **Gateway addresses:** `169.254.199.99`, plus every `gateway-ip.txt` found in the overlay. The build adds them to `lo0`
  in rc.sh, so existing plugin packages work unchanged.
- **Configuration:** `<env>/uds.json`. Edit it in the UDS sub-tab (table or JSON). Changes apply live, with no rebuild.
  The format is documented at the top of `idemu/uds.py`.
- **Presets:**
  - `b58`: the BoostDeck/ShiftDeck signals from ID6_apps `docs/SIGNALS.md`.
  - `s63tu`: the `STATUS_MESSWERTE` record from `s63tu_r0.prg`. Its DID `4000` and its field offsets are inferred from
    the decompile and are unverified.
- **Built-in services:**
  - Requests: 22 (one or more DIDs), 01 (OBD PIDs and supported-PID bitmaps), 09 02 (VIN), 10, 11, 14, 19 02, 27,
    2F (echo, including the 3-byte MHD map switch `2F 01 xx`), 31, 3E.
  - Unknown DID: `7F 22 31`. Unknown service: `7F xx 11`.
  - Unknown ECU: no reply (the tool times out), or `7F xx 11` with `"unknown_ecu": "nrc"`.
- **Raw rules:** each ECU can also have raw rules (`{"request": "22 40 ..", "response": "62 40 00 ..."}`, `..` matches
  any byte). They are checked before the built-in services.
- **Where traffic shows:**
  - The UDS sub-tab (live values, request tester and transaction list).
  - The CAN Monitor, as BMW ISO-TP frames: tester `6F1`, ECU replies on `600 + address`.
  - Logs → UDS diagnostics (`logs/uds.log`).
- **Reply size:** a reply is limited to about 1000 bytes by the guest UART line buffer.

The `pf` firewall of the original firmware stays enabled. If a tool cannot connect, check `/var/hsfz.log` (the `ifconfig`
output) and the `hsfz:` lines in renderer.log.
