# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Geometry for the 3BA -> UBE (user preset) displacement field.

Reference chain (built once per modpack, cached in the work folder as field_cache.npz; rebuilt when one of
the reference files changes):
  R   = "3BA to UBE 2.0" reference base (3BA shape), R + slider == UBE base shape (UBE's "Conversion references")
  U   = UBE base body+feet+hands (BodySlide ShapeData of UBE 2.0)
  Rtb[i] = where reference vertex i ends up on the UBE base shape ("b" = zero sliders, what BodySlide projects use)
  T3  = CBBE 3BA Ref body (zero sliders) with its targets T3tb (via projection onto R)
Per outfit: points on its embedded body (or T3 where the body was trimmed away) carry a displacement;
every outfit vertex gets the inverse-distance-weighted displacement of its k nearest such points.
"""
import os

import numpy as np

import env
from nifly_env import NifFile, knn, read_osd

CACHE = os.path.join(env.WORK, "field_cache.npz") if env.WORK else None
CACHE_VERSION = 2


class MissingReference(RuntimeError):
    """A file from UBE 2.0, its Conversion references or CBBE 3BA is not installed."""


def parts():
    """[(key, partition, nif, osd, osp)] of the UBE base body / feet / hands, wherever UBE 2.0 is installed."""
    out = []
    for key, partition, folder in env.UBE_PARTS:
        nif, osd, osp = env.ube_part(folder)
        if not (nif and osd and osp):
            raise MissingReference(f"UBE 2.0 BodySlide files not found ({folder}). Install UBE 2.0 and enable it.")
        out.append((key, partition, nif, osd, osp))
    return out


def inputs():
    """Every file the reference cache is built from: (conversion nif, conversion osd, 3BA ref nif, part nifs)."""
    rn, ro = env.conversion_ref()
    if not rn:
        raise MissingReference("UBE's 'Conversion references' (3BA to UBE 2.0) are not installed. Download the "
                               "optional file 'Conversion references' from the UBE 2.0 page and install it in MO2.")
    t3 = env.t3_ref()
    if not t3:
        raise MissingReference("CBBE 3BA (3BBB) is not installed or not enabled (CBBE 3BA Ref.nif not found).")
    return rn, ro, t3, [p[2] for p in parts()]


def _signature(files):
    out = []
    for f in files:
        st = os.stat(f)
        out.append(f"{os.path.normcase(f)}|{int(st.st_mtime)}|{st.st_size}")
    return np.array([str(CACHE_VERSION)] + out)


def mesh(path):
    s = NifFile(path).shapes[0]
    return np.array(s.verts, dtype=np.float64), np.array(s.tris, dtype=np.int64)


# ------------------------------------------------------------------ closest point on a triangle mesh
def tri_adjacency(nv, F):
    flat = F.ravel()
    counts = np.bincount(flat, minlength=nv)
    adj = -np.ones((nv, max(int(counts.max()), 1)), dtype=np.int64)
    order = np.argsort(flat, kind="stable")
    vs = flat[order]
    starts = np.cumsum(counts) - counts
    adj[vs, np.arange(len(order)) - starts[vs]] = order // 3
    return adj


def _closest_bary(p, a, b, c):
    """Barycentric coords of the closest point on triangle abc to p (Ericson). Arrays (...,3)."""
    ab, ac, ap = b - a, c - a, p - a
    bp, cp = p - b, p - c
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = va + vb + vc
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    v, w = vb / den, vc / den
    out = np.stack([1 - v - w, v, w], -1)

    def put(mask, bary):
        out[mask] = bary[mask] if bary.ndim == out.ndim else bary

    with np.errstate(divide="ignore", invalid="ignore"):
        e = (d4 - d3) + (d5 - d6)
        t = np.where(np.abs(e) < 1e-12, 0, (d4 - d3) / e)
        put((va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0), np.stack([0 * t, 1 - t, t], -1))       # edge BC
        t = np.where(np.abs(d2 - d6) < 1e-12, 0, d2 / (d2 - d6))
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), np.stack([1 - t, 0 * t, t], -1))                 # edge AC
        put((d6 >= 0) & (d5 <= d6), np.array([0.0, 0.0, 1.0]))                                  # vertex C
        t = np.where(np.abs(d1 - d3) < 1e-12, 0, d1 / (d1 - d3))
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), np.stack([1 - t, t, 0 * t], -1))                 # edge AB
        put((d3 >= 0) & (d4 <= d3), np.array([0.0, 1.0, 0.0]))                                  # vertex B
        put((d1 <= 0) & (d2 <= 0), np.array([1.0, 0.0, 0.0]))                                   # vertex A
    return out


def project(P, V, F, adj=None, k=4, chunk=2048):
    """Closest point on mesh (V,F) for each P. Returns (tri index, barycentric (N,3), distance)."""
    if adj is None:
        adj = tri_adjacency(len(V), F)
    _, I = knn(V, P, k)
    tri = np.empty(len(P), dtype=np.int64)
    bary = np.empty((len(P), 3))
    dist = np.empty(len(P))
    for s in range(0, len(P), chunk):
        cand = adj[I[s:s + chunk]].reshape(len(I[s:s + chunk]), -1)
        valid = cand >= 0
        cc = np.where(valid, cand, 0)
        a, b, c = V[F[cc, 0]], V[F[cc, 1]], V[F[cc, 2]]
        p = P[s:s + chunk][:, None, :]
        bc = _closest_bary(np.broadcast_to(p, a.shape), a, b, c)
        q = bc[..., 0:1] * a + bc[..., 1:2] * b + bc[..., 2:3] * c
        d2 = ((q - p) ** 2).sum(-1)
        d2[~valid] = np.inf
        j = d2.argmin(1)
        r = np.arange(len(j))
        tri[s:s + chunk] = cc[r, j]
        bary[s:s + chunk] = bc[r, j]
        dist[s:s + chunk] = np.sqrt(d2[r, j])
    return tri, bary, dist


def interp(values, F, tri, bary):
    f = F[tri]
    return (values[f[:, 0]] * bary[:, 0:1] + values[f[:, 1]] * bary[:, 1:2] + values[f[:, 2]] * bary[:, 2:3])


# ------------------------------------------------------------------ reference cache
def build_cache(log=print):
    rn, ro, t3_path, part_nifs = inputs()
    R, RF = mesh(rn)
    S = next(iter(read_osd(ro, len(R)).values()))
    Us, UFs = [], []
    off = 0
    for nif in part_nifs:
        v, f = mesh(nif)
        Us.append(v); UFs.append(f + off); off += len(v)
    U, UF = np.vstack(Us), np.vstack(UFs)
    tri, bary, dist = project(R + S, U, UF)
    log(f"reference+slider -> UBE base surface: mean {dist.mean():.4f}  p99 {np.percentile(dist, 99):.4f}  max {dist.max():.3f}")
    if dist.mean() > 0.5:
        raise MissingReference("The installed '3BA to UBE 2.0' reference does not match the installed UBE 2.0 body "
                               f"(mean distance {dist.mean():.2f}). Update both to the same UBE version.")
    out = {"R": R, "RF": RF}
    out["Rtb"] = interp(U, UF, tri, bary)      # "b" = UBE base shape (zero sliders), for BodySlide projects
    T3, _ = mesh(t3_path)
    ttri, tbary, tdist = project(T3, R, RF)
    log(f"3BA Ref -> reference surface: mean {tdist.mean():.4f}  p99 {np.percentile(tdist, 99):.4f}")
    ok = tdist <= 1.5                     # 3BA Ref has a neck/head stub the reference does not cover
    log(f"3BA Ref points usable: {ok.sum()} of {len(ok)}")
    T3, ttri, tbary = T3[ok], ttri[ok], tbary[ok]
    out["T3"] = T3
    out["T3tb"] = interp(out["Rtb"], RF, ttri, tbary)
    out["sig"] = _signature([rn, ro, t3_path] + part_nifs)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    np.savez_compressed(CACHE, **out)
    return out


def load_cache():
    """The reference cache; rebuilt when it is missing or one of its source files changed (UBE / 3BA update)."""
    rn, ro, t3_path, part_nifs = inputs()
    want = _signature([rn, ro, t3_path] + part_nifs)
    if os.path.exists(CACHE):
        try:
            with np.load(CACHE) as z:
                ref = {k: z[k] for k in z.files}
            if "sig" in ref and list(ref["sig"]) == list(want):
                return ref
        except (OSError, ValueError, KeyError):
            pass
    return build_cache()


# ------------------------------------------------------------------ per-outfit field
class Field:
    def __init__(self, ref, body_points, w, extra_radius=1.5, max_body_dev=5.0, fixed=None, t3_exclude=None):
        """fixed = (points, displacements) supplied by the caller (e.g. high-heel feet);
        t3_exclude = boolean mask over ref["T3"] of fill points never to use."""
        R, RF = ref["R"], ref["RF"]
        pts, disp = [], []
        if fixed is not None and len(fixed[0]):
            pts.append(fixed[0])
            disp.append(fixed[1])
        all_body = np.vstack([body_points] + ([fixed[0]] if fixed is not None and len(fixed[0]) else []))
        self.body_fit = None
        if len(body_points):
            tri, bary, dist = project(body_points, R, RF)
            self.body_fit = dist
            good = dist <= max_body_dev           # ignore body bits the reference cannot match
            body_points, tri, bary = body_points[good], tri[good], bary[good]
            pts.append(body_points)
            disp.append(interp(ref[f"Rt{w}"], RF, tri, bary) - body_points)
        if len(all_body):
            d, _ = knn(all_body, ref["T3"])
            keep = d[:, 0] > extra_radius        # body regions the outfit author trimmed away
        else:
            keep = np.ones(len(ref["T3"]), dtype=bool)
        if t3_exclude is not None:
            keep &= ~t3_exclude
        pts.append(ref["T3"][keep])
        disp.append(ref[f"T3t{w}"][keep] - ref["T3"][keep])
        self.points = np.vstack(pts)
        self.disp = np.vstack(disp)
        self.n_body, self.n_extra = len(all_body), int(keep.sum())

    def __call__(self, P, k=8):
        d, I = knn(self.points, P, k)
        wgt = 1.0 / (d ** 2 + 1e-4)
        return (self.disp[I] * wgt[..., None]).sum(1) / wgt.sum(1, keepdims=True)
