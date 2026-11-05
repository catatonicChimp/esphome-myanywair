"""Decode a sigrok .sr logic capture of a UART line: measure baud, detect
polarity, and dump the decoded bytes for each channel.

Usage: python3 -I decode_sr.py /path/to/capture.sr [max_chunks]
"""
import sys, zipfile, re
import numpy as np

STD_BAUDS = [2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200]


def load(srpath, max_chunks=None):
    z = zipfile.ZipFile(srpath)
    meta = z.read("metadata").decode()
    sr = int(re.search(r"samplerate=(\d+)\s*([kMG]?)Hz", meta).group(1))
    mult = {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}[re.search(r"samplerate=\d+\s*([kMG]?)Hz", meta).group(1)]
    samplerate = int(sr * mult)
    chunks = sorted((n for n in z.namelist() if re.match(r"logic-1-\d+$", n)),
                    key=lambda n: int(n.split("-")[-1]))
    if max_chunks:
        chunks = chunks[:max_chunks]
    data = b"".join(z.read(c) for c in chunks)
    return samplerate, np.frombuffer(data, dtype=np.uint8)


def measure_bit(bits):
    """Shortest consistent run length among the signal = 1 bit time (samples)."""
    edges = np.flatnonzero(np.diff(bits.astype(np.int8)))
    if len(edges) < 4:
        return None, 0
    runs = np.diff(edges)
    runs = runs[runs > 0]
    # the bit period ~ the small-end mode; use 2nd percentile to dodge glitches
    bit = int(np.percentile(runs, 2))
    return bit, len(edges)


def decode_uart(bits, bit_samples, invert):
    """Standard 8N1 decode. bits: 0/1 array (line level). invert flips it."""
    line = (1 - bits) if invert else bits
    n = len(line); i = 0; out = bytearray(); good = 0; bad = 0
    half = bit_samples // 2
    while i < n - bit_samples * 10:
        if line[i] == 1 and line[i + 1] == 0:  # falling edge = start bit
            start = i + 1
            center = start + half
            # verify start bit still low at its center
            if line[center] != 0:
                i += 1; continue
            val = 0
            for b in range(8):
                pos = start + half + (b + 1) * bit_samples
                if pos >= n: break
                if line[pos]:
                    val |= (1 << b)
            stop_pos = start + half + 9 * bit_samples
            if stop_pos < n and line[stop_pos] == 1:
                good += 1; out.append(val)
                i = stop_pos
            else:
                bad += 1; i += bit_samples
        else:
            i += 1
    return bytes(out), good, bad


def analyse_channel(name, bits, samplerate):
    bit_samples, nedges = measure_bit(bits)
    if not bit_samples:
        print(f"  {name}: idle/no activity ({nedges} edges)")
        return
    baud = samplerate / bit_samples
    nearest = min(STD_BAUDS, key=lambda b: abs(b - baud))
    print(f"  {name}: {nedges} edges, bit≈{bit_samples} samp → {baud:,.0f} baud (nearest standard {nearest})")
    bs = round(samplerate / nearest)
    best = None
    for inv in (False, True):
        data, good, bad = decode_uart(bits, bs, inv)
        frames = good + bad
        qual = good / frames if frames else 0
        print(f"     polarity={'INVERTED' if inv else 'normal'}: {good} good / {bad} bad ({qual:.0%} clean), {len(data)} bytes")
        if best is None or good > best[1]:
            best = (inv, good, data)
    inv, good, data = best
    print(f"  >>> best: {nearest} baud, {'INVERTED' if inv else 'normal'} polarity")
    show = data[:400]
    print("     hex:", show.hex(" "))
    print("     ascii:", "".join(chr(c) if 32 <= c < 127 else "." for c in show))
    return nearest, inv, data


def main():
    srpath = sys.argv[1]
    max_chunks = int(sys.argv[2]) if len(sys.argv) > 2 else None
    samplerate, samples = load(srpath, max_chunks)
    dur = len(samples) / samplerate
    print(f"{srpath}: {len(samples):,} samples @ {samplerate/1e6:g} MHz = {dur:.2f} s\n")
    for ch, shift in (("D0", 0), ("D1", 1)):
        bits = (samples >> shift) & 1
        if bits.min() == bits.max():
            print(f"  {ch}: constant {bits[0]} (unused/idle)")
            continue
        print(f"[{ch}]")
        analyse_channel(ch, bits, samplerate)
        print()


if __name__ == "__main__":
    main()
