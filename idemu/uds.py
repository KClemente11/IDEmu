"""UDS diagnostic emulator for the iDrive 5/6 head unit (the virtual car's ECUs as seen through the ZGW).

On the car, diagnostic tools on the head unit open HSFZ (TCP 6801) to the central gateway and send UDS requests
addressed to an ECU (DME 0x12, EGS 0x18, ...). In the emulator a small daemon in the guest (/fs/shim/hsfzd) plays the
gateway: it listens on 6801 on the gateway's link-local address and forwards each request over UART1 to the host,
where UdsEmulator.handle() builds the reply from a per-environment configuration (<env>/uds.json).

Configuration (JSON):
  {
    "gateway_ips": ["169.254.199.99"],             # extra addresses the guest gateway answers on (gateway-ip.txt
                                                    # files found in the overlay are added automatically at build time)
    "unknown_ecu": "silent" | "nrc",                # no ECU at that address: time out (like the car) or answer 7F xx 11
    "ecus": {
      "12": {
        "name": "DME",
        "dids": { "4205": <value>, ... },           # ReadDataByIdentifier 22 xx xx -> 62 xx xx <data>
        "obd":  { "0C": <value>, ... },             # OBD mode 01 PIDs -> 41 pid <data>
        "raw":  [ {"request": "2F 01 ..", "response": "6F 01 00"} ],   # exact requests; '..' matches any byte
        "dtcs": [ {"code": "123456", "status": "2F"} ]                  # 19 02 -> 59 02 ...; 14 clears them
      }
    }
  }

A <value> is one of
  {"hex": "FFFF"}                                   fixed bytes
  {"bytes": 2, "scale": 0.0078125, "offset": 0, "signed": false, "value": 101.3}
                                                    physical value -> raw = (value - offset) / scale, big-endian
  ... plus "wave": {"min": 100, "max": 240, "period": 8} to sweep between min and max (seconds per cycle)
  {"length": 40, "fill": 255, "fields": [{"name": "...", "pos": 4, "bytes": 2, ...}, ...]}
                                                    a composite record, with optional fill byte
Optional keys: "name", "unit", "mask" (raw & mask), "little" (little-endian).
"""
import collections
import copy
import json
import math
import os
import threading
import time

DEFAULT_IP = '169.254.199.99'
TESTER = 0xF4           # HSFZ source address of a diagnostic tool on the head unit
CAN_TESTER_ID = 0x6F1   # BMW diagnostic CAN ids: tester 0x6F1, ECU replies on 0x600 + address
MAX_REPLY = 1000        # bytes; the guest UART line buffer limits a reply to about this much

# ---------------------------------------------------------------------------------------------------------- presets
def _v(name, unit, nbytes, scale, value=None, offset=0.0, signed=False, wave=None, **kw):
    d = {'name': name, 'unit': unit, 'bytes': nbytes, 'scale': scale, 'offset': offset}
    if signed: d['signed'] = True
    if value is not None: d['value'] = value
    if wave: d['wave'] = {'min': wave[0], 'max': wave[1], 'period': wave[2]}
    d.update(kw)
    return d


PRESETS = collections.OrderedDict()
PRESETS['b58'] = {
    'label': 'B58 / 340i (BoostDeck, ShiftDeck, MHD maps)',
    'note': 'Signals from ID6_apps docs/SIGNALS.md (the collector.c request table).',
    'ecus': {
        '12': {'name': 'DME', 'dids': {
            '4201': _v('Ambient pressure', 'kPa', 2, 1 / 256.0, 101.3),
            '4205': _v('Boost pressure (absolute)', 'kPa', 2, 1 / 128.0, wave=(100, 240, 8)),
            '5889': _v('Lambda', '', 2, 16 / 65535.0, wave=(0.80, 1.00, 5)),
            '4A49': _v('Ignition timing', 'deg', 2, 0.1, signed=True, wave=(4, 22, 7)),
            '580F': _v('Intake air temperature', 'C', 1, 0.75, 32, offset=-48),
            '56D7': _v('Rail pressure', 'bar', 2, 1 / 50.0, wave=(60, 200, 6)),
            '586F': _v('Oil pressure', 'bar', 2, 1 / 1000.0, wave=(2.0, 4.5, 9)),
            '4300': _v('Coolant temperature', 'C', 2, 0.1, 92, offset=-273.15),
        }, 'obd': {
            '0C': _v('Engine speed', 'rpm', 2, 0.25, wave=(900, 6500, 6)),
            '0D': _v('Vehicle speed', 'km/h', 1, 1, wave=(0, 120, 20)),
            '05': _v('Coolant temperature', 'C', 1, 1, 92, offset=-40),
        }},
        '18': {'name': 'EGS', 'dids': {
            'DA12': _v('Transmission oil temperature', 'C', 2, 1, 75, offset=-48),
        }},
    },
}
PRESETS['s63tu'] = {
    'label': 'S63TU (s63tu_r0.prg STATUS_MESSWERTE)',
    'note': 'S63TU Master STATUS_MESSWERTE, confirmed on live DME 0x12: UDS request 22 40 00 returns '
            '62 40 00 + 40 data bytes. Offsets are zero-based from the first byte after 62 40 00; '
            'the first four data bytes and data bytes 6..7 are FF in recorded captures.',
    'ecus': {
        '12': {'name': 'DME', 'dids': {
            '4000': {'name': 'STATUS_MESSWERTE', 'length': 40, 'fill': 0xFF, 'fields': [
                _v('STAT_LR1_MW (lambda regulator 1)', '', 2, 0.000244140625, 1.0, pos=4),
                _v('STAT_VFZG_MW (vehicle speed)', 'km/h', 2, 0.0078125, wave=(0, 120, 20), pos=8),
                _v('STAT_NMOT_W_MW (engine speed)', '1/min', 2, 0.25, wave=(800, 6500, 6), pos=10),
                _v('STAT_NSOL_MW (target idle)', '1/min', 2, 0.25, 700, pos=12),
                _v('STAT_CAM_IN (intake cam)', 'degCA', 2, 0.0078125, 20, signed=True, pos=14),
                _v('STAT_CAM_EX (exhaust cam)', 'degCA', 2, 0.0078125, -15, signed=True, pos=16),
                _v('STAT_TIA (intake air)', 'C', 1, 0.75, 30, offset=-48, pos=18),
                _v('STAT_TMOT (coolant)', 'C', 1, 0.75, 90, offset=-48, pos=19),
                _v('STAT_IGA_IGC (ignition angle)', 'deg', 2, 0.1, wave=(2, 25, 7), signed=True, pos=20),
                _v('STAT_TPS_AV_1 (throttle)', '% DK', 2, 0.0244140625, wave=(2, 80, 6), signed=True, pos=22),
                _v('STAT_MAF_KGH_MES_BAS (air mass)', 'kg/h', 2, 0.1, wave=(40, 900, 6), signed=True, pos=24),
                _v('STAT_TQI_AV (torque)', 'Nm', 2, 0.5, wave=(40, 650, 6), signed=True, pos=26),
                _v('STAT_VB (battery)', 'V', 1, 0.0942, 14.1, pos=28),
                _v('STAT_V_PVS_1 (pedal sensor)', 'V', 2, 0.0048828125, 0.75, pos=29, mask=1023),
                _v('STAT_TMOTLINF', 'C', 1, 0.75, 90, offset=-48, pos=31),
                _v('STAT_NL_1', 'V', 2, 0.0048828125, 1.0, pos=32),
                _v('STAT_NL_4', 'V', 2, 0.0048828125, 1.0, pos=34),
                _v('STAT_NL_3', 'V', 2, 0.0048828125, 1.0, pos=36),
                _v('STAT_NL_2', 'V', 2, 0.0048828125, 1.0, pos=38),
            ]},
            # Standalone S63TU Master DID responses tested on the M6. These are
            # deliberately independent of the grouped 4000 measurement block.
            # The real DME returned FFFF for 4A49 in some captures; this preset
            # emits a valid simulated signed value, not the unavailable marker.
            '4201': _v('S63TU ambient pressure', 'kPa', 2, 1 / 256.0, 99.2),
            '4205': _v('S63TU charge pressure (absolute)', 'kPa', 2, 1 / 128.0,
                       wave=(99.2, 240.0, 8)),
            '5889': _v('S63TU lambda (measured)', '', 2, 16 / 65535.0,
                       wave=(0.85, 1.02, 6)),
            '4A49': _v('S63TU ignition timing (standalone)', 'deg', 2, 0.1,
                       signed=True, wave=(2.0, 25.0, 7)),
            '580F': _v('S63TU intake air temperature', 'C', 1, 0.75, 30, offset=-48),
            '4300': _v('S63TU coolant temperature', 'C', 1, 0.75, 90, offset=-48),
        }},
    },
}

