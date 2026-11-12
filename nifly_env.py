# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Shared helpers for the 3BA -> UBE outfit converter.

- Loads PyNifly without Blender (env.find_pynifly(): bundled next to the tool, a folder picked in the settings,
  or PyNifly installed in Blender): its package __init__ files import bpy, so we register empty stub packages
  before importing the pure-python modules.
- read_osd(): BodySlide .osd slider diffs -> {entry_name: dense (N,3) numpy array}
- knn(): k-nearest-neighbour search (scipy's cKDTree; plain numpy when scipy is missing).
"""
import os
import struct
import sys
import types

import numpy as np

import env

PYNIFLY = env.find_pynifly()
HERE = env.TOOL
if PYNIFLY is None:
    raise ImportError("PyNifly was not found. Get it from https://github.com/BadDogSkyrim/PyNifly/releases and put "
                      "its 'io_scene_nifly' folder into a folder named 'pynifly' next to UBE Tailor, or install it "
                      "in Blender.")

if "io_scene_nifly" not in sys.modules:
    sys.path.insert(0, PYNIFLY)
    _pkg = types.ModuleType("io_scene_nifly")
    _pkg.__path__ = [os.path.join(PYNIFLY, "io_scene_nifly")]
    sys.modules["io_scene_nifly"] = _pkg
    for _sub in ("osd", "tri"):
        _m = types.ModuleType("io_scene_nifly." + _sub)
        _m.__path__ = [os.path.join(_pkg.__path__[0], _sub)]
        sys.modules["io_scene_nifly." + _sub] = _m

from io_scene_nifly.pyn.pynifly import NifFile  # noqa: E402,F401


def read_osd(path, nverts):
    """Return {entry_name: (nverts,3) float64 diffs} from a BodySlide .osd file."""
    out = {}
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic not in (b"\x00DSO", b"OSD\x00"):
            raise ValueError(f"not an OSD file: {path}")
        _ver, count = struct.unpack("<II", f.read(8))
        for _ in range(count):
            nlen = f.read(1)[0]
            name = f.read(nlen).decode("utf-8", "replace")
            (nd,) = struct.unpack("<H", f.read(2))
            raw = np.frombuffer(f.read(14 * nd), dtype=np.dtype([("i", "<u2"), ("d", "<f4", 3)]))
            d = np.zeros((nverts, 3))
            d[raw["i"]] = raw["d"]
            out[name] = d
    return out


try:
    from scipy.spatial import cKDTree as _KDTree
except ImportError:      # scipy is optional; without it the slow exact search below is used
    _KDTree = None


def knn(points, queries, k=1, chunk=2048):
    """k nearest `points` for each of `queries`. Returns (dist (Q,k), idx (Q,k))."""
    points = np.asarray(points, dtype=np.float64)
    queries = np.asarray(queries, dtype=np.float64)
    if _KDTree is None or len(points) <= k or not len(queries):
        return knn_brute(points, queries, k, chunk)
    # worker processes set OMP_NUM_THREADS so several conversions can run side by side
    threads = int(os.environ.get("OMP_NUM_THREADS") or -1)
    d, i = _KDTree(points).query(queries, k=k, workers=threads)
    if k == 1:
        d, i = d[:, None], i[:, None]
    return d, i.astype(np.int64)


def knn_brute(points, queries, k=1, chunk=2048):
    """Exact k nearest neighbours with plain numpy (O(Q*P)); the fallback when scipy is missing."""
    points = np.asarray(points, dtype=np.float64)
    queries = np.asarray(queries, dtype=np.float64)
    k = max(1, min(k, len(points)))      # a tiny piece can have fewer points than neighbours asked for
    pn = (points ** 2).sum(1)
    D = np.empty((len(queries), k))
    I = np.empty((len(queries), k), dtype=np.int64)
    for s in range(0, len(queries), chunk):
        q = queries[s:s + chunk]
        d2 = (q ** 2).sum(1)[:, None] + pn[None, :] - 2.0 * q @ points.T
        np.maximum(d2, 0, out=d2)
        if k == 1:
            idx = d2.argmin(1)[:, None]
        else:
            idx = np.argpartition(d2, k - 1, axis=1)[:, :k]
        dd = np.take_along_axis(d2, idx, 1)
        order = dd.argsort(1)
        I[s:s + chunk] = np.take_along_axis(idx, order, 1)
        D[s:s + chunk] = np.sqrt(np.take_along_axis(dd, order, 1))
    return D, I


def verts(nif_path, shape_index=0):
    n = NifFile(nif_path)
    return np.array(n.shapes[shape_index].verts, dtype=np.float64)
