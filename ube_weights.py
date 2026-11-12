# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Copy UBE body/feet/hands bone weights onto conformed outfit shapes (Outfit Studio "Copy Bone Weights").

Per outfit vertex: weights = IDW of the k nearest UBE reference vertices' weights. Close to the body
(<= NEAR) the UBE weights are used fully; beyond FAR the author's weights are kept; linear blend between.
Bones the UBE body does not have (SMP/physics bones etc.) keep their original weight share.
At most 4 bones per vertex (Skyrim SE limit). Positions, other shapes and all other blocks are untouched.
"""
import ctypes

import numpy as np

from nifly_env import NifFile, knn
from smp_check import has_smp

NEAR, FAR, K, MAXB = 2.0, 8.0, 8, 4
_cache = {}


def _copy(buf):
    new = type(buf)()
    ctypes.pointer(new)[0] = buf
    return new


def ref_weights(refs):
    """(bone list, dense weights stacked body+feet+hands, skin-to-bone per bone, (node xform, parent) per bone)."""
    key = tuple(r.nif for r in refs)
    if key in _cache:
        return _cache[key]
    bones, stb, node, mats = [], {}, {}, []
    files = [NifFile(r.nif) for r in refs]
    for f in files:
        s = f.shapes[0]
        for b in s.bone_names:
            if b in stb:
                continue
            bones.append(b)
            stb[b] = _copy(s.get_shape_skin_to_bone(b))
            n = f.nodes.get(b)
            parent = n.parent.name if n is not None and n.parent is not None else None
            node[b] = (_copy(n.transform) if n is not None else None,
                       parent if parent and parent != f.rootNode.name else None)
    col = {b: i for i, b in enumerate(bones)}
    for f in files:
        s = f.shapes[0]
        M = np.zeros((len(s.verts), len(bones)))
        for b, lst in s.bone_weights.items():
            for vi, w in lst:
                M[vi, col[b]] += w
        mats.append(M)
    _cache[key] = (bones, np.vstack(mats), stb, node)
    return _cache[key]


def _is_plain(xf):
    R = np.array([xf.rotation[i][:] for i in range(3)])
    return np.allclose(R, np.eye(3), atol=1e-4) and abs(xf.scale - 1) < 1e-4


def _shift_stb(xf, t):
    """skin-to-bone for a shape whose skin space is global + t (from a reference with identity global-to-skin)."""
    out = _copy(xf)
    R = np.array([xf.rotation[i][:] for i in range(3)])
    T = np.array(xf.translation[:]) - xf.scale * R @ t
    for i in range(3):
        out.translation[i] = float(T[i])
    return out


def copy_weights(nif_path, targets, refs, upos, log=None):
    """Rewrite bone weights of shapes `targets` in nif_path. upos = reference vertex positions (one array per ref,
    same order as refs, e.g. heel-posed feet). Returns {shape: (verts fully UBE-weighted, verts blended)}."""
    bones, UW, stb, node = ref_weights(refs)
    U = np.vstack(upos)
    ube_set = set(bones)
    # HDT-SMP: a bone the physics XML does not know is created as a free rigid body and falls to the floor
    # (see smp_check.py), so shapes of a nif with an SMP XML may only keep the bones the author gave them.
    smp = has_smp(nif_path)
    # nifly's setShapeBoneWeights merges into existing weights and zero entries can crowd out real ones
    # (4 per vertex) on save, so first wipe every target shape's weights, save, and reopen.
    nif = NifFile(nif_path)
    old = {}
    for name in targets:
        s = nif.shape_dict.get(name)
        if s is None or not s.bone_names or not _is_plain(s.global_to_skin):
            if s is not None and s.bone_names and log:
                log(f"   weights: skipped {name} (rotated/scaled skin transform)")
            continue
        bw = s.bone_weights
        names = list(s.bone_names)
        stb_old = {bn: s.get_shape_skin_to_bone(bn) for bn in names}
        # a bone whose skin data cannot be read (broken or cut-off bone name, e.g. "NPC R UpperarmTwist1 [RUt1")
        # and that the UBE body does not have either could not be written back: keep the author's weights here
        lost = [bn for bn in names if stb_old[bn] is None and bn not in stb]
        if lost:
            if log:
                log(f"   weights: kept the author's weights on {name} (no skin data for bone(s) {', '.join(lost[:3])})")
            continue
        nodes_old = {}
        for bn in names:
            n = nif.nodes.get(bn)
            par = n.parent.name if n is not None and n.parent is not None else None
            nodes_old[bn] = (_copy(n.transform) if n is not None else None,
                             par if par and par != nif.rootNode.name else None)
        old[name] = (bw, names, {bn: _copy(x) for bn, x in stb_old.items() if x is not None}, nodes_old,
                     _copy(s.global_to_skin))
        for b, lst in bw.items():
            s.setShapeWeights(b, [(i, 0.0) for i, _w in lst])
    nif.save()
    nif = NifFile(nif_path)
    report = {}
    for name in targets:
        s = nif.shape_dict.get(name)
        if s is None or name not in old:
            continue
        old_w, old_bones, old_stb, old_nodes, g2s = old[name]
        if not _is_plain(g2s):
            if log:
                log(f"   weights: skipped {name} (rotated/scaled skin transform)")
            continue
        t = np.array(g2s.translation[:], dtype=np.float64)
        P = np.array(s.verts, dtype=np.float64) - t
        allb = old_bones + [b for b in bones if b not in old_bones]
        col = {b: i for i, b in enumerate(allb)}
        O = np.zeros((len(P), len(allb)))
        for b, lst in old_w.items():
            for vi, w in lst:
                O[vi, col[b]] += w

        d, I = knn(U, P, K)
        w = 1.0 / (d ** 2 + 1e-4)
        w /= w.sum(1, keepdims=True)
        C = np.zeros_like(O)
        C[:, [col[b] for b in bones]] = (UW[I] * w[..., None]).sum(1)
        custom = [col[b] for b in old_bones if b not in ube_set]
        keep = np.clip(O[:, custom].sum(1), 0, 1) if custom else np.zeros(len(P))
        body_old = O.copy()
        body_old[:, custom] = 0
        alpha = np.clip((FAR - d[:, 0]) / (FAR - NEAR), 0, 1)
        if smp:
            C[:, len(old_bones):] = 0.0                  # no bone the author did not use
            left = C.sum(1)
            ok = left > 0.05
            C[ok] /= left[ok, None]
            alpha = np.where(ok, alpha, 0.0)             # nothing usable -> keep the author's weights
        N = alpha[:, None] * C * (1 - keep)[:, None] + (1 - alpha)[:, None] * body_old
        if custom:
            N[:, custom] = O[:, custom]
        drop = np.argsort(-N, 1)[:, MAXB:]
        np.put_along_axis(N, drop, 0.0, 1)
        N[N < 1e-3] = 0.0
        tot = N.sum(1, keepdims=True)
        bad = tot[:, 0] <= 0
        N = np.where(bad[:, None], O, N / np.where(tot > 0, tot, 1))

        if bad.any():   # rotated skin shapes are skipped above, so this is only a no-weight safety net
            N[bad] = O[bad]
        used = [b for b in allb if N[:, col[b]].max() > 0]
        new_bones = [b for b in used if b not in old_bones]
        have = set(s.bone_names)
        for b in old_bones + new_bones:          # re-add any bone nifly dropped when the wipe was saved
            if b not in have:
                xf, parent = old_nodes.get(b) or node[b]
                s.add_bone(b, xf, parent)
        for b in old_bones + new_bones:
            x = old_stb.get(b)
            if x is None:
                x = stb[b] if not t.any() else _shift_stb(stb[b], t)
            s.set_skin_to_bone_xform(b, x)
            c = col[b]
            nz = np.nonzero(N[:, c])[0]
            s.setShapeWeights(b, [(int(i), float(N[i, c])) for i in nz])
        report[name] = (int((alpha >= 1).sum()), int(((alpha > 0) & (alpha < 1)).sum()))
    nif.save()
    return report