# DKG_10 PRG service-22 payload layouts (zero-based DID data offsets).
# Source: DKG_10 RES_0xDE30, RES_0xDE50 and RES_0xDE51 field definitions.
# Layout columns: signal | offset | width | signedness | PRG multiplier |
#                 PRG divisor | PRG addition | units.
# These are complete PRG-defined payloads, not guessed standalone DIDs.
_DKG_10_LAYOUTS = {
    'DE30': '''
STAT_MOTORDREHZAHL_WERT|0|2|u|1|4|0|1/min
STAT_EINGANGSDREHZAHL1_WERT|2|2|u|1|4|0|1/min
STAT_EINGANGSDREHZAHL2_WERT|4|2|u|1|4|0|1/min
STAT_AUSGANGSDREHZAHL_WERT|6|2|s|1|2|0|1/min
STAT_GESCHWINDIGKEIT_WERT|8|2|s|1|40|0|km/h
STAT_RADGESCHWINDIGKEIT_VL_WERT|10|2|s|1|16|0|km/h
STAT_RADGESCHWINDIGKEIT_VR_WERT|12|2|s|1|16|0|km/h
STAT_RADGESCHWINDIGKEIT_HL_WERT|14|2|s|1|16|0|km/h
STAT_RADGESCHWINDIGKEIT_HR_WERT|16|2|s|1|16|0|km/h
STAT_GESCHWINDIGKEIT_HINTERACHSE_WERT|18|2|s|1|16|0|km/h
STAT_MOTORTEMPERATUR_WERT|20|2|s|1|1|0|°C
STAT_MOTOROELTEMPERATUR_WERT|22|2|s|1|1|0|°C
STAT_KUPPLUNGSOELTEMPERATUR_WERT|24|2|s|1|1|0|°C
STAT_SG_TEMPERATUR_WERT|26|2|s|1|1|0|°C
STAT_UMGEBUNGSTEMPERATUR_WERT|28|2|s|1|1|0|°C
STAT_UBAT_WERT|30|2|u|1|2048|0|V
STAT_SPANNUNGSVERSORGUNG_7V4_WERT|32|2|u|1|2048|0|V
STAT_SENSORSPANNUNGSVERSORGUNG_VCC_WERT|34|2|u|1|2048|0|V
STAT_SENSORSPANNUNGSVERSORGUNG_SV1_WERT|36|2|u|1|2048|0|V
STAT_SENSORSPANNUNGSVERSORGUNG_SV2_WERT|38|2|u|1|2048|0|V
STAT_ISTSTROM_MAGNETVENTIL_PV1_WERT|40|2|s|1|1000|0|A
STAT_ISTSTROM_MAGNETVENTIL_PV2_WERT|42|2|s|1|1000|0|A
STAT_ISTSTROM_MAGNETVENTIL_PV3_WERT|44|2|s|1|1000|0|A
STAT_ISTSTROM_MAGNETVENTIL_PV4_WERT|46|2|s|1|1000|0|A
STAT_ISTSTROM_MAGNETVENTIL_PV6_WERT|48|2|s|1|1000|0|A
STAT_ISTSTROM_MAGNETVENTIL_PV7_WERT|50|2|s|1|1000|0|A
STAT_SOLLSTROM_MAGNETVENTIL_PV1_WERT|52|2|s|1|1000|0|A
STAT_SOLLSTROM_MAGNETVENTIL_PV2_WERT|54|2|s|1|1000|0|A
STAT_SOLLSTROM_MAGNETVENTIL_PV3_WERT|56|2|s|1|1|0|mA
STAT_SOLLSTROM_MAGNETVENTIL_PV4_WERT|58|2|s|1|1|0|mA
STAT_SOLLSTROM_MAGNETVENTIL_PV6_WERT|60|2|s|1|1000|0|A
STAT_SOLLSTROM_MAGNETVENTIL_PV7_WERT|62|2|s|1|1000|0|A
STAT_ISTDRUCK_KUPPLUNG1_WERT|64|2|s|1|100|0|bar
STAT_ISTDRUCK_KUPPLUNG2_WERT|66|2|s|1|100|0|bar
STAT_SOLLDRUCK_KUPPLUNG1_WERT|68|2|s|1|100|0|bar
STAT_SOLLDRUCK_KUPPLUNG2_WERT|70|2|s|1|100|0|bar
STAT_ISTMOMENT_KUPPLUNG1_WERT|72|2|s|1|8|0|Nm
STAT_ISTMOMENT_KUPPLUNG2_WERT|74|2|s|1|8|0|Nm
STAT_SOLLMOMENT_KUPPLUNG1_WERT|76|2|s|1|8|0|Nm
STAT_SOLLMOMENT_KUPPLUNG2_WERT|78|2|s|1|8|0|Nm
STAT_ISTPOSITION_SCHALTSTANGE_6_4_WERT|80|2|s|1|100|0|mm
STAT_ISTPOSITION_SCHALTSTANGE_5_7_WERT|82|2|s|1|100|0|mm
STAT_ISTPOSITION_SCHALTSTANGE_2_R_WERT|84|2|s|1|100|0|mm
STAT_ISTPOSITION_SCHALTSTANGE_1_3_WERT|86|2|s|1|100|0|mm
STAT_SOLLPOSITION_SCHALTSTANGE_6_4_NR|88|1|u|1|1|0|0-n
STAT_SOLLPOSITION_SCHALTSTANGE_5_7_NR|89|1|u|1|1|0|0-n
STAT_SOLLPOSITION_SCHALTSTANGE_2_R_NR|90|1|u|1|1|0|0-n
STAT_SOLLPOSITION_SCHALTSTANGE_1_3_NR|91|1|u|1|1|0|0-n
STAT_FAHRPEDAL_WERT|92|1|u|0.4|1|0|%
STAT_MOTORISTMOMENT_WERT|93|2|s|1|8|0|A
STAT_AQUER_CAN_WERT|95|2|s|1|40|0|m/s²
STAT_KILOMETERSTAND_WERT|97|4|u|1|1|0|km
STAT_HYDRAULIKDRUCK_WERT|101|2|s|1|100|0|bar
STAT_PARKSPERRE_AKTIV|103|1|u|1|1|0|0/1
STAT_PARKSPERRE_SENSOR1_EIN|104|1|u|1|1|0|0/1
STAT_PARKSPERRE_SENSOR2_EIN|105|1|u|1|1|0|0/1
STAT_KL15_EIN|106|1|u|1|1|0|0/1
STAT_KUPPLUNG1_NR|107|1|u|1|1|0|0-n
STAT_KUPPLUNG2_NR|108|1|u|1|1|0|0-n
STAT_ISTGANG_NR|109|1|u|1|1|0|0-n
STAT_SCHALTSTANGE_6_4_NR|110|1|u|1|1|0|0-n
STAT_SCHALTSTANGE_5_7_NR|111|1|u|1|1|0|0-n
STAT_SCHALTSTANGE_2_R_NR|112|1|u|1|1|0|0-n
STAT_SCHALTSTANGE_1_3_NR|113|1|u|1|1|0|0-n
STAT_GETRIEBEPOSITION_WERT|114|1|u|1|1|0|
STAT_OBD_STEUERFUNKTION|115|1|u|1|1|0|0-n
STAT_SPORT_TASTER_EIN|116|1|u|1|1|0|0/1
STAT_PROGRAMMINFO_WERT|117|1|u|1|1|0|
STAT_GANGANZEIGE_WERT|118|1|u|1|1|0|
STAT_WAEHLHEBELANZEIGE_WERT|119|1|u|1|1|0|
STAT_MIL_WERT|120|1|u|1|1|0|
STAT_KL15_CAN_EIN|121|1|u|1|1|0|0/1
STAT_BREMSLICHTSCHALTER_EIN|122|1|u|1|1|0|0/1
STAT_ENDSTUFE_FEHLER|123|1|u|1|1|0|0/1
STAT_ISTGANG_TEILGETRIEBE1_NR|124|1|u|1|1|0|0-n
STAT_ISTGANG_TEILGETRIEBE2_NR|125|1|u|1|1|0|0-n
STAT_FESTSTELLBREMSE_EIN|126|1|u|1|1|0|0/1
STAT_SCHALTDIAGRAMM_AGS_WERT|127|1|u|1|1|0|
STAT_ANTRIEBSDREHZAHLSENSOR_WERT|128|2|s|1|4|0|
''',
    'DE50': '''
STAT_FAHRZEUGTYP|0|1|u|1|1|0|0/1
STAT_ANZ_LOESCHUNGEN_WERT|1|2|u|1|1|0|
STAT_KM_STAND_LETZTER_LOESCHUNG_WERT|3|4|u|1|1|0|
STAT_ANZ_RENNSTARTS_WERT|7|2|u|1|1|0|
STAT_ANZ_SCHALTUNG_GANG_1_WERT|9|4|u|1|1|0|
STAT_ANZ_SCHALTUNG_GANG_2_WERT|13|4|u|1|1|0|
STAT_ANZ_SCHALTUNG_GANG_3_WERT|17|4|u|1|1|0|
STAT_ANZ_SCHALTUNG_GANG_4_WERT|21|4|u|1|1|0|
STAT_ANZ_SCHALTUNG_GANG_5_WERT|25|4|u|1|1|0|
STAT_ANZ_SCHALTUNG_GANG_6_WERT|29|4|u|1|1|0|
STAT_ANZ_SCHALTUNG_GANG_7_WERT|33|4|u|1|1|0|
STAT_ANZ_SCHALTUNG_GANG_R_WERT|37|4|u|1|1|0|
STAT_ANZ_SMOKIE_BURNOUTS_WERT|41|2|u|1|1|0|
STAT_ANZ_EINLEGEHAENGER_GANG_1_WERT|43|1|u|1|1|0|
STAT_ANZ_EINLEGEHAENGER_GANG_2_WERT|44|1|u|1|1|0|
STAT_ANZ_EINLEGEHAENGER_GANG_3_WERT|45|1|u|1|1|0|
STAT_ANZ_EINLEGEHAENGER_GANG_4_WERT|46|1|u|1|1|0|
STAT_ANZ_EINLEGEHAENGER_GANG_5_WERT|47|1|u|1|1|0|
STAT_ANZ_EINLEGEHAENGER_GANG_6_WERT|48|1|u|1|1|0|
STAT_ANZ_EINLEGEHAENGER_GANG_7_WERT|49|1|u|1|1|0|
STAT_ANZ_EINLEGEHAENGER_GANG_R_WERT|50|1|u|1|1|0|
STAT_AUFENTHALTSDAUER_OELSUMPF_KLEINER_MINUS_30_GRAD_WERT|51|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_MINUS_30_BIS_MINUS_20_GRAD_WERT|55|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_MINUS_20_BIS_MINUS_10_GRAD_WERT|59|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_MINUS_10_BIS_0_GRAD_WERT|63|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_0_BIS_10_GRAD_WERT|67|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_10_BIS_20_GRAD_WERT|71|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_20_BIS_30_GRAD_WERT|75|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_30_BIS_40_GRAD_WERT|79|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_40_BIS_50_GRAD_WERT|83|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_50_BIS_60_GRAD_WERT|87|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_60_BIS_70_GRAD_WERT|91|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_70_BIS_80_GRAD_WERT|95|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_80_BIS_90_GRAD_WERT|99|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_90_BIS_100_GRAD_WERT|103|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_100_BIS_110_GRAD_WERT|107|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_110_BIS_120_GRAD_WERT|111|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_120_BIS_130_GRAD_WERT|115|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_130_BIS_140_GRAD_WERT|119|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_140_BIS_150_GRAD_WERT|123|4|u|1|1|0|min
STAT_AUFENTHALTSDAUER_OELSUMPF_150_BIS_160_GRAD_WERT|127|4|u|1|1|0|min
STAT_ANZ_FAHRSTUFE_ANFORDERN_OHNE_BREMSE_WERT|131|1|u|1|1|0|
STAT_ANZ_R_GANG_ANFORDERN_UEBER_V_SCHWELLE_WERT|132|1|u|1|1|0|
STAT_ANZ_AUTO_P_FAHRZEUGVERLASSEN_WERT|133|1|u|1|1|0|
STAT_ANZ_P_ANFORDERN_V_UEBER_SCHWELLE_WERT|134|1|u|1|1|0|
STAT_KUPPLUNGSTEMPERATUR_K1_MAX_WERT|135|2|s|1|1|0|°C
STAT_ANZ_K1_MAX_TEMPERATUR_WERT|137|4|u|1|1|0|
STAT_KUPPLUNGSTEMPERATUR_K2_MAX_WERT|141|2|s|1|1|0|°C
STAT_ANZ_K2_MAX_TEMPERATUR_WERT|143|4|u|1|1|0|
STAT_ABSPRITZSSENSORTEMPERATUR_MAX_WERT|147|2|s|1|1|0|°C
STAT_ANZ_MAX_TEMPERATUR_ABSPRITZSENSOR_WERT|149|4|u|1|1|0|
STAT_AUFENTHALTSDAUER_FAHRMODUS_1_WERT|153|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_2_WERT|157|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_3_WERT|161|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_4_WERT|165|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_5_WERT|169|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_6_WERT|173|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_7_WERT|177|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_8_WERT|181|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_9_WERT|185|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_10_WERT|189|4|u|1|1|0|s
STAT_AUFENTHALTSDAUER_FAHRMODUS_11_WERT|193|4|u|1|1|0|s
''',
    'DE51': '''
STAT_ANZ_ZAEHLER_0_PV6_ADAPTIONEN_WERT|0|1|u|1|1|0|
STAT_ANZ_ZAEHLER_1_PV6_ADAPTIONEN_WERT|1|1|u|1|1|0|
STAT_ANZ_ZAEHLER_2_PV6_ADAPTIONEN_WERT|2|1|u|1|1|0|
STAT_ANZ_ZAEHLER_K1_ADAPTIONEN_WERT|3|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K2_ADAPTIONEN_WERT|5|2|u|1|1|0|
STAT_KILOMETERSTAND_LETZTER_K1_ADAPTION_WERT|7|4|u|1|1|0|km
STAT_KILOMETERSTAND_LETZTER_K2_ADAPTION_WERT|11|4|u|1|1|0|km
STAT_KISSPOINT_K1_MIN_WERT|15|2|s|1|1|0|
STAT_KISSPOINT_K2_MIN_WERT|17|2|s|1|1|0|
STAT_KILOMETERSTAND_K1_MIN_WERT|19|4|u|1|1|0|km
STAT_KILOMETERSTAND_K2_MIN_WERT|23|4|u|1|1|0|km
STAT_KISSPOINT_K1_MAX_WERT|27|2|s|1|1|0|
STAT_KISSPOINT_K2_MAX_WERT|29|2|s|1|1|0|
STAT_KILOMETERSTAND_K1_MAX_WERT|31|4|u|1|1|0|km
STAT_KILOMETERSTAND_K2_MAX_WERT|35|4|u|1|1|0|km
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K1_MAX50_WERT|39|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K1_MIN50_WERT|40|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K1_MAX300_WERT|41|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K1_MIN300_WERT|42|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K2_MAX50_WERT|43|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K2_MIN50_WERT|44|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K2_MAX300_WERT|45|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K2_MIN300_WERT|46|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K1_300_BEI_MAX50_WERT|47|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K1_300_BEI_MIN50_WERT|48|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K1_50_BEI_MAX300_WERT|49|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K1_50_BEI_MIN300_WERT|50|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K2_300_BEI_MAX50_WERT|51|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K2_300_BEI_MIN50_WERT|52|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K2_50_BEI_MAX300_WERT|53|1|s|1|1|0|
STAT_KUPPLUNGSADAPTIONSKENNLINIE_K2_50_BEI_MIN300_WERT|54|1|s|1|1|0|
STAT_ANZ_ZAEHLER_K1_ADAPTIONEN_50NM_WERT|55|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K1_ADAPTIONEN_75NM_WERT|57|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K1_ADAPTIONEN_125NM_WERT|59|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K1_ADAPTIONEN_200NM_WERT|61|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K1_ADAPTIONEN_300NM_WERT|63|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K2_ADAPTIONEN_50NM_WERT|65|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K2_ADAPTIONEN_75NM_WERT|67|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K2_ADAPTIONEN_125NM_WERT|69|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K2_ADAPTIONEN_200NM_WERT|71|2|u|1|1|0|
STAT_ANZ_ZAEHLER_K2_ADAPTIONEN_300NM_WERT|73|2|u|1|1|0|
''',
}

