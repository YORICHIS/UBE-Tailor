# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""BODYTRI: the NiStringExtraData that tells RaceMenu (and so OBody / any body-morph mod) which .tri morph file
belongs to a shape. RaceMenu reads the FIRST BODYTRI of a shape.

The problem: a 3BA outfit mesh already carries the 3BA BODYTRI ("<path>.tri"). The converter kept it in the UBE
project, and BodySlide's Build Morphs adds its own BODYTRI ("!UBE\\<path>.tri") as a second entry instead of
replacing it. RaceMenu then reads the old one - a 3BA (or missing) morph file - so the outfit never follows the
body's preset: built on Zeroed Sliders with OBody, the body grows through it.

  neutralize_source(nif)  project side: renames the old entry (its name becomes its own value, so it is no longer
                          a "BODYTRI"); BodySlide then writes the only, correct one. Done by make_projects.
  fix_built(nif)          game side, no rebuild needed: points every BODYTRI of a shape at the UBE morph file.
Both change 4 bytes per entry (string indices); nothing else in the file moves.
"""
import struct

from nif_patch import SseNif

OWNERS = ("BSTriShape", "BSDynamicTriShape", "NiTriShape", "BSSubIndexTriShape", "NiNode", "BSFadeNode")


def entries(n):
    """[(owner block, extra block, name string index, value string index, value)] of BODYTRI entries, in list order."""
    out = []
    for bi, t in enumerate(n.block_types):
        if t not in OWNERS:
            continue
        o = n.block_ofs[bi]
        _name_i, cnt = struct.unpack_from("<iI", n.buf, o)
        if cnt > 256:
            continue
        for ref in struct.unpack_from(f"<{cnt}i", n.buf, o + 8):
            if 0 <= ref < len(n.block_types) and n.block_types[ref] == "NiStringExtraData":
                ni, vi = struct.unpack_from("<ii", n.buf, n.block_ofs[ref])
                if 0 <= ni < len(n.strings) and n.strings[ni] == "BODYTRI":
                    out.append((bi, ref, ni, vi, n.strings[vi] if 0 <= vi < len(n.strings) else None))
    return out


def _write(n, path):
    with open(path, "wb") as f:
        f.write(n.buf)


def neutralize_source(path, save=True):
    """Project nif: no BODYTRI left (each one renamed to its own value). Returns how many were renamed."""
    n = SseNif(path)
    ents = entries(n)
    for _owner, ref, _ni, vi, _val in ents:
        struct.pack_into("<i", n.buf, n.block_ofs[ref], vi)
    if ents and save:
        _write(n, path)
    return len(ents)


def fix_built(path, save=True):
    """Built mesh: every BODYTRI of a shape points at its UBE morph file (the !UBE one, else the last one).
    Returns [(block, old value, new value)] of the entries changed."""
    n = SseNif(path)
    by_owner = {}
    for e in entries(n):
        by_owner.setdefault(e[0], []).append(e)
    changes = []
    for ents in by_owner.values():
        if len(ents) < 2:
            continue
        good = next((e for e in reversed(ents) if (e[4] or "").lower().startswith("!ube\\")), ents[-1])
        for _owner, ref, _ni, vi, val in ents:
            if vi != good[3]:
                struct.pack_into("<i", n.buf, n.block_ofs[ref] + 4, good[3])
                changes.append((ref, val, good[4]))
    if changes and save:
        _write(n, path)
    return changes
