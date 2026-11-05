# Firmware analysis — Sensibo anywAiR "Fuji" module (`ota_0.bin`)

App: `Sensibo-esp32` `e91f184`, ESP-IDF v5.1.1, built Feb 18 2025.
Recovered from the encrypted flash dump of the stock board (embedded checksum +
SHA-256 valid). Addresses are disassembly addresses from the reconstructed
image; the raw image and dump are not included here because they contain the
device's WiFi credentials and keys.

All addresses below are static-analysis observations. Wire behavior is
cross-confirmed against the logic captures documented in
[`PROTOCOL.md`](PROTOCOL.md).

## The AC driver is `./Src/fuji.c`

Tag string `FUJITSU` at `0x3c137858`, file-name string `./Src/fuji.c` at
`0x3c137a5c`. Function tags: `Fuji_init` (`0x3c1381f0`),
`Fuji_recvCommand` (`0x3c138200`), `Fuji_loop`.

| Function | Address |
|---|---|
| Response parser (`Fuji_recvCommand` body) | `0x4200a29c` |
| Frame checksum verify | `0x4200a330..0x4200a3be` |
| Type-03 poll frame builder | `0x42009cd2` |
| Type-02 write frame builder | `0x42009d64` |
| Send + wait-for-response | `0x4200a440` |
| State-entry dispatch (read side) | `0x42009e16` (dispatch `0x42009ec0..`) |
| `Fuji_init` (UART setup) | `0x4200ad4c` |
| JSON enum ↔ name maps | `0x4200d7e2..0x4200dbe8` |
| Poll register table (in DROM) | file offset `0x822c` |

## UART configuration (`Fuji_init` @ `0x4200ad4c`)

- `uart_param_config(UART_NUM_1, ...)`: **9600 baud, 8N1, no flow control**
  — the built `uart_config_t` on the stack is
  `{9600, .data_bits=3 (8-bit), .parity=0, .stop_bits=1, .flow_ctrl=0, .source_clk=4}`.
- `uart_set_pin(1, tx=5, rx=4, rts=-1, cts=-1)` @ `0x4200adb6`
  → **TX = GPIO5, RX = GPIO4** (matches the assert string
  `uart_set_pin(uart_num, FUJI_TX_PIN, FUJI_RX_PIN, -1, -1)`).
- `uart_driver_install(1, 1024, 1024, 1024, &uart_queue, 0)`.
- **No software UART inversion anywhere in `fuji.c`.** The idle-low/inverted
  waveform seen at the J1 aircon connector is produced by the board's
  Q1/Q2 discrete level-shifter stage (single-transistor inverters), not by
  the ESP32 UART. On the chip side the UART is standard polarity.

## Frame layer (confirmed in the builders)

### Checksum (`0x4200a330`)

```
sum = 0
for each byte before the 2 checksum bytes: sum = (sum + byte) & 0xFFFF
csum = 0xFFFF - sum          # stored big-endian as the last 2 bytes
```
The receive path recomputes exactly this and rejects mismatched frames
("Error frame check is not valid, excepted: %02x%02x, got: %x").

### Type-03 poll (`0x42009cd2`)

- `frame[0]=0x03`, `frame[1..3]=0x000000`
- `frame[4] = count * 2`
- payload = each 16-bit entry written big-endian (the firmware stores the
  table little-endian and byteswaps on output)
- checksum

The firmware's poll table (file offset `0x822c`, byte-exact):

```
0x5206, 0x1000, 0x1001, 0x1002, 0x1003, 0x1010, 0x1011,
0x1022, 0x1023, 0x1033, 0x10b6, 0x1101, 0x1031
```

i.e. on the wire: `03 00 00 00 1a 52 06 10 00 10 01 10 02 10 03 10 10
10 11 10 22 10 23 10 33 10 b6 11 01 10 31 <csum>` — identical to the
captured poll frame.

