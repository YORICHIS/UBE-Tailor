# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Which UBE meshes really exist, so the merged patch (merged_patch.py) only points armor addons at meshes that are
there. A project that was made but not built in BodySlide yet must not count: the piece would be invisible.
"""
import os

import env


def converted_set():
    """UBE meshes that really exist as loose files - built by BodySlide into any enabled mod or overwrite, or
    shipped by a mod or the game's Data folder: meshes\\!UBE\\<path> -> '<path>' (lower case)."""
    s = set()
    for base in env.loose_dirs():
        d = os.path.join(base, "meshes", "!UBE")
        if not os.path.isdir(d):
            continue
        for dp, _dn, fn in os.walk(d):
            for f in fn:
                if f.lower().endswith(".nif"):
                    s.add(os.path.relpath(os.path.join(dp, f), d).lower())
    return s


def mesh_exists():
    """exists(meshes-relative path) -> bool, loose files and loaded BSAs."""
    from resolve_mesh import Resolver
    r = Resolver()
    return lambda rel: r.resolve(rel)[0] is not None
