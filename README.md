# esphome-myanywair

ESPHome component for the **Sensibo anywAiR / Fujitsu myanywAiR** air-conditioner
controller — a local replacement for the Sensibo cloud bridge that speaks the
Fujitsu indoor unit's UART protocol directly.

This repo started life as the ESPHome "custom components" example template; the
original template README is kept at
[`docs/custom-component-template.md`](docs/custom-component-template.md) and the
`custom_components/empty_*` folders are the untouched template examples. The
useful content is:

| Path | What it is |
|---|---|
| `custom_components/fujitsu_ac/` | The working ESPHome component (climate, swing selects, light switch, AC sensor) |
| `anywair-generic.yaml` | Example config for your own ESP32 wired to the indoor unit |
| `anywair-stock-board.yaml` | Example config for reflashing the stock Sensibo board |
| `docs/PROTOCOL.md` | The UART wire protocol (frames, checksums, registers) |
| `docs/firmware-notes.md` | Reverse-engineering notes from the stock firmware dump |
| `docs/bench-guide.md` | How to read/flash the ESP32-C3 on the stock board |
| `tools/` | Capture decoding + protocol codec scripts |
| `reference/` | Photos/pinouts and the sigrok `.sr` UART captures |

## Status

- Wire protocol: **fully documented and validated** against fresh logic captures.
- Stock firmware: **dumped and decompiled**; register meanings confirmed from the
  manufacturer's own `fuji.c`.
- ESPHome component: **compiles cleanly** for ESP32 (Arduino) and ESP32-C3
  (ESP-IDF) with ESPHome 2026.10.
- **Validated on real hardware** (stock Sensibo board, Fujitsu indoor unit,
  Nov 2026): polls are answered, `power`/`mode`/`target temperature`/`fan`/AC
  temperature all read correctly, and setting the target from Home Assistant is
  applied by the unit and reported back.

### Findings from the live unit

- **AC temperature `10:33` is °F** (value ÷ 100). Observed `7175` → 71.75 °F
  (≈ 22.1 °C) with a 22 °C setpoint. The unit reports in whatever unit its
  remote/display is configured for.
- **Vertical/horizontal swing return `0xFFFF`** on this indoor unit — it does
  not expose louvre positions over this protocol. The swing selects stay
  unknown rather than showing a bogus value.
- The stock board's on-board transistor stage means **no software UART
  inversion** is needed there (confirmed: plain 9600 8N1 on GPIO5/GPIO4 works).
- The unit also emits unsolicited type-`0x02`, 1-byte frames; the component
  ignores them.

## The hardware

The Sensibo anywAiR (a.k.a. "myanywAiR Next") is a small ESP32-C3-MINI-1 board
that plugs into the Fujitsu indoor unit's service connector (J1, the "USB-A"
looking plug). It bridges that indoor unit to Sensibo's cloud.

- **J1 connector** — **not USB**. Pin 1 = +12 V, pin 4 = GND, pins 2 & 3 are the
  two UART data lines. Never plug it into a PC.
- **Aircon side**: ~5 V logic, two full-duplex data lines, **9600 baud 8N1**,
  **idle LOW (inverted UART)** as seen at the connector.
- **On-board level shifting**: two discrete transistor stages (Q1/Q2) that also
  invert, so the ESP32-C3's own UART runs standard polarity.
- **Firmware-confirmed pins**: the stock app configures **UART1, TX = GPIO5,
  RX = GPIO4** (see `docs/firmware-notes.md`).
- Additional on-board sensor: an **HDC1080** temperature/humidity sensor on I2C
  (pins not yet identified).

## Protocol in one table

Frames are `sync(03/02 00 00 00) + len + payload + checksum16(BE)`, where the
checksum is `0xFFFF − sum(every preceding byte)`.

| Register | Meaning | Values |
|---|---|---|
| `10:00` | power | `0001` = on, `0000` = off |
| `10:01` | mode | `0`=auto, `1`=cool, `2`=dry, `3`=fan, `4`=heat |
| `10:02` | setpoint | °C × 10 (big-endian) |
| `10:03` | fan | `0`=auto, `2`=quiet, `5`=low, `8`=medium, `0xb`=high |
| `10:10` (+`10:11`) | vertical swing | `0`=stopped, `1`=fixedTop, `2`=fixedMiddleTop, `3`=fixedMiddleBottom, `4`=fixedBottom |
| `10:22` (+`10:23`) | horizontal swing | `0`=stopped, `1`=fixedLeft, `2`=fixedCenterLeft, `3`=fixedCenter, `4`=fixedCenterRight, `5`=fixedRight |
| `10:b6` | panel light | `0`=off, `1`=on |
| `10:31` | status | raw |
| `10:33` | AC-side temperature | value ÷ 100 (unit unconfirmed) |

Poll (type `0x03`) asks for the stock list of 12 registers; the unit answers
with a type `0x03` frame containing `52 06 ff ff` followed by four-byte register
entries. Writes (type `0x02`) set one register per frame; swing writes always
pair the position register with a zeroed marker register. The full details,
including the exact byte layouts and the checksum derivation, are in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Using the component

