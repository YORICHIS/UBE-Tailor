# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""UBE Tailor health check: looks for every problem we have met so far, and knows the fix for each one.

  python tailor.py doctor [--fix] [--deep]

Each finding has a level:
  fix   the Tailor can repair it itself ("Fix all" / --fix)
  you   needs a step from the user (Batch Build in BodySlide, ticking a plugin while MO2 is open)
  info  nothing to repair, just to know (pieces the mod ships in the old LE format, meshes the mod never shipped)
and, for "fix", the action that repairs it: convert (re-make the projects), qa (grade them), repoint (rebuild
UBE Tailor.esp so it points at the built meshes and never at a mesh that does not exist), loadorder.
--deep also opens every converted HDT-SMP project to look for physics bones that would fall (slow).
"""
import os
import time

import env
import make_projects as mp
import merged_patch
import repoint_armas
import tailor_core as tc
from plugin_lib import enabled_plugins
from resolve_mesh import Resolver


class Finding:
    def __init__(self, key, level, title, items=(), action=None):
        self.key, self.level, self.title, self.items, self.action = key, level, title, list(items), action

    def __repr__(self):
        return f"[{self.level}] {self.title}"


def built_meshes():
    """{'<path>_1.nif' lower, relative to meshes\\!UBE: modified time} of every UBE mesh on disk."""
    out = {}
    for base in env.loose_dirs():
        d = os.path.join(base, "meshes", "!UBE")
        if not os.path.isdir(d):
            continue
        for dp, _dn, fn in os.walk(d):
            for f in fn:
                if f.lower().endswith(".nif"):
                    rel = os.path.relpath(os.path.join(dp, f), d).lower()
                    out.setdefault(rel, os.path.getmtime(os.path.join(dp, f)))   # first = highest priority
    return out


def _load_order_ok(fname):
    """(enabled, masters missing, masters loading after it) for a merged patch file."""
    on = {p.lower() for p in enabled_plugins()}
    lo = merged_patch.load_order()
    _fl, _cn, masters = merged_patch.tes4_info(os.path.join(mp.MOD, fname))
    me = lo.get(fname.lower())
    missing = [m for m in masters if m.lower() not in on and m.lower() not in lo]
    late = [m for m in masters if me is not None and lo.get(m.lower(), -1) > me]
    return fname.lower() in on, missing, late


def check(deep=False, log=None):
    say = log or (lambda s: None)
    t0 = time.time()
    out = []
    say("checking the outfits...")
    items = tc.scan()
    db = tc.load_db()
    conv = [i for i in items if i["state"] in ("built", "done")]

    lo = tc.left_out(items)
    if lo:
        out.append(Finding("left_out", "fix", f"{len(lo)} piece(s) left out of outfits you converted - still 3BA, "
                           "they sink into or float over the UBE body", [i["base"] for i in lo], "convert"))
    old = tc.outdated(items)
    if old:
        out.append(Finding("outdated", "fix", f"{len(old)} piece(s) converted with an older version of the Tailor",
                           [i["base"] for i in old], "convert"))

    changed = []
    for i in conv:
        sig = db.get(i["set"], {}).get("src")
        if not sig:
            continue
        try:
            st = os.stat(sig[0])
            now = [os.path.normcase(sig[0]), int(st.st_mtime), st.st_size]
        except OSError:
            now = None
        if now != sig:
            changed.append(i["base"])
    if changed:
        out.append(Finding("source_changed", "fix", f"{len(changed)} piece(s) whose mod changed (updated or removed) "
                           "the original mesh after it was converted", changed, "convert"))

    if deep:
        say("checking HDT-SMP physics bones...")
        res, falling, theirs = Resolver(), [], []
        ref_shapes = {r.shape for r in mp.load_refs()}
        proj_src = tc.project_sources()
        for i in conv:
            folder = os.path.join(mp.BS, "ShapeData", mp.safe(i["set"]))
            if not os.path.isdir(folder):
                continue
            for f in os.listdir(folder):
                if not f.lower().endswith(".nif"):
                    continue
                now = {(s, b) for s, b in mp.smp_falling(os.path.join(folder, f), res) if s not in ref_shapes}
                if not now:
                    continue
                src = next((p for p in (os.path.join(mp.WORK, "meshes", i["base"] + w) for w in ("_1.nif", "_0.nif"))
                            if os.path.isfile(p)), proj_src.get(i["base"].lower()))
                if src and now <= mp.smp_falling(src, res):
                    theirs.append(i["base"])         # the same bones fall in the mod's own mesh: its design
                else:
                    falling.append(i["base"])
                break
        if falling:
            out.append(Finding("smp", "fix", f"{len(falling)} HDT-SMP piece(s) where the conversion added physics "
                               "bones that would fall (head on the floor, legs melting)", falling, "convert"))
        if theirs:
            out.append(Finding("smp_mod", "info", f"{len(theirs)} HDT-SMP piece(s) whose own physics XML leaves some "
                               "bones undeclared, exactly like the mod's original mesh (not caused by the Tailor)",
                               theirs))

    if deep:
        say("checking the morph-file entries (BODYTRI)...")
        import bodytri
        dup = []
        for base in env.loose_dirs():
            d = os.path.join(base, "meshes", "!UBE")
            if not os.path.isdir(d):
                continue
            for dp, _dn, fn in os.walk(d):
                for f in fn:
                    if f.lower().endswith(".nif"):
                        p = os.path.join(dp, f)
                        try:
                            if bodytri.fix_built(p, save=False):
                                dup.append(p)
                        except Exception:
                            pass
        if dup:
            out.append(Finding("bodytri", "fix", f"{len(dup)} built mesh(es) read an old 3BA morph file first - they "
                               "will not follow OBody / RaceMenu body presets (the body grows through them)",
                               dup, "bodytri"))

    ungraded = [i for i in conv if "motion" not in db.get(i["set"], {}).get("qa", {})]
    if ungraded:
        out.append(Finding("ungraded", "fix", f"{len(ungraded)} converted piece(s) not graded yet (fit and moving)",
                           [i["set"] for i in ungraded], "qa"))

    say("checking what BodySlide has built...")
    built = built_meshes()
    unbuilt, stale = [], []
    for i in conv:
        rel = (i["base"] + "_1.nif").lower()
        osp = tc.osp_of(i["base"])
        if rel not in built:
            unbuilt.append(i["base"])
        elif os.path.exists(osp) and built[rel] < os.path.getmtime(osp) - 1:
            stale.append(i["base"])
    if unbuilt or stale:
        out.append(Finding("batch_build", "you", f"Batch Build needed in BodySlide: {len(unbuilt)} project(s) never "
                           f"built, {len(stale)} built before their last conversion (until then the game keeps the "
                           "older mesh)", unbuilt + stale))

    say("checking the patch...")
    conv_set = repoint_armas.converted_set()
    to_new = gone = 0
    for _label, data, _file, _foreign in tc._all_armas():
        if _file:
            continue                                   # outfit mods not in the patch yet: counted below
        m3 = tc.arma_info(data)[1]
        if not m3:
            continue
        key = m3.replace("/", "\\").lower()
        if key.startswith("!ube\\"):
            gone += key[5:] not in conv_set
        else:
            to_new += key in conv_set
    add = len({i["file"] for i in items if i.get("file") and i["state"] == "built"})
    st = merged_patch.load_state()
    add += len({i["foreign"] for i in items if i.get("foreign") and i["state"] == "built"
                and i["foreign"].lower() not in (p.lower() for p in st["foreign"])})
    if to_new or gone or add:
        out.append(Finding("patches", "fix", f"UBE Tailor.esp is out of date: {to_new} piece(s) can switch to their "
                           f"built UBE mesh, {gone} point at a UBE mesh that does not exist (invisible piece), {add} "
                           "outfit mod(s) with converted pieces are not in it yet", [], "repoint"))
    if not env.output_mod_enabled() and (conv or merged_patch.merged_files()):
        out.append(Finding("output_mod", "fix" if env.can_edit_profile() else "you",
                           f"The mod '{os.path.basename(env.OUT_MOD)}' (projects + patch) is not enabled in MO2 - "
                           "BodySlide and the game do not see it", [os.path.basename(env.OUT_MOD)], "loadorder"))

    can_edit = env.can_edit_profile()
    for f in merged_patch.merged_files():
        enabled, missing, late = _load_order_ok(f)
        if missing:
            out.append(Finding("merged_masters", "fix", f"{f} needs {len(missing)} plugin(s) that are no longer "
                               f"enabled ({', '.join(missing[:3])}) - the game would crash", missing, "repoint"))
        if not enabled or late:
            why = "is not enabled" if not enabled else f"loads before {', '.join(late[:3])}"
            out.append(Finding("loadorder", "fix" if can_edit else "you",
                               f"{f} {why} - it must be ticked and at the bottom of the load order", [f], "loadorder"))

    graded = [(i, db.get(i["set"], {}).get("qa", {})) for i in conv]
    bad_fit = [i["base"] for i, q in graded if q.get("grade") == "C"]
    bad_move = [i["base"] for i, q in graded if q.get("motion") == "C"]
    if bad_fit or bad_move:
        out.append(Finding("review", "info", f"to look at in game: {len(bad_fit)} piece(s) with fit C, "
                           f"{len(bad_move)} with moving C (the Fit column shows them)", bad_fit + bad_move))
    counts = {k: sum(1 for i in items if i["state"] == k) for k in ("oldrim", "missing", "nosupport")}
    if any(counts.values()):
        out.append(Finding("cannot", "info", f"cannot be converted: {counts['oldrim']} old Skyrim LE mesh(es) "
                           f"(port them to SE first), {counts['missing']} mesh(es) the mod never shipped (invisible "
                           f"in game anyway), {counts['nosupport']} single-weight mesh(es) (not supported yet)"))
    say(f"health check done in {time.time() - t0:.0f} s")
    return out


def fix(findings, preset=None, workers=6, log=print, stop=None):
    """Run every 'fix' action of the findings, in the order that works: convert, grade, patches, load order."""
    if tc.running("SkyrimSE.exe"):
        log("The game is running. Close it first.")
        return False
    todo = [f for f in findings if f.level == "fix"]
    bases = list(dict.fromkeys(b for f in todo if f.action == "convert" for b in f.items))
    made = []
    if bases:
        log(f"converting {len(bases)} piece(s)...")
        made, failed = tc.convert(bases, workers, None, stop)
        log(f"   converted {len(made)}, failed {len(failed)}")
        for b, e in failed[:10]:
            log(f"   failed: {b}  {e[:140]}")
    sets = list(dict.fromkeys(made + [s for f in todo if f.action == "qa" for s in f.items]))
    preset = preset or env.preset()
    if sets and preset and not (stop and stop()):
        log(f"grading {len(sets)} piece(s)...")
        tc.qa(sets, preset, workers, None, stop)
    dup = [p for f in todo if f.action == "bodytri" for p in f.items]
    if dup:
        import bodytri
        n = sum(1 for p in dup if bodytri.fix_built(p))
        log(f"   {n} built mesh(es) now read their UBE morph file")
    if bases or any(f.action == "repoint" for f in todo):
        log("updating the patches...")
        for line in tc.repoint(False).strip().splitlines()[-2:]:
            log("   " + line)
    if any(f.action == "loadorder" for f in todo):
        files = merged_patch.merged_files()
        if merged_patch.place_in_load_order(files):
            log(f"   mod '{os.path.basename(env.OUT_MOD)}' enabled, " + (", ".join(files) or "no plugin yet")
                + " ticked at the end of the load order")
        else:
            log(f"   MO2 is open: press F5 in MO2, enable the mod '{os.path.basename(env.OUT_MOD)}', tick "
                + ", ".join(files) + " and keep it at the bottom")
    if bases:
        log("Next: Batch Build in BodySlide, then Scan here.")
    return True
