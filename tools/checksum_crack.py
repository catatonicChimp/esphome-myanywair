"""Brute-force the 2-byte trailer (checksum) of the Fujitsu/Sensibo frames.

Collects complete frames from a .sr capture, then tests sum and CRC16
variants over several byte ranges to find one matching ALL frames.

Usage: python3 -I checksum_crack.py /path/to/capture.sr [max_chunks]
"""
import sys, zipfile, re
import numpy as np

SYNC = b"\x03\x00\x00\x00"


def load(srpath, max_chunks=None):
    z = zipfile.ZipFile(srpath)
    meta = z.read("metadata").decode()
    m = re.search(r"samplerate=(\d+)\s*([kMG]?)Hz", meta)
    sr = int(int(m.group(1)) * {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}[m.group(2)])
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


def get_frames(stream):
    parts = stream.split(SYNC)
    out = []
    for p in parts[1:]:
        fr = SYNC + p
        # a frame's declared length byte is fr[4]; total = 4 sync +1 len + body...
        # we just keep whole split segments that look sane
        if 8 <= len(fr) <= 80:
            out.append(fr)
    return out


def crc16(data, poly, init, refin, refout, xorout):
    def rev(x, n):
        r = 0
        for _ in range(n):
            r = (r << 1) | (x & 1); x >>= 1
        return r
    crc = init
    for b in data:
        if refin:
            b = rev(b, 8)
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    if refout:
        crc = rev(crc, 16)
    return crc ^ xorout


def main():
    srpath = sys.argv[1]
    max_chunks = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    sr, samples = load(srpath, max_chunks)
    bs = round(sr / 9600)
    # gather unique frames from both lines
    frs = []
    for shift in (0, 1):
        bits = (samples >> shift) & 1
        if bits.min() == bits.max():
            continue
        frs += get_frames(decode_uart(bits, bs))
    # unique, keep a handful of distinct ones
    seen = {}
    for f in frs:
        seen[f] = seen.get(f, 0) + 1
    uniq = [f for f, _ in sorted(seen.items(), key=lambda kv: -kv[1])][:12]
    print(f"{len(frs)} frames, {len(uniq)} distinct tested\n")
    for f in uniq[:6]:
        print("  frame:", f.hex(" "))
    print()

    # candidate payload ranges (exclude trailing 2 csum bytes)
    def ranges(f):
        body = f[:-2]
        yield "full", body
        yield "no-sync", body[4:]
        yield "from-len", body[4:]
        yield "after-5206", f[f.find(b"\x52\x06") + 2:-2] if b"\x52\x06" in f else body

    # --- simple sums ---
    for name, pick in [("sum16LE", "le"), ("sum16BE", "be")]:
        for rname in ["full", "no-sync", "after-5206"]:
            ok = True
            for f in uniq:
                body = dict(ranges(f))[rname]
                s = sum(body) & 0xFFFF
                exp = f[-2] | (f[-1] << 8) if pick == "le" else (f[-2] << 8) | f[-1]
                if s != exp:
                    ok = False; break
            if ok:
                print(f"MATCH: {name} over {rname}")

    # --- CRC16 sweep ---
    polys = [0x1021, 0x8005, 0x3D65, 0xA001]
    inits = [0x0000, 0xFFFF]
    found = False
    for poly in polys:
        for init in inits:
            for refin in (False, True):
                for refout in (False, True):
                    for xorout in (0x0000, 0xFFFF):
                        for order in ("le", "be"):
                            for rname in ["full", "no-sync", "after-5206"]:
                                ok = True
                                for f in uniq:
                                    body = dict(ranges(f))[rname]
                                    c = crc16(body, poly, init, refin, refout, xorout)
                                    exp = (f[-2] | (f[-1] << 8)) if order == "le" else ((f[-2] << 8) | f[-1])
                                    if c != exp:
                                        ok = False; break
                                if ok:
                                    print(f"MATCH CRC16 poly={poly:#06x} init={init:#06x} "
                                          f"refin={refin} refout={refout} xorout={xorout:#06x} "
                                          f"order={order} range={rname}")
                                    found = True
    if not found:
        print("No standard sum/CRC16 matched - trailer may be a custom check or cover different bytes.")
        # show the byte-sum vs trailer for manual inspection
        for f in uniq[:4]:
            body = f[4:-2]
            print(f"  body-sum={sum(body)&0xffff:04x}  trailer={f[-2]:02x}{f[-1]:02x}  len={len(f)}")


if __name__ == "__main__":
    main()
