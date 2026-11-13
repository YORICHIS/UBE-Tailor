# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Read Skyrim SE plugins (.esp/.esm/.esl): records of chosen top groups, subrecords, plugin locations."""
import os
import struct
import zlib

import env


def enabled_plugins():
    return env.enabled_plugins()


def plugin_locations():
    """{plugin file name lower: winning path} for every plugin file the game sees (game Data, mods, overwrite)."""
    loc = {}
    exts = (".esp", ".esm", ".esl")
    # lowest priority first, later ones win: game Data, mods from the bottom of modlist.txt up, overwrite
    for d in [env.DATA] + [os.path.join(env.MODS, m) for m in reversed(env.enabled_mods())] + [env.OVERWRITE]:
        if d and os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().endswith(exts):
                    loc[f.lower()] = os.path.join(d, f)
    return loc


def subrecords(buf):
    i, n, big = 0, len(buf), None
    while i + 6 <= n:
        t = buf[i:i + 4]
        sz = struct.unpack_from("<H", buf, i + 4)[0]
        i += 6
        if t == b"XXXX":
            big = struct.unpack_from("<I", buf, i)[0]
            i += sz
            continue
        if big is not None:
            sz, big = big, None
        yield t, buf[i:i + sz]
        i += sz


def zstr(d):
    return d.split(b"\0", 1)[0].decode("cp1252", "replace")


class RecFlags(int):
    """A record's flags that also remember its form version (record header bytes 20-21). A copy of the record must
    keep that version: the layout of some fields depends on it (MO2T..MO5T texture hashes are a bare list of 12-byte
    entries before version 40), and a version-44 header on old data crashes the game while it loads the plugin."""

    def __new__(cls, flags, form_version=44):
        o = super().__new__(cls, flags)
        o.form_version = form_version
        return o


def read_plugin(path, want):
    """Return (masters, records) where records = list of (sig, formid, data, flags) for top groups in want;
    flags is a RecFlags (it carries the record's form version)."""
    recs = []
    with open(path, "rb") as f:
        hdr = f.read(24)
        if hdr[:4] != b"TES4":
            return [], recs
        tes4 = f.read(struct.unpack_from("<I", hdr, 4)[0])
        masters = [zstr(d) for t, d in subrecords(tes4) if t == b"MAST"]
        while True:
            g = f.read(24)
            if len(g) < 24:
                break
            gsize = struct.unpack_from("<I", g, 4)[0]
            if g[:4] != b"GRUP" or g[8:12] not in want:
                f.seek(gsize - 24, 1)
                continue
            end = f.tell() + gsize - 24
            while f.tell() < end:
                h = f.read(24)
                if h[:4] == b"GRUP":
                    continue
                sz = struct.unpack_from("<I", h, 4)[0]
                flags, fid = struct.unpack_from("<II", h, 8)
                form_version = struct.unpack_from("<H", h, 20)[0]
                data = f.read(sz)
                if flags & 0x40000:
                    data = zlib.decompress(data[4:])
                recs.append((h[:4], fid, data, RecFlags(flags, form_version)))
    return masters, recs



