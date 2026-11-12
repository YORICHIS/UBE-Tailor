# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Minimal Skyrim SE (NIF 20.2.0.7, BS version 100) reader/patcher for BSTriShape vertex positions.

Only vertex xyz (and the shape bounding sphere) are rewritten, in place, same byte length, so every
other block -- skinning, partitions, shaders, HDT-SMP extra data, physics bones -- stays byte-identical.
For skinned SSE shapes the vertex data lives in NiSkinPartition, so that copy is patched too.
"""
import struct

import numpy as np

VF_FULLPREC = 0x400


class SseNif:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.buf = bytearray(f.read())
        self._parse_header()
        self.shapes = [s for s in (self._parse_shape(i) for i, t in enumerate(self.block_types) if t == "BSTriShape") if s]

    # ---------------------------------------------------------------- header
    def _parse_header(self):
        b = self.buf
        p = b.index(b"\n") + 1
        ver, _endian, _uver, nblocks = struct.unpack_from("<IBII", b, p); p += 13
        if ver != 0x14020007:
            raise ValueError("not a NIF 20.2.0.7 file")
        (self.bsver,) = struct.unpack_from("<I", b, p); p += 4
        if self.bsver != 100:
            raise ValueError(f"not Skyrim SE (BS version {self.bsver})")
        for _ in range(3):  # author, process script, export script (ExportString: u8 len incl. NUL)
            p += 1 + b[p]
        (ntypes,) = struct.unpack_from("<H", b, p); p += 2
        types = []
        for _ in range(ntypes):
            (n,) = struct.unpack_from("<I", b, p); p += 4
            types.append(b[p:p + n].decode("ascii")); p += n
        idx = struct.unpack_from(f"<{nblocks}H", b, p); p += 2 * nblocks
        self.block_types = [types[i & 0x7FFF] for i in idx]
        sizes = struct.unpack_from(f"<{nblocks}I", b, p); p += 4 * nblocks
        nstr, _maxlen = struct.unpack_from("<II", b, p); p += 8
        self.strings = []
        for _ in range(nstr):
            (n,) = struct.unpack_from("<I", b, p); p += 4
            self.strings.append(b[p:p + n].decode("cp1252", "replace")); p += n
        (ngroups,) = struct.unpack_from("<I", b, p); p += 4 + 4 * ngroups
        self.block_ofs = []
        for s in sizes:
            self.block_ofs.append(p); p += s
        self.block_sizes = list(sizes)

    # ---------------------------------------------------------------- shapes
    @staticmethod
    def _layout(desc):
        # Skyrim SE (BSVertexDataSSE) always stores positions as full floats, whatever VF_FULLPREC says
        vsize = (desc & 0xF) * 4
        return vsize, True

    def _parse_shape(self, bi):
        b, p = self.buf, self.block_ofs[bi]
        (name_i,) = struct.unpack_from("<i", b, p); p += 4
        (nextra,) = struct.unpack_from("<I", b, p); p += 4 + 4 * nextra
        p += 4  # controller
        p += 4  # flags
        xf_ofs = p
        t = np.array(struct.unpack_from("<3f", b, p)); p += 12
        r = np.array(struct.unpack_from("<9f", b, p)).reshape(3, 3); p += 36
        (scale,) = struct.unpack_from("<f", b, p); p += 4
        p += 4  # collision object
        bound_ofs = p; p += 16
        skin, _shader, _alpha = struct.unpack_from("<3i", b, p); p += 12
        (desc,) = struct.unpack_from("<Q", b, p); p += 8
        ntris, nverts = struct.unpack_from("<HH", b, p); p += 4
        (dsize,) = struct.unpack_from("<I", b, p); p += 4
        vsize, full = self._layout(desc)
        copies = []
        if dsize > 0:
            copies.append((p, vsize, full))
        if skin >= 0:
            part = self._skin_partition(skin)
            if part is not None:
                q, pvsize, pfull, pcount = part
                copies.append((q, pvsize, pfull))
                if nverts == 0:          # skinned SSE shapes keep the counts in the partition
                    nverts = pcount
                elif nverts != pcount:
                    raise ValueError(f"vertex count mismatch in block {bi}")
        if not copies:
            return None
        name = self.strings[name_i] if 0 <= name_i < len(self.strings) else f"block{bi}"
        return {"block": bi, "name": name, "nverts": nverts, "copies": copies, "bound_ofs": bound_ofs,
                "skinned": skin >= 0,
                "xf": (t, r, scale), "xf_ofs": xf_ofs}

    def _skin_partition(self, skin_bi):
        if self.block_types[skin_bi] not in ("NiSkinInstance", "BSDismemberSkinInstance"):
            return None
        p = self.block_ofs[skin_bi]
        _data, part_bi = struct.unpack_from("<ii", self.buf, p)
        if part_bi < 0 or self.block_types[part_bi] != "NiSkinPartition":
            return None
        q = self.block_ofs[part_bi]
        _nparts, dsize, vsize = struct.unpack_from("<III", self.buf, q); q += 12
        (desc,) = struct.unpack_from("<Q", self.buf, q); q += 8
        if dsize == 0:
            return None
        _vs, full = self._layout(desc)
        return (q, vsize, full, dsize // vsize)

    # ---------------------------------------------------------------- access
    def positions(self, shape):
        """Vertex positions in shape-local space, from the first data copy."""
        ofs, vsize, full = shape["copies"][0]
        n = shape["nverts"]
        fmt = "<3f" if full else "<3e"
        return np.array([struct.unpack_from(fmt, self.buf, ofs + i * vsize) for i in range(n)], dtype=np.float64)

    def set_positions(self, shape, pos):
        pos = np.asarray(pos, dtype=np.float64)
        assert pos.shape == (shape["nverts"], 3)
        for ofs, vsize, full in shape["copies"]:
            fmt = "<3f" if full else "<3e"
            for i, v in enumerate(pos):
                struct.pack_into(fmt, self.buf, ofs + i * vsize, *v)
        lo, hi = pos.min(0), pos.max(0)
        c = (lo + hi) / 2
        rad = float(np.linalg.norm(pos - c, axis=1).max())
        struct.pack_into("<4f", self.buf, shape["bound_ofs"], *c, rad)

    def to_global(self, shape, local):
        t, r, s = shape["xf"]
        return local @ (r.T * s) + t

    def to_local_delta(self, shape, delta):
        _t, r, s = shape["xf"]
        return delta @ np.linalg.inv(r.T * s)

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.buf)
