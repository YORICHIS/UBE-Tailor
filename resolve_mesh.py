# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Find which file the game actually uses for a mesh path (the MO2 profile picked in env.py).

Loose files (overwrite, then mods by modlist priority, then the game's Data folder) beat BSAs; between BSAs the one
whose plugin loads later wins. extract() copies the winning file into a destination folder (bsa.py for BSAs).
"""
import os
import shutil
import struct

import env


def enabled_mods():
    """Enabled mods, highest priority first."""
    return env.enabled_mods()


def load_order():
    return env.load_order()


def bsa_names(path):
    """List lowercase file paths inside an SSE (v104/105) BSA."""
    with open(path, "rb") as f:
        b = f.read(36)
        if len(b) < 36 or b[:4] != b"BSA\0":
            return []
        ver, off, aflags, nfold, nfile, tfold, tfile = struct.unpack_from("<7I", b, 4)
        if ver not in (104, 105):
            return []
        rec = 24 if ver == 105 else 16
        f.seek(0)      # only the directory part is needed, not the (often huge) file data
        b = f.read(off + nfold * rec + tfold + nfold + nfile * 16 + tfile)
    counts = [struct.unpack_from("<I", b, off + i * rec + 8)[0] for i in range(nfold)]
    p = off + nfold * rec
    folders = []
    for c in counts:
        name = ""
        if aflags & 1:
            n = b[p]
            name = b[p + 1:p + n].decode("cp1252", "replace").lower()
            p += 1 + n
        folders.append((name, c))
        p += 16 * c
    names = b[p:p + tfile].split(b"\0")
    out, k = [], 0
    for folder, c in folders:
        for _ in range(c):
            out.append(folder + "\\" + names[k].decode("cp1252", "replace").lower())
            k += 1
    return out


def _rank(lo, stem):
    """Load order position of the plugin that loads this archive ("<plugin>.bsa" or "<plugin> - Meshes.bsa")."""
    for s in (stem, stem.rsplit(" - ", 1)[0] if " - " in stem else None):
        if s:
            r = max((lo.get(s + e, -1) for e in (".esp", ".esm", ".esl")), default=-1)
            if r >= 0:
                return r
    return -1


class Resolver:
    def __init__(self):
        self.mods = enabled_mods()
        self.dirs = [env.OVERWRITE] + [os.path.join(env.MODS, m) for m in self.mods] + [env.DATA]
        self._bsa_index = None

    def loose(self, rel):
        rel = rel.replace("/", "\\")
        for base in self.dirs:
            p = os.path.join(base, "meshes", rel)
            if os.path.isfile(p):
                return p
        return None

    def bsa_index(self):
        if self._bsa_index is None:
            lo = {n: i for i, n in enumerate(load_order())}
            idx = {}
            # the game's own folder first (lowest priority): vanilla / Creation Club / DLC archives; Skyrim - *.bsa
            # load from the game's ini even without a plugin of that name. Then the mods, low priority first.
            dirs = [(env.DATA, True)] + [(os.path.join(env.MODS, m), False) for m in reversed(self.mods)]
            for d, game_dir in dirs:
                if not os.path.isdir(d):
                    continue
                for f in os.listdir(d):
                    if not f.lower().endswith(".bsa") or "textures" in f.lower():
                        continue
                    stem = f[:-4].lower()
                    rank = _rank(lo, stem)
                    if rank < 0 and game_dir and stem.startswith("skyrim - "):
                        rank = -0.5               # Skyrim - Meshes0/1.bsa: always loaded
                    if rank < 0:
                        continue  # archive not loaded by any active plugin
                    try:
                        names = bsa_names(os.path.join(d, f))
                    except (OSError, struct.error, IndexError):
                        continue                  # broken or foreign archive: the game cannot read it either
                    for n in names:
                        if n.startswith("meshes\\"):
                            old = idx.get(n)
                            if old is None or rank >= old[0]:
                                idx[n] = (rank, os.path.join(d, f))
            self._bsa_index = idx
        return self._bsa_index

    def resolve(self, rel):
        p = self.loose(rel)
        if p:
            return "loose", p
        hit = self.bsa_index().get("meshes\\" + rel.lower().replace("/", "\\"))
        return ("bsa", hit[1]) if hit else (None, None)

    def extract(self, rel, dest_dir):
        """Copy the winning file for meshes\\<rel> to dest_dir\\meshes\\<rel>. Returns the new path or None."""
        kind, src = self.resolve(rel)
        dst = os.path.join(dest_dir, "meshes", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if kind == "loose":
            shutil.copy2(src, dst)
            return dst
        if kind == "bsa":
            data = read_from_bsa(src, "meshes\\" + rel)
            if data is None:
                return None
            with open(dst, "wb") as f:
                f.write(data)
            return dst
        return None


_ARCHIVES = {}


def read_from_bsa(bsa_path, name):
    """One file's bytes from a BSA (bsa.py: no outside tool, no unpacking of the whole archive), or None."""
    import bsa
    try:
        a = _ARCHIVES.get(bsa_path)
        if a is None:
            a = _ARCHIVES[bsa_path] = bsa.Archive(bsa_path)
        return a.read(name)
    except (KeyError, ValueError, OSError):
        return None


if __name__ == "__main__":
    import sys
    r = Resolver()
    for rel in sys.argv[1:]:
        print(rel, "->", r.resolve(rel))