# Baseline measured on the S63TU vehicle, November 13, 2026; the simulator
# reproduces these counters instead of fabricating lifetime statistics.
# Live fields may be animated independently. These are demonstration values,
# NOT diagnostic information about the emulator user's own vehicle.
_DKG_10_CAPTURE_SEEDS = {
    'DE30': ('0C3F00000000000000000000000000000000000000400033001E00150003730B3A6D27D227E527E2010800BD0000000104CA02BC010800BE0000000004CB02BCFFFF0006000000000000000000000000001E0012FCBAFC980000000000FFE2FFFC0003E31401F4000101010101000101020208020080000001010001010201000C3F'),
    'DE50': ('01000000000000000000010280000214B200027917000253C10002002000018BE2000097E200002F2100006600000C0000040900000000000000000000000400000045000002DE00000E890000298F000054050000A2E90000E62F0000B05E000035ED0000010000000000000000000000000000000000000000000000000000000000DC0F0000007D00000001008000000000007D0000000000000AA6000029300017AD2400000000000000000000000000774E400008EFFF00047FAC0000000000000000'),
    'DE51': ('16204F1683249B00031C0000031C0000B400B9000000000000000000C800C600001C78000036F8775572646F546D6465706B74646D556CFFFFFFFFFFFFB39D0846AA8FFFFF895A1C78021D'),
}