- `0x5206` is the message id and is sent as if it were the first list entry.
- `0x10NN` = register tag 0x10, address 0xNN; `0x1101` = tag 0x11.

### Type-02 write (`0x42009d64`)

- `frame[0]=0x02`, `frame[1..3]=0x000000`
- `frame[4] = count * 4`
- each entry is `(addr16, value16)` packed little-endian in RAM and written
  byteswapped, producing on the wire: `<tag> <addr> <hi> <lo>` (big-endian
  value)
- checksum

For one register: `02 00 00 00 04 10 <addr> <hi> <lo> <csum_hi> <csum_lo>`
— byte-identical to the captured setpoint write.

Write handling also:
- accepts `frame[5]==0` responses (`0x4200a3be`),
- treats `frame[5]==2` as an ACK path (`0x4200a414`), otherwise
  "Received unknown response result",
- logs "Received NACK response result",
- sleeps ~20 ticks between poll cycles (`0x4200a4d2`).

### Type-03 response parsing (`0x42009e16`, dispatch `0x42009ec0`)

`frame[4]=0x35`, `frame[5]=0x01`, then `52 06 ff ff`, then 12 entries of
`<tag> <addr> <hi> <lo>` = 53 payload bytes, then checksum. Entries are
dispatched by `(addr<<8)|tag`:

| Key | Register | Handler |
|---|---|---|
| `0x0310` | 10:03 | fan |
| `0x0110` | 10:01 | mode |
| `0x0210` | 10:02 | setpoint |
| `0x0010` | 10:00 | power |
| `0x1010` | 10:10 | vertical swing |
| `0x1110` | 10:11 | vertical swing marker |
| `0x2210` | 10:22 | vertical swing auto |
| `0x2310` | 10:23 | horizontal swing |
| `0x3110` | 10:31 | status |
| `0x3310` | 10:33 | sensor value |
| `0xb610` | 10:b6 | light |
| `0x1101` | 11:01 | supported-modes status |

## Register meanings and wire values

Values below are big-endian 16-bit as they appear on the wire, taken from
both the read-side dispatch and the write-side mapping functions. Names
come from the firmware's own JSON serialization (`fanLevel`, `mode`,
`light`, `swing`, `horizontalSwing`).

### 10:00 — power (`0x4200a002`)
- `0x0001` = on, `0x0000` = off
- on-wire check is `value_le == 0x0100`

### 10:01 — mode (`0x4200a010` read, `0x4200a5ac` write)
Firmware enum → wire: `cool(0)→1`, `heat(1)→4`, `fan(2)→3`,
`auto(3)→0`, `dry(4)→2`. So:

| Wire | Mode |
|---|---|
| `0x0000` | auto |
| `0x0001` | cool |
| `0x0002` | dry |
| `0x0003` | fan |
| `0x0004` | heat |

This confirms the order inferred in `PROTOCOL.md` (the app cycles
1→4→3→2→0 = cool→heat→fan→dry→auto).

### 10:02 — setpoint (`0x4200a074` read, `0x4200a620` write)
- value = °C × 10, big-endian (constant `10.0f` at `0x3c138228` is the divisor)
- `0xFFFF` = invalid (logged "AC temperature = Invalid")
- captured `0x00f0` = 24.0 °C etc.

### 10:03 — fan (`0x4200a0e0` read, `0x4200a53c` write)
Firmware enum → wire: `auto(0)→0`, `high(1)→0x0b`, `medium(2)→0x08`,
`low(3)→0x05`, `quiet(4)→0x02`. So:

| Wire | Fan |
|---|---|
| `0x0000` | auto |
| `0x0002` | quiet |
| `0x0005` | low |
| `0x0008` | medium |
| `0x000b` | high |

(The firmware also knows JSON names `medium_low`, `strong`, `medium_high`
for other products, but this driver only maps the five values above;
anything else logs "unsupported fan level".)

