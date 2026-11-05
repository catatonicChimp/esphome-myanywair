"""Fujitsu anywAiR / Sensibo UART protocol codec.

Wire format: 9600 baud, 8N1, INVERTED (idle low).
Frame:  03 00 00 00  <len> [01]  52 06  [ff ff]  <register entries>  <csum hi> <csum lo>
        ^^^^^^^^^^^ sync        ^^^^^ type 0x5206   ... TLVs ...       one's-complement
Type byte right after sync: 0x03 = poll/response, 0x02 = write command.
Checksum: csum16 = 0xFFFF - (sum of every frame byte before the 2 csum bytes), big-endian.
Register entry: tag(10/11) addr  [hi lo]   (value present in responses/writes).

This module is used to validate the decode against the capture and to build
command frames for the ESPHome port.
"""

SYNC = b"\x03\x00\x00\x00"


def checksum(frame_wo_csum: bytes) -> bytes:
    c = (0xFFFF - (sum(frame_wo_csum) & 0xFFFF)) & 0xFFFF
    return bytes([c >> 8, c & 0xFF])


def verify(frame: bytes) -> bool:
    body, csum = frame[:-2], (frame[-2] << 8) | frame[-1]
    return ((sum(body) + csum) & 0xFFFF) == 0xFFFF


def build_write(addr: int, value: int, tag: int = 0x10) -> bytes:
    """Build a type-0x02 write command: set register addr = value (16-bit)."""
    body = bytes([0x02, 0x00, 0x00, 0x00, 0x04, tag, addr, (value >> 8) & 0xFF, value & 0xFF])
    return body + checksum(body)


REG_NAMES = {
    0x00: "power",
    0x01: "mode",
    0x02: "setpoint_decideg",   # value/10 = deg C
    0x03: "fan",
    0x33: "sensor?",
}


if __name__ == "__main__":
    # self-test against frames observed in the capture
    known = [
        "03 00 00 00 1a 52 06 10 00 10 01 10 02 10 03 10 10 10 11 10 22 10 23 10 33 10 b6 11 01 10 31 fd 42",
        "03 00 00 00 35 01 52 06 ff ff 10 00 00 01 10 01 00 01 10 02 00 f0 10 03 00 00 10 10 ff ff 10 11 00 00 10 22 ff ff 10 23 ff ff 10 33 1c e8 10 b6 ff ff 11 01 00 00 10 31 00 00 f1 3a",
        "03 00 00 00 35 01 52 06 ff ff 10 00 00 01 10 01 00 01 10 02 00 e6 10 03 00 00 10 10 ff ff 10 11 00 00 10 22 ff ff 10 23 ff ff 10 33 1c e8 10 b6 ff ff 11 01 00 00 10 31 00 00 f1 44",
        "02 00 00 00 04 10 02 00 e6 ff 01",
    ]
    print("checksum verification of captured frames:")
    for h in known:
        f = bytes.fromhex(h)
        print(f"  {'OK ' if verify(f) else 'BAD'}  sum={sum(f)&0xffff:04x}  {h[:40]}...")

    print("\nrebuild the setpoint write (23.0C = 0x00e6) and compare to captured:")
    built = build_write(0x02, 0x00E6)
    cap = bytes.fromhex("02 00 00 00 04 10 02 00 e6 ff 01".replace(" ", ""))
    print(f"  built   : {built.hex(' ')}")
    print(f"  captured: {cap.hex(' ')}")
    print(f"  MATCH: {built == cap}")

    print("\nexample commands we can now send:")
    for degc in (18.0, 22.0, 25.0):
        print(f"  set {degc}C -> {build_write(0x02, int(degc*10)).hex(' ')}")
    for m in range(5):
        print(f"  set mode {m} -> {build_write(0x01, m).hex(' ')}")
