# Fujitsu anywAiR / Sensibo UART protocol

Reverse-engineered from logic captures (`withsensibo.sr`, 2 ch @ 12 MHz) of the
Sensibo anywAiR C3 board talking to a Fujitsu indoor unit while settings were
changed in the Sensibo app. All values below are **confirmed from the capture**
unless marked *(inferred)*.

## Physical / UART

| Property | Value |
|---|---|
| Baud | **9600** |
| Framing | **8N1** |
| **Polarity** | **INVERTED** (idle LOW) at J1 |
| Wires | **two** data lines (full-duplex), through Q1/Q2 level shifters to J1 |
| Levels | aircon side ~5 V, ESP side 3.3 V |

**Firmware-confirmed (`Fuji_init`):** the stock ESP32-C3 uses **UART1 with
TX = GPIO5, RX = GPIO4**, 9600 8N1, and **no software inversion**. The
inverted idle-low waveform at J1 comes from the board's Q1/Q2 single-transistor
level shifters, not the UART. Replicate the transistor stage → plain UART;
bypass it with non-inverting level shifters → enable UART inversion in software.

> The inverted polarity is why a plain FTDI/CP2102 reads nothing — they can't
> decode inverted UART. An ESP32 UART can (`invert: true` in ESPHome); a logic
> analyzer captures raw and you invert in software.

J1 "USB-A" connector: **pin 1 = +12 V, pin 4 = GND, pins 2 & 3 = the two UART
lines** (one idles ~5 V, one ~0 V). It is NOT real USB — never plug into a PC.

## Frame format

```
03 00 00 00   <len>  [01]   52 06   [ff ff]   <register entries...>   <csum_hi> <csum_lo>
└─ sync ────┘  len   type?  msg-id   pad       TLVs                    one's-complement
```

- **Byte 0 = message type**: `03` = poll / response (read), `02` = **write command**.
- `00 00 00` = rest of the 4-byte sync/header.
- `<len>` = payload length (`0x1a` poll, `0x35` response, `0x04` write).
- `52 06` = message/opcode id (constant in all observed frames).
- Response frames carry an extra `01` and a leading `ff ff` before the entries.
- **Register entry** = `tag addr [hi lo]`: tag `10` or `11`, 1-byte address, and in
  responses/writes a **2-byte big-endian value**. Poll frames list `tag addr` only.

### Checksum (confirmed, verified on all frames + rebuilt exactly)

```
csum16 = 0xFFFF - (sum of every frame byte before the 2 csum bytes)   # big-endian
```
Equivalently: `sum16(body) + csum16 == 0xFFFF`. See `fujitsu_codec.py`.

## Registers (from the response, type 03)

| Reg | Meaning | Wire values (firmware-confirmed) |
|---|---|---|
| `10:00` | **power** | `0001` = on, `0000` = off |
| `10:01` | **mode** | `0000`=auto, `0001`=cool, `0002`=dry, `0003`=fan, `0004`=heat (cycled `01→04→03→02→00`) |
| `10:02` | **setpoint** | `00f0`=24.0 °C, `00e6`=23.0, `00fa`=25.0 → **value ÷ 10 = °C**; `ffff` = off/invalid |
| `10:03` | **fan** | `0000`=auto, `0002`=quiet, `0005`=low, `0008`=medium, `000b`=high |
| `10:10` | **vertical swing** | `0000`=stopped, `0001`=fixedTop, `0002`=fixedMiddleTop, `0003`=fixedMiddleBottom, `0004`=fixedBottom |
| `10:11` | v-swing range marker | `0001` = rangeFull |
| `10:22` | **horizontal swing** | `0000`=stopped, `0001`=fixedLeft, `0002`=fixedCenterLeft, `0003`=fixedCenter, `0004`=fixedCenterRight, `0005`=fixedRight |
| `10:23` | h-swing range marker | `0001` = rangeFull |
| `10:b6` | **light** | `0000`=off, `0001`=on |
| `10:31` | status | `0000` (raw passthrough) |
| `10:33` | AC room temperature, **°F** | value ÷ 100 — live-validated: `1c07`→71.75 °F with a 22 °C setpoint |
| `11:01` | supported-modes status | `0000` |

> **Live-hardware notes (Nov 2026, Fujitsu indoor unit):**
>
> - `10:33` reports **Fahrenheit** on this unit (value ÷ 100; `7175` → 71.75 °F
>   ≈ 22.08 °C against a 22 °C setpoint).
> - Swing registers `10:10`/`10:22` return **`ffff`** — this indoor unit has no
>   louvre positions over this protocol. `10:b6` (panel light) is `ffff` too.
> - Fan **`0x0002` (quiet) is not supported**: it is accepted but the unit
>   reports `0x0005` (low) back. Auto `0x0000`, low `0x0005`, medium `0x0008`
>   and high `0x000b` all work.
> - `10:31` and `11:01` both read `0000` on this unit.
> - The unit also sends unsolicited type-`0x02` frames with a 1-byte payload;
>   the component ignores them.

> All mappings in this table are now confirmed from the recovered firmware's
> `fuji.c` write/read handlers, not just the capture. Firmware details:
> [`firmware-notes.md`](firmware-notes.md).

## Writing a setting (type 02)

A write is `02 00 00 00 04 <tag> <addr> <hi> <lo> <csum16>`. Captured example — the
app setting 23.0 °C produced exactly:

```
02 00 00 00 04 10 02 00 e6 ff 01     # write reg 10:02 = 0x00e6 (23.0 °C)
```

`fujitsu_codec.build_write(addr, value)` reproduces this byte-for-byte. Examples it
generates (all checksum-valid):

```
set 22.0 C : 02 00 00 00 04 10 02 00 dc ff 0b
set 25.0 C : 02 00 00 00 04 10 02 00 fa fe ed
set mode 1 : 02 00 00 00 04 10 01 00 01 ff e7
```

## What this enables

We now have enough to **both read state and send commands** without Sensibo's
cloud. Two ways to use it:

1. **Separate ESP32 + ESPHome** (lowest risk): wire any ESP32's UART to the
   aircon's two data lines through a level shifter, `uart: baud_rate: 9600,
   invert on`, and implement this frame codec as an external component /
   `climate` platform. Leaves this board untouched as a reference.
2. **Reflash this board's ESP32-C3** with ESPHome: reuses the enclosure, 12 V
   supply and temp/humidity sensor. Needs the UART GPIO (trace Q1/Q2 → module)
   and a working flash path (download mode via the rear pads; write-only, so a
   locked read doesn't necessarily block it).

Either way the protocol work — the hard part — is done.

## Files

- `tools/fujitsu_codec.py` — decode/verify/build frames (validated against the capture)
- `tools/decode_sr.py` — measure baud + polarity and dump a `.sr` UART line
- `tools/parse_frames.py` — split frames, track which registers change
- `tools/checksum_crack.py` — how the checksum was recovered
- captures/pinouts: in the `reference/` folder of this repository