### 10:10 / 10:11 — vertical swing (`0x4200a13c` read, `0x4200a662` write)
Write sends two entries: `(10:10, value)` and `(10:11, 0x0000)`.

Firmware enum → wire: `stopped(0)→0`, `fixedTop(1)→1`,
`fixedMiddleTop(2)→2`, `fixedMiddleBottom(4)→3`, `fixedBottom(5)→4`.

| Wire (10:10) | Swing |
|---|---|
| `0x0000` | stopped |
| `0x0001` | fixedTop |
| `0x0002` | fixedMiddleTop |
| `0x0003` | fixedMiddleBottom |
| `0x0004` | fixedBottom |

- Read side: `10:11 == 0x0001` marks the "rangeFull" condition
  (enum 9 in firmware).
- Firmware JSON names for enum 3 (`fixedMiddle`), 6/7 (`rangeTop`/
  `rangeMiddle`) and 9 (`rangeFull`) exist, but this AC driver maps only
  the five wire values above plus the special rangeFull handling.

### 10:22 / 10:23 — horizontal swing (`0x4200a1d2`/`0x4200a22a` read, `0x4200a6fc` write)
Write sends `(10:22, value)` and `(10:23, 0x0000)`.

Firmware enum → wire: `stopped(0)→0`, `fixedLeft(1)→1`,
`fixedCenterLeft(2)→2`, `fixedCenter(6)→3`, `fixedCenterRight(3)→4`,
`fixedRight(4)→5`; enum 10 (`rangeFull`) reuses the cached current value.

| Wire (10:22) | Swing |
|---|---|
| `0x0000` | stopped |
| `0x0001` | fixedLeft |
| `0x0002` | fixedCenterLeft |
| `0x0003` | fixedCenter |
| `0x0004` | fixedCenterRight |
| `0x0005` | fixedRight |

- Read side: `10:23 == 0x0001` marks `rangeFull`.
- Other firmware names (`fixedLeftRight`, `fixedCenter`,
  `rangeCenter`, `rangeLeft`, `rangeRight`) are known to the JSON layer
  but not mapped by this write function.

### 10:b6 — light (`0x4200a248` read, `0x4200a7a0` write)
- `0x0000` = off (enum 0), `0x0001` = on (enum 2)
- firmware JSON names: `off`, `dim`, `on`; only `off`/`on` have wire values
  ("unsupported light" otherwise)

### 10:31 — status
Raw passthrough (`0x42009f6a`: stored unconverted). Observed `0x0000`.

### 10:33 — AC-side sensor (`0x42009fa8`)
- `0xFFFF` = invalid
- values `> 3` are divided by **100.0** (double `100.0` at
  `0x3c1366a8`); values 0–3 are stored raw
- captured `0x1ce8` → `74.0`. Most consistent interpretation is the AC
  room temperature in °F (74 °F ≈ 23.3 °C with a 24 °C setpoint); treat
  the unit as unconfirmed until compared against the app.

## Supported-mode detection (`0x4200ac40..0x4200ad10`)

The driver writes each mode to 10:01, reads back the response, and records
which values the unit accepted into a `supported_modes` bitmask stored in
NVS (`KEY_SUPPORTED_MODES`, default `0x1F` = all five). Repeated failed
detection logs "Error while detecting supported modes".

## ESPHome implications

- The wire protocol is exactly what `tools/fujitsu_codec.py` already
  implements — the capture-derived codec needed no changes.
- UART: 9600 8N1. On the stock board, TX=GPIO5, RX=GPIO4, and the
  inversion seen at J1 comes from the Q1/Q2 transistor stage. Replicate
  that stage → plain UART; bypass it with non-inverting level shifting →
  enable UART inversion in software.
- Poll the 12-entry list above, then parse the type-03 response entries.
- Writes are single-register type-02 frames (swing writes are two entries).
- Aircon-side levels are ~5 V; ESP32 is 3.3 V.