def _dkg_10_preset():
    """Build every DKG field using PRG-defined affine scaling, big-endian bytes.

    Algorithms: sequential fixed-offset record packing and raw-to-physical
    scaling (physical = raw * MUL / DIV + ADD). ``encode_value`` performs
    the inverse on simulated values. The supplied capture seeds the defaults.
    """
    dids = {
        'F150': {'name': 'DKG_10 identification (captured)', 'hex': '0F1870'},
    }
    for did, layout in _DKG_10_LAYOUTS.items():
        seed = bytes.fromhex(_DKG_10_CAPTURE_SEEDS[did])
        fields = []
        for line in layout.strip().splitlines():
            name, pos, width, sign, mul, div, add, unit = line.split('|')
            pos, width = int(pos), int(width)
            mul, div, add = float(mul), float(div), float(add)
            assert div and mul, (did, name)
            raw = int.from_bytes(seed[pos:pos + width], 'big', signed=(sign == 's'))
            physical = raw * mul / div + add
            entry = _v(name, unit, width, mul / div, physical, offset=add,
                       signed=(sign == 's'), pos=pos)
            # Animate only rapidly-changing live channels; preserve the captured
            # historical statistics exactly unless the user edits uds.json.
            if did == 'DE30' and name == 'STAT_KUPPLUNGSOELTEMPERATUR_WERT':
                entry['wave'] = {'min': physical, 'max': physical + 35, 'period': 90}
            elif did == 'DE30' and name == 'STAT_MOTORDREHZAHL_WERT':
                entry['wave'] = {'min': physical, 'max': 2200, 'period': 8}
            fields.append(entry)
        dids[did] = {'name': 'DKG_10 %s (%d PRG fields)' % (did, len(fields)),
                     'length': len(seed), 'fill': 0, 'fields': fields}
    return {'name': 'DKG / EGS', 'dids': dids}


def _obd_s63tu(bank):
    """SAE J1979 OBD mode 01 signals; bank selects diagnostic ECU 12/13.

    01 06/07 are Bank 1 trim PIDs *within that DME*, so BoostDeck STFT 2
    requests 01 06 from ECU 0x13, not Bank-2 PID 01 08 from ECU 0x12.
    """
    second = bank == 2
    return {
        '04': _v('Calculated engine load', '%', 1, 100 / 255.0,
                 wave=(8.24 if second else 8.63, 48 if second else 45, 8)),
        '05': _v('Coolant temperature', 'C', 1, 1, 64, offset=-40),
        '06': _v('STFT on DME%d (OBD Bank 1)' % bank, '%', 1, 100 / 128.0,
                 wave=(3.125 if second else 1.5625, 9.375, 5), offset=-100),
        '07': _v('LTFT on DME%d (OBD Bank 1)' % bank, '%', 1, 100 / 128.0,
                 3.125, offset=-100),
        '0C': _v('Engine speed', 'rpm', 2, 0.25, wave=(780, 2200, 8)),
        '0D': _v('Vehicle speed', 'km/h', 1, 1, 0),
        '10': _v('Mass air flow', 'g/s', 2, 0.01, wave=(3.19 if second else 3.30, 12, 8)),
    }


def _add_s63tu_extended_presets():
    dme1 = PRESETS['s63tu']['ecus']['12']
    dme1['name'] = 'DME1'
    dme1['obd'] = _obd_s63tu(1)
    # Keep the grouped and standardized MAF/coolant/RPM simulations consistent.
    # The actual grouped 4000 PRG field definitions remain unchanged.
    for f in dme1['dids']['4000']['fields']:
        if f['name'].startswith('STAT_MAF_KGH_MES_BAS'):
            f['wave'] = {'min': 11.8, 'max': 43.2, 'period': 12}
        elif f['name'].startswith('STAT_TPS_AV_1'):
            f['wave'] = {'min': 2.42, 'max': 38, 'period': 8}
        elif f['name'].startswith('STAT_NMOT_W_MW'):
            f['wave'] = {'min': 780, 'max': 2200, 'period': 8}
        elif f['name'].startswith('STAT_TMOT (coolant)'):
            f['value'] = 64
    # 22 43 00 was captured as a ONE-byte temperature, not the older B58
    # two-byte value. The PRG scaling is byte * 0.75 - 48 degrees C.
    dme1['dids']['4300'] = _v('S63TU coolant temperature', 'C', 1, 0.75, 64, offset=-48)
    # Additional captured PRG adaptation DIDs: preserve their exact bytes;
    # no undocumented signal offsets are asserted here.
    dme1['dids']['400A'] = {'name': 'S63TU mixture adaptation (captured)',
                             'hex': 'FFFFFFFf850EFFFF274BFFFFFFFF'}
    dme1['dids']['4046'] = {'name': 'S63TU lambda adaptation (captured)',
                             'hex': '867EFFEB7E3B8B0F800682D07D968F7A7F718EB5761B819580027F1A7E327F1D8000800081D40000'}
    # Actual DME1 returned 41 23 02 93 in the supplied full capture.
    dme1['obd']['23'] = _v('Fuel rail pressure (gauge)', 'bar', 2, 0.1,
                            wave=(65.9, 140, 9))
    # 01 5C was advertised in the live 01 40 bitmap but no response was
    # recorded: emulate the STANDARD conversion, not a confirmed live value.
    dme1['obd']['5C'] = _v('Engine oil temperature', 'C', 1, 1,
                            wave=(72, 98, 75), offset=-40)
    # The second S63TU DME responds to 22 40 00 / 42 01 / 42 05 / 58 89
    # in the supplied dual-DME log; do not map it to hypothetical Bank-2 PIDs.
    dme2_dids = copy.deepcopy(dme1['dids'])
    dme2_dids['4000']['name'] = 'STATUS_MESSWERTE DME2'
    for f in dme2_dids['4000']['fields']:
        if f['name'].startswith('STAT_MAF_KGH_MES_BAS'):
            f['wave'] = {'min': 11.5, 'max': 42, 'period': 12}
    dme2_dids['400A'] = {'name': 'S63TU mixture adaptation DME2 (captured)',
                          'hex': 'FFFFFFFF8546FFFF2909FFFFFFFF'}
    dme2_dids['4046'] = {'name': 'S63TU lambda adaptation DME2 (captured)',
                          'hex': '86CCFFE17CC18CFA800580367CD983DC7FA283C173897FFC80017D857B4F7DAC7FFF80007F790000'}
    PRESETS['s63tu']['ecus']['13'] = {'name': 'DME2', 'dids': dme2_dids,
                                     'obd': _obd_s63tu(2)}
    PRESETS['dkg_10'] = {
        'label': 'DKG_10 / Getrag LES4 (transmission live + statistics)',
        'note': 'DKG_10 PRG verified DIDs 22 DE30, 22 DE50 and 22 DE51. '
                'Static lifetime counters seeded from November 13 capture.',
        'ecus': {'18': _dkg_10_preset()},
    }
    PRESETS['s63tu']['ecus']['18'] = copy.deepcopy(PRESETS['dkg_10']['ecus']['18'])
    PRESETS['s63tu']['label'] = 'S63TU BoostDeck (DME1 + DME2 + DKG_10)'
    PRESETS['s63tu']['note'] += (' Includes OBD 01 04/06/07/0C/10 from both DMEs, '
                                 'DME1 01 23/5C, and PRG-derived DKG DE30/50/51.')


_add_s63tu_extended_presets()


