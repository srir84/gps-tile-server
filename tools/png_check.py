"""png_check.py: exits 0 only if the file is a complete 256 x 256 RGBA heat-map tile: the PNG signature, every
chunk's CRC, IHDR first and IEND last, and the image data inflating to 256 rows of 1 + 1,024 bytes. Used by
the deploy and release smoke tests (tools/deploy.sh, tools/release.sh). Usage: python3 -I png_check.py FILE"""
import struct
import sys
import zlib

data = open(sys.argv[1], "rb").read()
assert data[:8] == b"\x89PNG\r\n\x1a\n"
i, kinds, idat = 8, [], b""
while i < len(data):
    n, kind = struct.unpack(">I4s", data[i:i + 8])
    body = data[i + 8:i + 8 + n]
    assert len(body) == n and struct.unpack(">I", data[i + 8 + n:i + 12 + n])[0] == zlib.crc32(kind + body)
    kinds.append(kind)
    idat += body if kind == b"IDAT" else b""
    i += 12 + n
assert kinds[0] == b"IHDR" and kinds[-1] == b"IEND" and data[16:24] == struct.pack(">II", 256, 256)
assert len(zlib.decompress(idat)) == 256 * 1025
