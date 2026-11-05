# Sensibo anywAiR C3 — serial dump bench guide

Goal: get a **read-only backup** of the firmware and find out whether the chip is
locked, without damaging the board. Everything here only *reads*. The only write
step (flashing your own firmware) comes later, and only if the dump is plaintext.

Chip: **ESP32-C3-MINI-1** — a RISC-V SoC with **4 MB flash inside the module**.
There is no separate flash chip to clip onto; the backup goes through the chip's
own ROM bootloader over UART (or its native USB).

---

## 0. You need

- 3.3 V USB-UART adapter (CP2102 / CH340 / FTDI). **Must be 3.3 V logic**, not 5 V.
- Multimeter with continuity (beep) mode.
- Fine jumper wires / probes; ideally a 12 V bench supply.
- Mac with the scripts in this folder. No installs needed — they use `uvx`.

## ⚠️ Safety

- The "USB-A" port (J1) carries **12 V on pin 1**. Never plug it into a PC or a
  real USB device, and never plug a USB device into it.
- Power the board **either** from 12 V on J1 **or** from 3.3 V on the J2 3V3 pad —
  **never both at once.**
- Connect the UART adapter's **GND** always. Do **not** connect its 3V3/5V output
  if the board is already powered from 12 V — you'd back-feed the regulator.

---

## 1. Identify the pads (power OFF)

Board back (chip side) has **J2**, a 2×5 pad field numbered 1–10, plus **TP1/TP2**.
You're looking for six nets: **GND, 3V3, TX(GPIO21), RX(GPIO20), EN, IO9(boot)**.

Use continuity mode:

| Find | How |
|---|---|
| **GND** | Beeps to J1 pin 4 and to the metal USB shell. |
| **3V3** | Beeps to the output-side pad of the big silver `8R2` inductor / the cap beside it. Should read ~3.3 V once powered. |

Mark those two. The remaining J2 pads are the signal candidates (TX, RX, EN, IO9,
IO8, IO2, maybe USB D-/D+). Note which pads look pre-tinned — the factory used them.

## 2. Power it up

**Preferred:** 12 V supply → J1 pin 1 (+) and J1 pin 4 (GND). Current limit ~300 mA.
The onboard regulator then feeds the chip and survives Wi-Fi current spikes.

**Alternative:** regulated 3.3 V → J2 3V3 pad and GND, from a supply that can give
**≥500 mA**. (Most USB-UART 3V3 pins can't — the chip browns out when radio starts.)

## 3. Find TX (watch the boot log)

Adapter: **RX → candidate pad**, **GND → board GND**. TX not connected yet. Then:

```bash
cd tools   # this repo's helper scripts (dump.sh)
./dump.sh bootlog /dev/cu.usbserial-XXXX      # your adapter's port; ls /dev/cu.* to find it
```

Briefly short **EN** to GND (that's the reset) — or just power-cycle. The pad that
spits out readable text is **TX / GPIO21**. You'll see something like:

```
ESP-ROM:esp32c3-api1-20210207
...
boot:0xc (SPI_FAST_FLASH_BOOT)
```

Move RX from pad to pad until you get that. `Ctrl-C` to stop between tries.
(The log also hints at security — watch for `SECURE BOOT` / flash-encryption lines.)

## 4. Find RX

RX / GPIO20 is almost always the pad **physically next to TX**. Wire the adapter's
**TX → that pad**. You'll confirm it works in step 6.

## 5. Enter download mode

Hold **IO9 (GPIO9) at GND** while you pulse **EN** (reset). To find IO9: hold a
candidate at GND, tap EN, and watch `bootlog` — the right pad changes the log to:

```
boot:0x4 (DOWNLOAD_BOOT(UART0...))
```

and then goes quiet (ROM waiting for a host). If no pad does that, also tie
**IO8 (GPIO8) to 3V3** through ~10k — the C3 needs IO8 high to enter download mode.

> Shortcut: if two J2 pads turn out to be the chip's native USB (**D- = GPIO18,
> D+ = GPIO19**), wire them to a USB cable instead. The C3 enumerates as its own
> serial port and you can skip the UART adapter — use `BEFORE=usb-reset` below.

## 6. Dump it (read-only)

With the board in download mode:

```bash
./dump.sh dump /dev/cu.usbserial-XXXX
```

If reads are flaky, slow it down:

```bash
BAUD=115200 ./dump.sh dump /dev/cu.usbserial-XXXX
```

Using the native-USB route instead:

```bash
BEFORE=usb-reset ./dump.sh dump /dev/cu.usbmodemXXXX
```

The script will:
1. `get-security-info` + `espefuse summary` — **read-only**, tells us if it's locked.
2. Read the full 4 MB **twice** and compare SHA-256 (so you know the backup is good).
3. Run the analyser and print a verdict.

Output lands in `tools/dumps/<timestamp>/` (or wherever `dump.sh` lives).

---

## 7. Read the verdict

- **PLAINTEXT** → 🎉 flash encryption is off. The dump is real firmware. You can
  later flash ESPHome straight onto this board, and I can decompile the dump to pull
  out the Fujitsu UART settings + command codes. **Send me `analysis.txt`.**
- **Encrypted / Secure Download Mode** → the dump is ciphertext; you can't replace
  the firmware in place. Plan B: hot-air a fresh ESP32-C3-MINI-1 onto the board, or
  build a clone (C3 SuperMini + 12V→3.3V buck + 2-transistor level shifter + USB-A
  plug) and decode the protocol by sniffing the wire instead.

## Guard your backup

The `dumps/` folder is your **only** way back to stock. Keep it. The `nvs`
partition inside it holds your Wi-Fi password and the Sensibo device keys — don't
post the raw dump publicly; send it to me privately if you want it analysed.

---

### Pin reference (ESP32-C3)

| Net | GPIO | Role |
|---|---|---|
| U0TXD | 21 | serial out (chip → you) |
| U0RXD | 20 | serial in (you → chip) |
| EN | — | reset, active low |
| IO9 | 9 | boot select: low at reset = download mode |
| IO8 | 8 | must be **high** at reset to enter download |
| IO2 | 2 | must be high at reset (usually pulled already) |
| USB D- / D+ | 18 / 19 | native USB-serial |