# ------------------------------------------------------------------------------------------------- vehicle profiles
# Complete virtual cars for testing BoostDeck's automatic engine/gearbox identification. Use them with the UDS tab's
# "Replace" button (Add would leave ECUs of the previous car behind, e.g. DME2 0x13). The original b58/s63tu/dkg_10
# presets and the default configuration are unchanged.
#
# Identification DIDs (PRG IDENT / ECU_CONFIG jobs, s63tu_r0.prg, n55_alp.prg, dkg_10.prg):
#   22 F150  ID_SGBD_INDEX = data bytes 0..2. Only DKG_10 0F1870 is a captured value; the DME indices below are
#            emulator placeholders (marked as such) so a change of virtual car is visible to the plugin.
#   22 5FF2  ECU_CONFIG on MEVD17 DMEs: 74 data bytes; STAT_TURBO_WERT byte 3, STAT_EGS_WERT byte 26,
#            STAT_DKG_WERT byte 27, STAT_MSA_WERT byte 32 (raw flags). The B58 (MG1) PRG is not available, so the
#            B58 profile does not answer 5FF2.
def _ecu_config(egs, dkg):
    return {'name': 'ECU_CONFIG (PRG 22 5FF2)', 'length': 74, 'fill': 0, 'fields': [
        _v('STAT_TURBO_WERT', '0/1', 1, 1, 1, pos=3),
        _v('STAT_EGS_WERT', '0/1', 1, 1, egs, pos=26),
        _v('STAT_DKG_WERT', '0/1', 1, 1, dkg, pos=27),
        _v('STAT_MSA_WERT', '0/1', 1, 1, 1, pos=32),
    ]}


def _placeholder_index(hexstr):
    return {'name': 'IDENT SGBD index (emulator placeholder, not a captured car value)', 'hex': hexstr}


def _obd_single_dme(extra=None):
    """SAE J1979 mode 01 for a single-DME inline six (one bank: 01 06/07 only)."""
    d = {
        '04': _v('Calculated engine load', '%', 1, 100 / 255.0, wave=(9, 55, 8)),
        '05': _v('Coolant temperature', 'C', 1, 1, 88, offset=-40),
        '06': _v('STFT bank 1', '%', 1, 100 / 128.0, wave=(-3.1, 6.25, 5), offset=-100),
        '07': _v('LTFT bank 1', '%', 1, 100 / 128.0, 2.3, offset=-100),
        '0C': _v('Engine speed', 'rpm', 2, 0.25, wave=(750, 6200, 8)),
        '0D': _v('Vehicle speed', 'km/h', 1, 1, wave=(0, 110, 20)),
        '0F': _v('Intake air temperature', 'C', 1, 1, 31, offset=-40),
        '10': _v('Mass air flow', 'g/s', 2, 0.01, wave=(4.5, 180, 8)),
        '11': _v('Throttle position', '%', 1, 100 / 255.0, wave=(3, 85, 6)),
        '23': _v('Fuel rail pressure (gauge)', 'bar', 2, 0.1, wave=(50, 200, 9)),
        '5C': _v('Engine oil temperature', 'C', 1, 1, wave=(85, 104, 75), offset=-40),
    }
    if extra: d.update(extra)
    return d


# N55 STATUS_MESSWERTE (n55_alp.prg, 22 40 00 -> 62 40 00 + 44 data bytes). Offsets are data-byte positions; the
# scalars used by BoostDeck sit at the same positions as on the S63TU (40 bytes), the N55 adds LR2 at byte 6 and
# six knock channels. Data bytes 0..3 are not defined by the PRG (FF fill).
_N55_4000_FIELDS = [
    _v('STAT_LR1_MW (lambda regulator 1)', '', 2, 0.000244140625, 1.0, pos=4),
    _v('STAT_LR2_MW (lambda regulator 2)', '', 2, 0.000244140625, 1.0, pos=6),
    _v('STAT_VFZG_MW (vehicle speed)', 'km/h', 2, 0.0078125, wave=(0, 110, 20), pos=8),
    _v('STAT_NMOT_W_MW (engine speed)', '1/min', 2, 0.25, wave=(750, 6200, 8), pos=10),
    _v('STAT_NSOL_MW (target idle)', '1/min', 2, 0.25, 680, pos=12),
    _v('STAT_CAM_IN (intake cam)', 'degCA', 2, 0.0078125, 18, signed=True, pos=14),
    _v('STAT_CAM_EX (exhaust cam)', 'degCA', 2, 0.0078125, -12, signed=True, pos=16),
    _v('STAT_TIA (intake air)', 'C', 1, 0.75, 31, offset=-48, pos=18),
    _v('STAT_TMOT (coolant)', 'C', 1, 0.75, 88, offset=-48, pos=19),
    _v('STAT_IGA_IGC (ignition angle)', 'deg', 2, 0.1, wave=(2, 24, 7), signed=True, pos=20),
    _v('STAT_TPS_AV_1 (throttle)', '% DK', 2, 0.0244140625, wave=(3, 85, 6), signed=True, pos=22),
    _v('STAT_MAF_KGH_MES_BAS (air mass)', 'kg/h', 2, 0.1, wave=(16, 650, 8), signed=True, pos=24),
    _v('STAT_TQI_AV (torque)', 'Nm', 2, 0.5, wave=(30, 420, 8), signed=True, pos=26),
    _v('STAT_VB (battery)', 'V', 1, 0.0942, 14.2, pos=28),
    _v('STAT_V_PVS_1 (pedal sensor)', 'V', 2, 0.0048828125, 0.75, pos=29, mask=1023),
    _v('STAT_TMOTLINF', 'C', 1, 0.75, 88, offset=-48, pos=31),
] + [_v('STAT_NL_%d (knock)' % n, 'V', 2, 0.0048828125, 1.0, pos=p)
     for n, p in ((1, 32), (5, 34), (3, 36), (6, 38), (2, 40), (4, 42))]


def _mevd17_standalone(label):
    """SG_FUNKTIONEN standalone DIDs shared by n55_alp.prg and s63tu_r0.prg (service 22)."""
    return {
        '4201': _v(label + ' ambient pressure (STAT_UMGEBUNGSDRUCK)', 'kPa', 2, 1 / 256.0, 100.9),
        '4205': _v(label + ' boost pressure absolute (STAT_LADEDRUCK)', 'kPa', 2, 1 / 128.0, wave=(100, 230, 8)),
        '5889': _v(label + ' lambda bank 1 (STAT_LAMBDA_ISTWERT_GRUPPE1)', '', 2, 1 / 4096.0, wave=(0.82, 1.01, 5)),
        '4A49': _v(label + ' ignition cyl 1 (STAT_ZUENDWINKEL_ZYL1)', 'deg', 2, 0.1, signed=True, wave=(2, 24, 7)),
        '580F': _v(label + ' intake air temperature (STAT_ANSAUGLUFTTEMPERATUR)', 'C', 1, 0.75, 31, offset=-48),
        '4300': _v(label + ' coolant temperature (STAT_KUEHLMITTELTEMPERATUR)', 'C', 1, 0.75, 88, offset=-48),
        '4807': _v(label + ' engine speed (STAT_MOTORDREHZAHL)', '1/min', 2, 0.25, wave=(750, 6200, 8)),
        '586F': _v(label + ' oil pressure (STAT_0x586F, hPa)', 'hPa', 2, 1, wave=(1800, 4500, 9), signed=True),
    }


# ZF 8HP Gen2 (gkeb23tu.prg "Elektronische Getriebesteuerung Elektrische-Schaltung", EGS_EL), SG_FUNKTIONEN and
# RES_0x.... tables. EDIABAS types: int = signed 16 bit, unsigned int = 16 bit, (unsigned) long = 32 bit, char = 8 bit.
# Counter/time values are plausible seeds, not captured from a car.
_EGS_TEMP_RANGES_S = (40 * 3600, 210 * 3600, 260 * 3600, 330 * 3600, 290 * 3600, 150 * 3600, 70 * 3600,
                      22 * 3600, 6 * 3600, 2 * 3600, 1500, 120, 0)   # RES_0x4441, 13 x u32 seconds