1. Copy `custom_components/fujitsu_ac/` into your ESPHome config directory (or
   point `external_components` at this repo as in the example YAMLs).
2. Copy `secrets.yaml.example` to `secrets.yaml` and set your WiFi credentials.
3. Use one of the example YAMLs as a starting point:

```yaml
external_components:
  - source:
      type: local
      path: custom_components

uart:
  tx_pin: GPIO5
  rx_pin: GPIO4
  baud_rate: 9600

fujitsu_ac:
  id: ac_hub
  update_interval: 5s

climate:
  - platform: fujitsu_ac
    name: "Air Conditioner"
```

### Entities

- `climate` — power, mode (auto/cool/dry/fan/heat), target temperature and fan
  speed.
- `select` ("Vertical Swing", "Horizontal Swing") — the fixed louvre positions.
  These are exposed as selects because ESPHome's climate swing modes only
  offer on/off-style values, not individual positions.
- `switch` — the AC panel light.
- `sensor` — the AC-reported temperature (`10:33`).

The hub polls every 5 s and publishes state; commands are queued and each waits
for the unit's reply (or a 600 ms timeout) before the next is sent.

## Wiring your own ESP32

**Option A — replicate the stock transistor stage (recommended).** Copy the
stock board's two-transistor level shifter (or just reuse the stock board), and
use plain (non-inverted) UART pins. This is exactly how the original hardware
works, 3.3 V on the ESP side and ~5 V on the aircon side.

**Option B — wire direct.** The aircon lines idle LOW, so enable inversion in
software, and protect the ESP's RX pin from the 5 V line with a divider
(e.g. 10 kΩ series + 20 kΩ to GND). Some indoor units may not accept 3.3 V as a
high on their receive line, in which case use option A.

```yaml
uart:
  tx_pin:
    number: GPIO16
    inverted: true
  rx_pin:
    number: GPIO17
    inverted: true
  baud_rate: 9600
```

## Flashing the stock board

The stock ESP32-C3-MINI-1 has flash encryption enabled, but Secure Boot is
disabled and UART download mode is available, so the board can be reflashed.
See [`docs/bench-guide.md`](docs/bench-guide.md) for pad identification and the
read-only backup procedure, and [`docs/firmware-notes.md`](docs/firmware-notes.md)
for how the original firmware was recovered (a temporary, RAM-only/encrypted
bootloader probe; the original flash sector was restored and verified
afterwards).

### ⚠️ The first flash must be encrypted

Because flash encryption is enabled, a **plaintext** serial write will not boot
(the ROM tries to decrypt it and sees garbage). ESPHome's normal
`esphome run`/`upload` over serial writes plaintext, so for the *first* flash
use esptool directly with `--encrypt`:

```bash
esphome compile anywair-stock-board.yaml
esptool --chip esp32c3 --port /dev/cu.usbserial-XXXX --baud 115200 \
  --before no-reset --after hard-reset \
  write-flash --encrypt --flash-mode dio --flash-freq 40m \
  0x0 .esphome/build/anywair-stock/build/firmware.factory.bin
```

(40 MHz matches the stock flash configuration; the chip is an XMC 4 MB part.)

After that first boot, **use OTA** for all updates — no serial or encryption
flags needed:

```bash
esphome upload anywair-stock-board.yaml --device anywair-stock.local
```

To go back to stock, write the original backup **without** `--encrypt`:

```bash
esptool --chip esp32c3 --port /dev/cu.usbserial-XXXX --baud 115200 \
  write-flash 0x0 stock-backup.bin
```

### Logging

On the ESP32-C3, ESPHome's logger defaults to **USB-Serial-JTAG**, so logs do
*not* appear on the UART0 pins the USB-UART adapter is attached to. Either read
logs over the network (`esphome logs …`) or set `logger: hardware_uart: UART0`
and reflash.

> ⚠️ Keep a backup of the original encrypted flash image. It is the only way
> back to stock firmware, and it contains your WiFi credentials and device keys
> — do not publish it.

## Tools

The `tools/` scripts decode the original logic captures in `reference/` and
implement the protocol codec:

```bash
python3 tools/decode_sr.py "reference/WithSensiboAttachedAdjustedSettingsInAPP.sr"
python3 tools/parse_frames.py "reference/WithSensiboAttachedAdjustedSettingsInAPP.sr"
python3 tools/fujitsu_codec.py       # self-test against frames from the capture
```

They require `numpy` (signals) — `uv run --with numpy python3 tools/decode_sr.py …`.

## TODO

- [ ] Validate the ESPHome port on real hardware (both the stock board and a
      scratch-built ESP32).
- [ ] Confirm the unit/meaning of `10:33` (exposed as °F).
- [ ] Identify the HDC1080 I2C pins on the stock board.
- [ ] Optional: expose `10:31` / `11:01` status values as diagnostic sensors.

## Safety notes

- **J1 is not USB.** Pin 1 carries 12 V.
- Power the board either from 12 V on J1 **or** 3.3 V on the J2 3V3 pad — never
  both.
- Never connect a USB-UART adapter's 3V3/5V output while the board is powered
  from 12 V.
