# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Read files out of Skyrim Special Edition BSA archives without outside tools.

Version 105 (SSE, LZ4 frame compression) and 104 (Oldrim/LE layout, zlib) are supported.
"""
import struct
import zlib

COMPRESSED = 0x4            # archive flag: files are compressed unless their size has bit 30 set
EMBED_NAMES = 0x100         # archive flag: each file's data starts with its full path
TOGGLE = 0x40000000


def _lz4_block(src, out):
    """Decode one LZ4 block from src, appending to out (bytearray; earlier output may be referenced)."""
    i, n = 0, len(src)
    while i < n:
        tok = src[i]
        i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | src[i + 1] << 8
        i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        if off <= 0 or start < 0:
            raise ValueError("bad LZ4 data")
        if off >= ml:
            out += out[start:start + ml]
        else:                                   # overlapping copy: repeat the last `off` bytes
            seg = bytes(out[start:])
            out += (seg * (ml // off + 1))[:ml]


def lz4_frame(data):
    if struct.unpack_from("<I", data, 0)[0] != 0x184D2204:
        raise ValueError("not an LZ4 frame")
    flg = data[4]
    i = 6 + (8 if flg & 0x08 else 0) + (4 if flg & 0x01 else 0) + 1      # FLG, BD, [size], [dict id], HC
    block_sum = bool(flg & 0x10)
    out = bytearray()
    while True:
        size = struct.unpack_from("<I", data, i)[0]
        i += 4
        if size == 0:
            break
        raw = bool(size & 0x80000000)
        size &= 0x7FFFFFFF
        chunk = data[i:i + size]
        i += size + (4 if block_sum else 0)
        if raw:
            out += chunk
        else:
            _lz4_block(chunk, out)
    return bytes(out)


class Archive:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            h = f.read(36)
            if len(h) < 36 or h[:4] != b"BSA\0":
                raise ValueError(f"not a BSA: {path}")
            ver, off, flags, nfold, nfile, tfold, tfile = struct.unpack_from("<7I", h, 4)
            if ver not in (104, 105):
                raise ValueError(f"unsupported BSA version {ver}: {path}")
            self.ver, self.flags = ver, flags
            rec = 24 if ver == 105 else 16
            f.seek(0)                            # only the directory, not the (often huge) file data
            b = f.read(off + nfold * rec + tfold + nfold + nfile * 16 + tfile)
        counts = [struct.unpack_from("<I", b, off + i * rec + 8)[0] for i in range(nfold)]
        p = off + nfold * rec
        recs = []
        for c in counts:
            folder = ""
            if flags & 1:
                n = b[p]
                folder = b[p + 1:p + n].decode("cp1252", "replace").lower()
                p += 1 + n
            for j in range(c):
                _h, size, offset = struct.unpack_from("<QII", b, p + 16 * j)
                recs.append((folder, size, offset))
            p += 16 * c
        names = b[p:p + tfile].split(b"\0")
        self.files = {}
        for k, (folder, size, offset) in enumerate(recs):
            name = names[k].decode("cp1252", "replace").lower()
            self.files[(folder + "\\" + name) if folder else name] = (size, offset)

    def names(self):
        return list(self.files)

    def read(self, name):
        size, offset = self.files[name.lower().replace("/", "\\")]
        comp = bool(self.flags & COMPRESSED) != bool(size & TOGGLE)
        size &= 0x3FFFFFFF
        with open(self.path, "rb") as f:
            f.seek(offset)
            data = f.read(size)
        if self.flags & EMBED_NAMES:
            data = data[1 + data[0]:]
        if not comp:
            return data
        orig = struct.unpack_from("<I", data, 0)[0]
        out = lz4_frame(data[4:]) if self.ver == 105 else zlib.decompress(data[4:])
        if len(out) != orig:
            raise ValueError(f"{name}: unpacked {len(out)} bytes, expected {orig}")
        return out
