#!/usr/bin/env bash
# Read-only backup of a Sensibo anywAiR C3 board (ESP32-C3-MINI-1, 4 MB in-package flash).
#
# Nothing in this script writes to flash or burns eFuses. It only runs:
#   esptool get-security-info, espefuse summary, esptool read-flash (twice, to verify)
#
# Usage:
#   ./dump.sh bootlog /dev/cu.usbserial-XXXX   # watch the normal boot log (board NOT in download mode)
#   ./dump.sh dump    /dev/cu.usbserial-XXXX   # board must already be in download mode (GPIO9 low at reset)
#
# Env:
#   BEFORE=no-reset (default; bare board, you toggle EN/GPIO9 by hand)
#          usb-reset (if you're on the C3's own USB D+/D- pads)
#   BAUD=115200 (default). With --before/--after no-reset the flasher stub stays at
#        whatever baud the previous esptool call switched it to, so every call in
#        this script must use the same rate. 115200 needs no baud change at all.

set -euo pipefail

cmd=${1:-}
port=${2:-}
[[ -z "$cmd" || -z "$port" ]] && { sed -n '2,15p' "$0"; exit 1; }

here="$(cd "$(dirname "$0")" && pwd)"
out="$here/dumps/$(date +%Y%m%d-%H%M%S)"
BEFORE=${BEFORE:-no-reset}
BAUD=${BAUD:-115200}
FAST_BAUD=${FAST_BAUD:-921600}   # only for the final flash read

esptool()  {  # a later --baud overrides the default one here
  uvx --from esptool esptool --chip esp32c3 --port "$port" --baud "$BAUD" --before "$BEFORE" --after no-reset "$@"; }
espefuse() { uvx --from esptool espefuse --chip esp32c3 --port "$port" --before "$BEFORE" "$@"; }

case "$cmd" in
  bootlog)
    mkdir -p "$out"
    echo "Logging $port @115200 to $out/bootlog.txt. Reset the board (short EN to GND briefly). Ctrl-C to stop."
    uv run --quiet --with pyserial python3 -I -c '
import serial, sys
s = serial.Serial(sys.argv[1], 115200, timeout=0.2)
with open(sys.argv[2], "wb") as f:
    while True:
        b = s.read(4096)
        if b:
            f.write(b); f.flush()
            sys.stdout.write(b.decode("utf-8", "replace")); sys.stdout.flush()
' "$port" "$out/bootlog.txt"
    ;;

  dump)
    mkdir -p "$out"
    echo "== Saving to $out"

    echo "== Security info (read-only)"
    esptool get-security-info 2>&1 | tee "$out/security-info.txt" || echo "!! get-security-info failed (see above)"

    echo "== eFuse summary (read-only)"
    espefuse summary 2>&1 | tee "$out/efuse-summary.txt" || echo "!! efuse summary failed"
    espefuse summary --format json --file "$out/efuse-summary.json" >/dev/null 2>&1 || true

    if grep -qi "secure download mode" "$out/security-info.txt" 2>/dev/null; then
      echo "!! Secure Download Mode is on: flash reads are blocked by the ROM. Stopping here."
      exit 2
    fi

    # One fast read, last: after esptool raises the baud, no later call could reconnect.
    # The stub sends an MD5 of the flash it read and esptool aborts on a mismatch,
    # so a single read is already verified end to end.
    echo "== Reading full 4 MB flash at ${FAST_BAUD} baud (MD5-verified by the stub)"
    if ! esptool --baud "$FAST_BAUD" read-flash 0 0x400000 "$out/sensibo_c3_full.bin"; then
      echo "!! Read failed. Power-cycle (pad 4 still low) and retry with FAST_BAUD=460800."
      exit 3
    fi
    sha=$(shasum -a 256 "$out/sensibo_c3_full.bin" | cut -d' ' -f1)
    echo "$sha  sensibo_c3_full.bin" > "$out/SHA256SUMS"
    echo "== Read OK: $sha"
    python3 -I "$here/analyse_dump.py" "$out/sensibo_c3_full.bin" | tee "$out/analysis.txt"
    echo
    echo "Done. Keep $out somewhere safe: it is your only way back to stock firmware."
    ;;

  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