def _egs_8hp(index_hex):
    ranges = '-40..40,40..80,80..90,90..95,95..100,100..105,105..110,110..115,115..120,120..130,130..140,' \
             '140..170,uncertain'.split(',')
    return {'name': 'EGS (ZF 8HP, gkeb23tu)', 'dids': {
        'F150': _placeholder_index(index_hex),
        'DA12': _v('STAT_GETRIEBEOELTMEPERATUR_WERT (oil temp)', 'C', 2, 1, wave=(62, 96, 120), offset=-48,
                   signed=True),
        'DA25': _v('STAT_MOTOROELTEMPERATUR_WERT (engine oil)', 'C', 2, 1, 98, offset=-48, signed=True),
        'DA26': _v('STAT_MOTORTEMPERATUR_WERT (engine)', 'C', 2, 1, 90, offset=-48, signed=True),
        'DA1C': _v('STAT_GESCHWINDIGKEIT_WERT (speed)', 'km/h', 2, 1 / 16.0, wave=(0, 110, 20), signed=True),
        'DA2E': _v('STAT_ISTGANG (current gear)', '0-n', 2, 1, 4, signed=True),
        'DA37': {'name': 'RES_0xDA37 time in D / S / manual', 'length': 12, 'fill': 0, 'fields': [
            _v('STAT_D_ZAEHLER_WERT', 's', 4, 1, 1250 * 3600, pos=0),
            _v('STAT_S_ZAEHLER_WERT', 's', 4, 1, 210 * 3600, pos=4),
            _v('STAT_M_ZAEHLER_WERT', 's', 4, 1, 35 * 3600, pos=8)]},
        '4441': {'name': 'RES_0x4441 time per oil temperature range', 'length': 52, 'fill': 0, 'fields': [
            _v('STAT_TEMPERATURBEREICH_%d_WERT (%s C)' % (i + 1, r), 's', 4, 1, v, pos=i * 4)
            for i, (r, v) in enumerate(zip(ranges, _EGS_TEMP_RANGES_S))]},
        '4130': {'name': 'RES_0x4130 fast-fill adaptation counters A..E', 'length': 10, 'fill': 0, 'fields': [
            _v('STAT_ADAPTIONSWERTE_KSFCTR_KUPPLUNG_%s_WERT' % c, '', 2, 1, v, pos=i * 2)
            for i, (c, v) in enumerate(zip('ABCDE', (412, 388, 405, 97, 233)))]},
        '4131': {'name': 'RES_0x4131 fill-pressure adaptation counters A..E', 'length': 10, 'fill': 0, 'fields': [
            _v('STAT_ADAPTIONSWERTE_KPFCTR_KUPPLUNG_%s_WERT' % c, '', 2, 1, v, pos=i * 2)
            for i, (c, v) in enumerate(zip('ABCDE', (1210, 1188, 1302, 640, 954)))]},
        '4132': _v('STAT_ADAPTIONSWERTE_NICCTR_WERT (NIC adaptations)', '', 2, 1, 57),
        '41A1': _v('STAT_ADAPTIONSWERTE_WK_CTR_WERT (converter adaptations)', '', 2, 1, 143),
        '4300': _v('STAT_AUTO_P_EMF3_ZAEHLER_WERT', '', 1, 1, 3),
        '4301': _v('STAT_AUTO_P_EMF2_ZAEHLER_WERT', '', 1, 1, 11),
        '4302': _v('STAT_AUTO_P_EMF1_ZAEHLER_WERT', '', 1, 1, 6),
        '4445': _v('STAT_COUNT_FORCEDSHIFTUP_WERT (engine upshift requests)', '', 1, 1, 21),
        '431B': _v('STAT_CNT_ENGER_ENABLED_WERT (P engaged by EGNER)', '', 1, 1, 2),
    }}


def _egs_ecu(index_hex):
    return _egs_8hp(index_hex)


def _add_vehicle_profiles():
    # S63TU (F1x M5/M6): DME1 0x12 + DME2 0x13 + DKG_10 0x18, i.e. the existing s63tu preset plus identification.
    s63 = copy.deepcopy(PRESETS['s63tu'])
    s63['ecus']['12']['dids']['F150'] = _placeholder_index('0A6301')
    s63['ecus']['12']['dids']['5FF2'] = _ecu_config(egs=0, dkg=1)
    s63['ecus']['13']['dids']['F150'] = _placeholder_index('0A6302')
    s63['ecus']['13']['dids']['5FF2'] = _ecu_config(egs=0, dkg=1)
    PRESETS['vehicle_s63tu'] = {
        'label': 'Vehicle: S63TU M5/M6 (DME1 + DME2 + DKG_10)',
        'note': 'Twin MEVD17.2.8 DMEs (0x12/0x13, 22 4000 = 40 data bytes) and DKG_10 (F150 0F1870 captured). '
                'ECU_CONFIG reports DKG. DME F150 values are placeholders. Use Replace.',
        'ecus': s63['ecus'],
    }
    # N55 (single MEVD17.2 DME), 8HP automatic.
    n55_dids = _mevd17_standalone('N55')
    n55_dids['4000'] = {'name': 'STATUS_MESSWERTE (n55_alp.prg)', 'length': 44, 'fill': 0xFF,
                        'fields': copy.deepcopy(_N55_4000_FIELDS)}
    n55_dids['F150'] = _placeholder_index('0A5501')
    n55_dids['5FF2'] = _ecu_config(egs=1, dkg=0)
    PRESETS['vehicle_n55'] = {
        'label': 'Vehicle: N55 + ZF 8HP (n55_alp + gkeb23tu)',
        'note': 'n55_alp.prg: 22 4000 = 44 data bytes, standalone DIDs from SG_FUNKTIONEN, OBD mode 01 baseline. '
                'No DME2. ECU_CONFIG reports EGS. 8HP from gkeb23tu.prg: DA12 oil temp, time in D/S/M, oil '
                'temperature histogram, adaptation and auto-P counters. F150 values are placeholders. Use Replace.',
        'ecus': {'12': {'name': 'DME (N55)', 'dids': n55_dids, 'obd': _obd_single_dme()},
                 '18': _egs_ecu('0A8801')},
    }
    # B58 (MG1): the reference DIDs from SIGNALS.md; no PRG available, so no 4000 group and no ECU_CONFIG.
    b58_dids = copy.deepcopy(PRESETS['b58']['ecus']['12']['dids'])
    b58_dids['F150'] = _placeholder_index('0B5801')
    PRESETS['vehicle_b58'] = {
        'label': 'Vehicle: B58 340i (single DME + 8HP EGS)',
        'note': 'Reference B58 DIDs (docs/SIGNALS.md) plus OBD mode 01. No B58 PRG: 22 4000 and 22 5FF2 answer '
                'NRC 31, like an unknown DME. F150 values are placeholders. Use Replace.',
        'ecus': {'12': {'name': 'DME (B58)', 'dids': b58_dids, 'obd': _obd_single_dme()},
                 '18': _egs_ecu('0A8802')},
    }


_add_vehicle_profiles()

SERVICES = {0x10: 'DiagnosticSessionControl', 0x11: 'ECUReset', 0x14: 'ClearDTC', 0x19: 'ReadDTC', 0x22: 'ReadDataByIdentifier',
            0x27: 'SecurityAccess', 0x2F: 'IOControl', 0x31: 'RoutineControl', 0x3E: 'TesterPresent', 0x01: 'OBD mode 01',
            0x09: 'OBD mode 09'}


def default_config():
    cfg = {'gateway_ips': [DEFAULT_IP], 'unknown_ecu': 'silent', 'ecus': {}}
    merge_preset(cfg, 'b58')
    return cfg


def merge_preset(cfg, name):
    p = PRESETS[name]
    for addr, ecu in p['ecus'].items():
        dst = cfg.setdefault('ecus', {}).setdefault(addr, {'name': ecu.get('name', '')})
        if not dst.get('name'): dst['name'] = ecu.get('name', '')
        for kind in ('dids', 'obd'):
            if ecu.get(kind): dst.setdefault(kind, {}).update(copy.deepcopy(ecu[kind]))
        if ecu.get('raw'): dst.setdefault('raw', []).extend(copy.deepcopy(ecu['raw']))
    return cfg


def upgrade_legacy_s63tu_4000(v):
    """Upgrade only the known old 36-byte STATUS_MESSWERTE layout, preserving user values.

    The prior emulator omitted the six reserved FF bytes: four at the beginning
    and two between lambda regulator and vehicle speed. Only the exact legacy
    offset pattern is migrated, so unrelated/custom DID definitions are intact.
    """
    old_positions = (0, 4, 6, 8, 10, 12, 14, 15, 16, 18, 20, 22, 24, 25, 27, 28, 30, 32, 34)
    if (v.get('name') != 'STATUS_MESSWERTE' or v.get('length') != 36 or
        len(v.get('fields') or []) != len(old_positions) or
        tuple(f.get('pos') for f in v['fields']) != old_positions):
        return v
    updated = copy.deepcopy(v)
    updated['length'] = 40
    updated['fill'] = 0xFF
    for f in updated['fields']:
        f['pos'] += 4
        if f.get('name') == 'STAT_LR1_MW (lambda bank 1)':
            f['name'] = 'STAT_LR1_MW (lambda regulator 1)'
    return updated


