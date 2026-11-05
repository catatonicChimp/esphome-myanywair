"""Parse the Fujitsu/Sensibo register protocol from a .sr capture.

Decodes both UART lines (9600 8N1 inverted), splits into frames on the
03 00 00 00 sync, and reports: the canonical frames, and which register
VALUES change across the capture (= the settings that were adjusted).

Usage: python3 -I parse_frames.py /path/to/capture.sr [max_chunks]
"""
import sys, zipfile, re
import numpy as np

SYNC = b"\x03\x00\x00\x00"


def load(srpath, max_chunks=None):
    z = zipfile.ZipFile(srpath)
    meta = z.read("metadata").decode()
    m = re.search(r"samplerate=(\d+)\s*([kMG]?)Hz", meta)
    mult = {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}[m.group(2)]
    sr = int(int(m.group(1)) * mult)
    chunks = sorted((n for n in z.namelist() if re.match(r"logic-1-\d+$", n)),
                    key=lambda n: int(n.split("-")[-1]))
    if max_chunks:
        chunks = chunks[:max_chunks]
    return sr, np.frombuffer(b"".join(z.read(c) for c in chunks), dtype=np.uint8)


def decode_uart(bits, bit_samples, invert=True):
    line = (1 - bits) if invert else bits
    n = len(line); i = 0; out = bytearray(); half = bit_samples // 2
    while i < n - bit_samples * 10:
        if line[i] == 1 and line[i + 1] == 0:
            start = i + 1
            if line[start + half] != 0:
                i += 1; continue
            val = 0
            for b in range(8):
                if line[start + half + (b + 1) * bit_samples]:
                    val |= (1 << b)
            stop = start + half + 9 * bit_samples
            if stop < n and line[stop] == 1:
                out.append(val); i = stop
            else:
                i += bit_samples
        else:
            i += 1
    return bytes(out)


def frames(stream):
    parts = stream.split(SYNC)
    return [SYNC + p for p in parts[1:] if p]


def parse_regs(fr):
    """Return dict addr->value for a response frame (tag 10/11, addr, 2-byte value)."""
    # layout: 03000000 <len> <type?> 52 06 [tag addr hi lo]... csum csum
    body = fr[4:]
    if len(body) < 4:
        return {}, None
    length = body[0]
    # find 52 06 marker
    idx = fr.find(b"\x52\x06")
    if idx < 0:
        return {}, length
    p = idx + 2
    regs = {}
    data = fr[p:len(fr) - 2]  # drop 2-byte checksum
    i = 0
    while i + 4 <= len(data):
        tag, addr, hi, lo = data[i], data[i + 1], data[i + 2], data[i + 3]
        if tag in (0x10, 0x11):
            regs[(tag, addr)] = (hi << 8) | lo
            i += 4
        else:
            i += 1
    return regs, length


def main():
    srpath = sys.argv[1]
    max_chunks = int(sys.argv[2]) if len(sys.argv) > 2 else None
    sr, samples = load(srpath, max_chunks)
    bit_samples = round(sr / 9600)
    print(f"{len(samples):,} samples @ {sr/1e6:g}MHz, {len(samples)/sr:.1f}s, bit={bit_samples} samp\n")

    for ch, shift in (("D0", 0), ("D1", 1)):
        bits = (samples >> shift) & 1
        if bits.min() == bits.max():
            print(f"[{ch}] idle\n"); continue
        stream = decode_uart(bits, bit_samples, invert=True)
        frs = frames(stream)
        print(f"===== {ch}: {len(frs)} frames =====")
        # show the first full frame
        if frs:
            print("  sample frame:", frs[1 if len(frs) > 1 else 0].hex(" "))
        # track register values over time
        history = {}
        order = []
        for fr in frs:
            regs, _ = parse_regs(fr)
            for k, v in regs.items():
                if k not in history:
                    history[k] = []
                    order.append(k)
                if not history[k] or history[k][-1] != v:
                    history[k].append(v)
        print(f"  registers seen: {len(order)}")
        for k in order:
            vals = history[k]
            tag, addr = k
            changed = " <== CHANGES" if len(vals) > 1 else ""
            shown = " -> ".join(f"{v:04x}" for v in vals[:12])
            print(f"   reg {tag:02x}:{addr:02x} = {shown}{changed}")
        print()


if __name__ == "__main__":
    main()