# ---------------------------------------------------------------------------------------------------------- encoding
def hexb(s):
    return bytes.fromhex(''.join(str(s).split()).replace('0x', '').replace('0X', ''))


def norm_key(k, width):
    k = str(k).strip().upper().replace('0X', '')
    int(k, 16)
    return k.zfill(width)


def phys_value(v, t):
    w = v.get('wave')
    if w:
        lo, hi, per = float(w.get('min', 0)), float(w.get('max', 0)), max(0.2, float(w.get('period', 5)))
        return lo + (hi - lo) * (0.5 - 0.5 * math.cos(2 * math.pi * t / per))
    return float(v.get('value', 0) or 0)


def encode_field(v, t):
    """Raw bytes of one value description at time t."""
    if 'hex' in v:
        return hexb(v['hex'])
    n = int(v.get('bytes', 1))
    scale = float(v.get('scale', 1) or 1)
    raw = int(round((phys_value(v, t) - float(v.get('offset', 0) or 0)) / scale))
    if v.get('signed'):
        lo, hi = -(1 << (8 * n - 1)), (1 << (8 * n - 1)) - 1
    else:
        lo, hi = 0, (1 << (8 * n)) - 1
    raw = max(lo, min(hi, raw))
    if v.get('mask') is not None: raw &= int(v['mask'])
    return (raw & ((1 << (8 * n)) - 1)).to_bytes(n, 'little' if v.get('little') else 'big')


def encode_value(v, t):
    if 'fields' in v:
        size = int(v.get('length') or max(int(f.get('pos', 0)) + int(f.get('bytes', 1)) for f in v['fields']))
        fill = int(v.get('fill', 0))
        if not 0 <= fill <= 255:
            raise ValueError('record fill must be a byte (0..255)')
        buf = bytearray([fill]) * size
        for f in v['fields']:
            b = encode_field(f, t); p = int(f.get('pos', 0))
            buf[p:p + len(b)] = b
        return bytes(buf[:size])
    return encode_field(v, t)


def describe(v, t):
    """'101.3 kPa' style text for the log (first field of a record)."""
    if 'hex' in v: return 'hex ' + hexb(v['hex']).hex().upper()
    if 'fields' in v: return '%d fields' % len(v['fields'])
    x = phys_value(v, t)
    txt = ('%.3f' % x).rstrip('0').rstrip('.')
    return (txt if txt not in ('-0', '') else '0') + ((' ' + v['unit']) if v.get('unit') else '')


def isotp_frames(addr, payload):
    """BMW extended-addressing ISO-TP frames (first byte = target address) for the CAN monitor."""
    if len(payload) <= 6:
        return [bytes([addr, len(payload)]) + payload]
    out = [bytes([addr, 0x10 | (len(payload) >> 8 & 0xF), len(payload) & 0xFF]) + payload[:5]]
    sn, i = 1, 5
    while i < len(payload):
        out.append(bytes([addr, 0x20 | (sn & 0xF)]) + payload[i:i + 6]); sn += 1; i += 6
    return out


# ---------------------------------------------------------------------------------------------------------- emulator
class UdsEmulator(object):
    def __init__(self, path, can=None, log_path=None):
        self.path, self.can, self.log_path = path, can, log_path
        self._lock = threading.RLock()
        self._t0 = time.monotonic()
        self._ring = collections.deque(maxlen=600)
        self._seq = 0
        self._cleared = set()
        self.cfg = self.load()
        self.stats = {'requests': 0, 'positive': 0, 'negative': 0, 'silent': 0}

    # --- configuration ---------------------------------------------------------------------------------------------
    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = default_config()
        return validate(cfg)

    def config(self):
        with self._lock:
            return copy.deepcopy(self.cfg)

    def save(self, cfg):
        cfg = validate(cfg)
        with self._lock:
            self.cfg = cfg
            self._cleared.clear()
        save_config(self.path, cfg)
        return cfg

    def set_value(self, ecu, kind, key, value, field=None):
        """Changes "value" of one entry (or of one field of a record) and drops its sweep."""
        with self._lock:
            cfg = copy.deepcopy(self.cfg)
            e = cfg['ecus'][norm_key(ecu, 2)][kind][norm_key(key, 4 if kind == 'dids' else 2)]
            if field is not None: e = e['fields'][int(field)]
            e.pop('wave', None); e.pop('hex', None); e['value'] = float(value)
        return self.save(cfg)

    # --- requests ----------------------------------------------------------------------------------------------------
    def now(self):
        return time.monotonic() - self._t0

    def handle(self, src, tgt, req):
        """Reply bytes for one UDS request, or None for no reply (the tester times out)."""
        req = bytes(req)
        with self._lock:
            cfg, t = self.cfg, self.now()
            ecu = cfg['ecus'].get('%02X' % tgt)
            resp, note = self._answer(cfg, ecu, tgt, req, t)
            self.stats['requests'] += 1
            self.stats['silent' if resp is None else 'negative' if resp[:1] == b'\x7f' else 'positive'] += 1
            self._seq += 1
            item = {'seq': self._seq, 't': round(t, 3), 'src': '%02X' % src, 'ecu': '%02X' % tgt,
                    'ecu_name': (ecu or {}).get('name', ''), 'req': req.hex().upper(),
                    'resp': None if resp is None else resp.hex().upper(), 'note': note}
            self._ring.append(item)
        self._log(item)
        self._to_can(tgt, req, resp, note)
        return resp

    def _answer(self, cfg, ecu, tgt, req, t):
        if not req: return None, 'empty request'
        sid = req[0]
        if ecu is None:
            return (bytes([0x7F, sid, 0x11]), 'no ECU %02X configured' % tgt) if cfg.get('unknown_ecu') == 'nrc' else (None, 'no ECU %02X configured (no reply)' % tgt)
        for rule in ecu.get('raw') or []:
            pat = ''.join(str(rule.get('request', '')).split()).upper()
            if len(pat) == 2 * len(req) and all(pat[i:i + 2] == '..' or int(pat[i:i + 2], 16) == req[i // 2] for i in range(0, len(pat), 2)):
                r = rule.get('response')
                return (None, 'raw rule: no reply') if r in (None, '') else (hexb(r), rule.get('name') or 'raw rule')
        if sid == 0x22:
            if len(req) < 3 or (len(req) - 1) % 2: return bytes([0x7F, 0x22, 0x13]), 'bad length'
            out, notes = bytearray([0x62]), []
            for i in range(1, len(req), 2):
                did = '%02X%02X' % (req[i], req[i + 1])
                v = (ecu.get('dids') or {}).get(did)
                if v is None: continue
                out += req[i:i + 2] + encode_value(v, t)
                notes.append('%s %s = %s' % (did, v.get('name', ''), describe(v, t)))
            if len(out) == 1: return bytes([0x7F, 0x22, 0x31]), 'DID %s not configured' % req[1:].hex().upper()
            return bytes(out[:MAX_REPLY]), '; '.join(notes)
        if sid == 0x01:
            if len(req) < 2: return bytes([0x7F, 0x01, 0x13]), 'bad length'
            out, notes = bytearray([0x41]), []
            for pid in req[1:7]:
                if pid in (0x00, 0x20, 0x40, 0x60):             # supported-PID bitmaps
                    bits = 0
                    known_pids = [int(k, 16) for k in (ecu.get('obd') or {})]
                    for p in known_pids:
                        if pid < p <= pid + 0x20: bits |= 1 << (32 - (p - pid))
                    # The final bit advertises another bitmap page. A PID in
                    # 0x41..0x60 requires 01 00 -> 01 20 -> 01 40 discovery.
                    if any(p > pid + 0x20 for p in known_pids): bits |= 1
                    out += bytes([pid]) + bits.to_bytes(4, 'big'); continue
                v = (ecu.get('obd') or {}).get('%02X' % pid)
                if v is None: continue
                out += bytes([pid]) + encode_value(v, t)
                notes.append('PID %02X %s = %s' % (pid, v.get('name', ''), describe(v, t)))
            if len(out) == 1: return bytes([0x7F, 0x01, 0x12]), 'PID %s not configured' % req[1:].hex().upper()
            return bytes(out), '; '.join(notes) or 'supported PIDs'
        if sid == 0x09 and req[1:2] == b'\x02':
            vin = str(cfg.get('vin') or 'WBA00000000000000')[:17].ljust(17, '0').encode('ascii', 'replace')
            return b'\x49\x02\x01' + vin, 'VIN'
        if sid == 0x10 and len(req) >= 2:
            return bytes([0x50, req[1], 0x00, 0x32, 0x01, 0xF4]), 'session %02X' % req[1]
        if sid == 0x3E:
            if len(req) >= 2 and req[1] & 0x80: return None, 'tester present (no reply requested)'
            return bytes([0x7E, 0x00]), 'tester present'
        if sid == 0x11 and len(req) >= 2:
            return bytes([0x51, req[1]]), 'reset %02X' % req[1]
        if sid == 0x19 and len(req) >= 3 and req[1] == 0x02:
            out = bytearray([0x59, 0x02, 0xFF])
            dtcs = [] if tgt in self._cleared else (ecu.get('dtcs') or [])
            for d in dtcs:
                st = int(str(d.get('status', '2F')), 16)
                if st & req[2]: out += hexb(d['code'])[:3].rjust(3, b'\0') + bytes([st])
            return bytes(out), '%d DTC(s)' % ((len(out) - 3) // 4)
        if sid == 0x14:
            self._cleared.add(tgt)
            return b'\x54', 'DTCs cleared'
        if sid == 0x27 and len(req) >= 2:
            return (bytes([0x67, req[1], 0x12, 0x34, 0x56, 0x78]), 'seed') if req[1] & 1 else (bytes([0x67, req[1]]), 'key accepted')
        if sid == 0x2F and len(req) >= 2:                  # also the 3-byte MHD map switch 2F 01 <slot>
            return bytes([0x6F]) + req[1:], 'IO control echo'
        if sid == 0x31 and len(req) >= 4:
            return bytes([0x71]) + req[1:4], 'routine %s' % req[2:4].hex().upper()
        return bytes([0x7F, sid, 0x11]), 'service %02X not supported' % sid

    # --- output ------------------------------------------------------------------------------------------------------
    def transactions(self, since=0, limit=200):
        with self._lock:
            items = [x for x in self._ring if x['seq'] > int(since or 0)][-int(limit):]
            return {'seq': self._seq, 'items': items, 'stats': dict(self.stats)}

    def _log(self, it):
        if not self.log_path: return
        svc = SERVICES.get(int(it['req'][:2] or '0', 16), '')
        line = '%9.3f  %s(%s) <- %s  %s  =>  %s   %s\n' % (it['t'], it['ecu'], it['ecu_name'] or '?', it['src'], it['req'],
                                                      it['resp'] if it['resp'] is not None else '(no reply)', (svc + ': ' if svc else '') + (it['note'] or ''))
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(line)
        except OSError:
            pass

    def _to_can(self, tgt, req, resp, note):
        can = self.can
        if not can or not hasattr(can, 'log_only'): return
        try:
            short = (note or '').split(';')[0][:60]
            for i, fr in enumerate(isotp_frames(tgt, req)):
                can.log_only(CAN_TESTER_ID, fr, 'UDS -> %02X %s' % (tgt, SERVICES.get(req[0], '')) if i == 0 else None, 'req')
            if resp is not None:
                frames = isotp_frames(0xF1, resp)      # on the CAN side the tester is F1
                if len(frames) > 1: can.log_only(CAN_TESTER_ID, bytes([tgt, 0x30, 0x00, 0x00]), 'flow control', 'req')
                for i, fr in enumerate(frames):
                    can.log_only(0x600 + tgt, fr, ('UDS <- %02X %s' % (tgt, short)) if i == 0 else None, 'resp')
        except Exception:
            pass


def validate(cfg):
    """Normalises keys (upper-case hex) and checks every value can be encoded. Raises ValueError with the bad entry."""
    if not isinstance(cfg, dict): raise ValueError('UDS configuration must be a JSON object')
    out = {'gateway_ips': [], 'unknown_ecu': 'nrc' if cfg.get('unknown_ecu') == 'nrc' else 'silent', 'ecus': {}}
    if cfg.get('vin'): out['vin'] = str(cfg['vin'])
    for ip in cfg.get('gateway_ips') or [DEFAULT_IP]:
        parts = str(ip).strip().split('.')
        if len(parts) != 4 or not all(p.isdigit() and int(p) < 256 for p in parts):
            raise ValueError('gateway address %r is not an IPv4 address' % ip)
        out['gateway_ips'].append('.'.join(str(int(p)) for p in parts))
    for addr, ecu in (cfg.get('ecus') or {}).items():
        try:
            a = norm_key(addr, 2)
        except ValueError:
            raise ValueError('ECU address %r is not hex' % addr)
        if len(a) != 2: raise ValueError('ECU address %r must be one byte' % addr)
        e = {'name': str((ecu or {}).get('name', ''))}
        for kind, width in (('dids', 4), ('obd', 2)):
            items = {}
            for k, v in ((ecu or {}).get(kind) or {}).items():
                try:
                    kk = norm_key(k, width)
                except ValueError:
                    raise ValueError('ECU %s: %s key %r is not hex' % (a, kind, k))
                if len(kk) != width: raise ValueError('ECU %s: %s key %r is too long' % (a, kind, k))
                if not isinstance(v, dict): raise ValueError('ECU %s %s %s: value must be an object' % (a, kind, kk))
                if kind == 'dids' and kk == '4000':
                    v = upgrade_legacy_s63tu_4000(v)
                try:
                    encode_value(v, 0.0)
                except Exception as ex:
                    raise ValueError('ECU %s %s %s: %s' % (a, kind, kk, ex))
                items[kk] = v
            if items: e[kind] = items
        for i, r in enumerate((ecu or {}).get('raw') or []):
            try:
                pat = ''.join(str(r.get('request', '')).split())
                if not pat or len(pat) % 2: raise ValueError('request must be whole bytes')
                for j in range(0, len(pat), 2):
                    if pat[j:j + 2] != '..': int(pat[j:j + 2], 16)
                if r.get('response'): hexb(r['response'])
            except Exception as ex:
                raise ValueError('ECU %s raw rule %d: %s' % (a, i + 1, ex))
            e.setdefault('raw', []).append(r)
        if (ecu or {}).get('dtcs'): e['dtcs'] = ecu['dtcs']
        out['ecus'][a] = e
    return out


def config_path(env_dir):
    return os.path.join(env_dir, 'uds.json')


def load_config(env_dir):
    try:
        with open(config_path(env_dir), encoding='utf-8') as f:
            return validate(json.load(f))
    except (OSError, ValueError):
        return default_config()


def save_config(path, cfg):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, path)


def gateway_ips(env_dir, overlay_files=()):
    """Addresses the guest gateway answers on: the configured ones plus every gateway-ip.txt shipped in the overlay."""
    ips = list(load_config(env_dir).get('gateway_ips') or [DEFAULT_IP])
    for rel, p in overlay_files:
        if os.path.basename(rel).lower() != 'gateway-ip.txt': continue
        try:
            with open(p, encoding='ascii', errors='replace') as f:
                ip = f.read().strip()
            validate({'gateway_ips': [ip]})
        except (OSError, ValueError):
            continue
        if ip not in ips: ips.append(ip)
    return ips


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='UDS emulator preset configuration helper')
    parser.add_argument('--merge-preset', choices=list(PRESETS),
                        help='Add/update the named preset in a uds.json file')
    parser.add_argument('--config', help='Path to existing uds.json')
    parser.add_argument('--output', help='Output file; defaults to --config')
    parser.add_argument('--only-missing', action='store_true',
                        help='Keep existing DID/PID definitions instead of updating them')
    args = parser.parse_args()
    if not args.merge_preset or not args.config:
        parser.error('specify --merge-preset and --config')
    try:
        with open(args.config, encoding='utf-8') as f:
            data = validate(json.load(f))
    except FileNotFoundError:
        data = default_config()
    except (ValueError, OSError) as exc:
        parser.error('unable to read configuration: %s' % exc)
    if args.only_missing:
        preset = PRESETS[args.merge_preset]
        for addr, ecu in preset['ecus'].items():
            dst = data.setdefault('ecus', {}).setdefault(addr, {'name': ecu.get('name','')})
            if not dst.get('name'): dst['name'] = ecu.get('name', '')
            for kind in ('dids', 'obd'):
                for key, v in ecu.get(kind, {}).items():
                    dst.setdefault(kind, {}).setdefault(key, copy.deepcopy(v))
    else:
        merge_preset(data, args.merge_preset)
    dst = args.output or args.config
    # Avoid silently destroying a prior working simulator configuration.
    if os.path.isfile(dst):
        import shutil
        shutil.copy2(dst, dst + '.bak')
    save_config(dst, validate(data))
    print('Merged %s into %s' % (args.merge_preset, dst))
