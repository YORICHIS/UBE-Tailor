# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""UBE Tailor core: find 3BA outfits, turn them into UBE BodySlide projects in parallel, grade the fit,
and patch the plugins so UBE races use the converted meshes.

Used by tailor.py (command line) and tailor_gui.pyw (window). BodySlide itself does the final Batch Build.
"""
import json
import multiprocessing
import os
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET

import numpy as np

import make_projects as mp
import ube_field
from collections import Counter

import env
from nifly_env import NifFile, knn
from plugin_lib import enabled_plugins, plugin_locations, read_plugin, subrecords, zstr
from resolve_mesh import Resolver

DB = os.path.join(env.WORK, "tailor_db.json") if env.WORK else None
NORD = 0x00013746                      # NordRace: an armor addon that Nords can wear is one UBE races can wear
UBE_PLUGIN = env.UBE_PLUGIN
UBE_RACE_RX = re.compile(r"^00UBE_(Breton|Imperial|Nord|Redguard|DarkElf|HighElf|WoodElf|Orc)Race(Vampire)?$", re.I)
GRADES = {"A": "Excellent", "B": "OK", "C": "Needs review"}
STATES = {"pending": "Not converted", "built": "Project ready (needs patch)", "done": "Done",
          "native": "Native UBE", "nosupport": "Not supported", "head": "Head piece (skipped)",
          "oldrim": "Old LE mesh (port to SE first)", "missing": "Mesh missing in the mod"}


KINDS = {"clothing": "Clothing only", "jewelry": "Jewelry & tails", "device": "Bondage devices",
         "body": "NPC body parts"}


def kind_of(base, slots, plugin):
    """Rough item type, so the list can show clothing only: by mesh folder, biped slots and plugin name."""
    low, s, pl = base.lower(), set(slots), plugin.lower()
    if low.startswith("actors\\"):
        return "body"
    if low.startswith(("devious\\", "zaz")) or "devious" in pl or "zaz" in pl:
        return "device"
    if s and (s <= {35, 36} or s <= {40}):
        return "jewelry"
    return "clothing"


def set_name_of(base):
    return "UBE Auto - " + base.replace("/", "\\").replace("\\", " - ")


def osp_of(base):
    return os.path.join(mp.BS, "SliderSets", mp.safe(set_name_of(base)) + ".osp")


def running(exe):
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"], capture_output=True, text=True,
                             creationflags=0x08000000).stdout
    except OSError:
        return False
    return exe.lower() in out.lower()


# ---------------------------------------------------------------- database (heel flag, log line, QA per project)
def load_db():
    try:
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_db(db):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    tmp = DB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=0)
    os.replace(tmp, DB)


# ---------------------------------------------------------------- scan
def arma_info(data):
    flags, m3, edid, rnam, races = 0, None, "", None, []
    for t, x in subrecords(data):
        if t in (b"BOD2", b"BODT"):
            flags = struct.unpack_from("<I", x)[0]
        elif t == b"MOD3":
            m3 = zstr(x)
        elif t == b"EDID":
            edid = zstr(x)
        elif t == b"RNAM" and len(x) == 4:
            rnam = struct.unpack("<I", x)[0]
        elif t == b"MODL" and len(x) == 4:
            races.append(struct.unpack("<I", x)[0])
    return edid, m3, {i + 30 for i in range(32) if flags >> i & 1}, rnam, races


def merged_files():
    import merged_patch
    return merged_patch.merged_files()


_RES = {}


def mesh_exists(base):
    """True if the game can find the outfit mesh (_1 or _0, loose or in a loaded BSA). One resolver per scan."""
    r = _RES.get("r")
    if r is None:
        r = _RES["r"] = Resolver()
    return any(r.resolve(base + s)[0] for s in ("_1.nif", "_0.nif"))


def outdated(items):
    """Converted pieces whose project was made with an older conversion method (make_projects.METHOD)."""
    return [i for i in items if i.get("outdated")]


def outfit_mates(chosen, items):
    """Not-yet-converted pieces of the same outfits (mesh folders) as the chosen ones, so a conversion always
    covers the whole outfit: a 3BA piece worn over the UBE body sinks in or floats."""
    folders = {os.path.dirname(i["base"]).lower() for i in chosen}
    have = {i["base"].lower() for i in chosen}
    return [i for i in items if i["state"] == "pending" and i["base"].lower() not in have
            and os.path.dirname(i["base"]).lower() in folders]


def to_fix(items):
    """Everything the Tailor should fix on its own: pieces left out of converted outfits + outdated projects."""
    return left_out(items) + outdated(items)


def left_out(items):
    """Pieces not converted although another piece of the same outfit (same mesh folder) is: worn together, the
    3BA one no longer fits the UBE body under it (it sinks in or floats). Returns the items."""
    folder = lambda i: os.path.dirname(i["base"]).lower()
    started = {folder(i) for i in items if i["state"] in ("built", "done")}
    return [i for i in items if i["state"] == "pending" and folder(i) in started]


def slot53_models(path):
    """Models (lower case) of an outfit plugin whose body piece must not carry UBE's extra slot 53: the plugin has
    its own slot-53 piece (pants, leggings) and its original armor addon with that model has no slot 53. Worn
    together, two pieces on slot 53 make the game hide one of them."""
    ms, recs = read_plugin(path, {b"ARMA"})
    bod = lambda d: next((struct.unpack_from("<I", x)[0] for t, x in subrecords(d) if t in (b"BOD2", b"BODT")), 0)
    own = [d for _s, fid, d, _fl in recs if fid >> 24 >= len(ms)]
    if not any(bod(d) & 1 << 23 and not bod(d) & 4 for d in own):
        return set()
    out = set()
    for d in own:
        if bod(d) & 4 and not bod(d) & 1 << 23:
            m3 = next((zstr(x) for t, x in subrecords(d) if t == b"MOD3"), "")
            if m3:
                out.add(m3.replace("/", "\\").lower())
    return out


def foreign_armas(aware=None):
    """UBE armor addons that OTHER UBE patches add to outfit mods (e.g. made with UBE's xEdit script, or a mod's own
    UBE patch): [dict(patch, path, ms, src, fid, data, flags)] - fid as numbered inside that patch, src = the outfit
    plugin whose armor the patch overrides. The Tailor never edits those patches: UBE Tailor.esp overrides their
    armor addons (merged_patch.foreign_overrides) once the converted mesh is built."""
    if aware is None:
        _cov, aware = covered_armos()
    ours = {f.lower() for f in merged_files()}
    loc = plugin_locations()
    names = {p.lower(): p for p in enabled_plugins()}
    out = []
    for low in sorted(aware - ours - {UBE_PLUGIN.lower()}):
        path = loc.get(low)
        if not path:
            continue
        try:
            ms, recs = read_plugin(path, {b"ARMO", b"ARMA"})
        except Exception:
            continue
        lms = [m.lower() for m in ms]
        if UBE_PLUGIN.lower() not in lms:
            continue
        ui, n = lms.index(UBE_PLUGIN.lower()), len(ms)
        armas = {fid: (d, fl) for sig, fid, d, fl in recs if sig == b"ARMA"}
        src_of = {}
        for sig, fid, d, _fl in recs:
            if sig != b"ARMO" or fid >> 24 >= n:
                continue                                  # only the armors of other plugins it overrides
            for t, x in subrecords(d):
                if t == b"MODL" and len(x) == 4:
                    a = struct.unpack("<I", x)[0]
                    if a in armas:
                        src_of.setdefault(a, ms[fid >> 24])
        for a, src in src_of.items():
            d, fl = armas[a]
            _e, m3, _slots, rnam, races = arma_info(d)
            if not m3 or rnam is None or rnam >> 24 != ui:
                continue                                  # not an armor addon for the UBE races
            out.append(dict(patch=names.get(low, os.path.basename(path)), path=path, ms=ms, src=src, fid=a,
                            data=d, flags=fl))
    return out


def _all_armas():
    """(source plugin label, armor addon data, plugin file or None, other UBE patch or None) of every outfit piece the
    Tailor knows: the UBE copies in the merged patch, the UBE armor addons of other UBE patches (as UBE Tailor.esp
    overrides them, if it does), and the armor addons of outfit mods no UBE patch covers yet (file = that mod)."""
    import merged_patch
    for label, data in merged_patch.scan_records():
        yield label, data, None, None
    cov, aware = covered_armos()
    over = merged_patch.override_records()
    for f in foreign_armas(aware):
        key = merged_patch.owner_key(f["ms"], f["patch"], f["fid"])
        yield os.path.splitext(f["src"])[0], over.get(key, f["data"]), None, f["patch"]
    for name, (path, todo) in find_new_plugins(covered=(cov, aware)).items():
        want = {a for _o, al in todo for a in al}
        ms, recs = read_plugin(path, {b"ARMA"})
        for _sig, fid, data, _fl in recs:
            if fid >> 24 >= len(ms) and fid & 0xFFFFFF in want:
                yield os.path.splitext(name)[0], data, name, None


def _patch_armas():
    for label, data, _file, _foreign in _all_armas():
        yield label, data


def scan():
    """Every outfit mesh UBE races should wear -> list of items (one per mesh base), with its state.
    item["file"] = the outfit plugin when it is not in the merged patch yet (repoint() adds it once converted);
    item["foreign"] = the other UBE patch whose armor addon UBE races use for it."""
    items = {}
    for plugin, data, pfile, foreign in _all_armas():
        edid, m3, slots, _r, _a = arma_info(data)
        if not m3 or (slots and slots <= mp.HEAD_SLOTS):
            continue
        path = m3.replace("/", "\\")
        ube = path.lower().startswith("!ube\\")
        if ube:
            path = path[5:]
        mo = re.match(r"(.*)_[01]\.nif$", path, re.I)
        base = mo.group(1) if mo else path
        it = items.get(base.lower())
        if it is None:
            it = items[base.lower()] = {"base": base, "plugin": plugin, "edids": [], "slots": set(),
                                        "weighted": bool(mo), "ube_all": True, "ube_any": False, "file": pfile,
                                        "foreign": foreign}
        it["edids"].append(edid)
        it["slots"] |= slots
        it["ube_all"] &= ube
        it["ube_any"] |= ube
    out = []
    db = load_db()
    _RES.clear()                          # mods may have changed since the last scan
    for it in items.values():
        it["set"] = set_name_of(it["base"])
        proj = it["weighted"] and os.path.exists(osp_of(it["base"]))
        if proj:
            it["state"] = "done" if it["ube_all"] else "built"
        elif it["ube_any"]:
            it["state"] = "native"       # a UBE mesh from another mod (installed by the user): never touched
        elif db.get(it["set"], {}).get("head"):
            it["state"] = "head"         # converting found it sits above the neck only
        elif db.get(it["set"], {}).get("oldrim"):
            it["state"] = "oldrim"       # the mod ships a Skyrim LE mesh
        elif db.get(it["set"], {}).get("missing") and not mesh_exists(it["base"]):
            it["state"] = "missing"      # the mod points at a mesh it never shipped (checked again each scan)
        else:
            it["state"] = "pending" if it["weighted"] else "nosupport"
        it["outdated"] = it["state"] in ("built", "done") and db.get(it["set"], {}).get("method", 0) < mp.METHOD
        it["slots"] = sorted(it["slots"])
        it["kind"] = kind_of(it["base"], it["slots"], it["plugin"])
        out.append(it)
    out.sort(key=lambda i: (i["plugin"].lower(), i["base"].lower()))
    return out


# ---------------------------------------------------------------- new outfits: plugins the patches do not cover
def covered_armos(exclude=()):
    """(armors some UBE-aware plugin already overrides, plugins that are UBE-aware themselves).
    UBE-aware = has UBE_AllRace.esp as master: our patches, and the UBE patches of outfits the user installed.
    exclude = lower-case plugin names to ignore (the merged patch while it is being rebuilt)."""
    cov, aware = set(), set()
    loc = plugin_locations()
    paths = {f.lower(): os.path.join(mp.MOD, f) for f in merged_files()}
    for name in enabled_plugins():
        if name.lower() in loc:
            paths.setdefault(name.lower(), loc[name.lower()])
    for low in exclude:
        paths.pop(low, None)
    for low, path in paths.items():
        try:
            ms, recs = read_plugin(path, {b"ARMO"})
        except Exception:
            continue
        if UBE_PLUGIN.lower() not in (m.lower() for m in ms):
            continue
        aware.add(low)
        for _sig, fid, _data, _fl in recs:
            if fid >> 24 < len(ms):
                cov.add((ms[fid >> 24].lower(), fid & 0xFFFFFF))
    return cov, aware


def patchable(path, name, cov):
    """[(armo object id, [arma object ids])] of this plugin's own playable armors that no UBE patch covers."""
    ms, recs = read_plugin(path, {b"ARMO", b"ARMA"})
    n = len(ms)
    armas = {fid & 0xFFFFFF: data for sig, fid, data, _fl in recs if sig == b"ARMA" and fid >> 24 >= n}
    out = []
    for sig, fid, data, fl in recs:
        if sig != b"ARMO" or fid >> 24 < n or fl & 0x4 or (name.lower(), fid & 0xFFFFFF) in cov:
            continue
        ok = []
        for t, x in subrecords(data):
            if t != b"MODL" or len(x) != 4:
                continue
            a = struct.unpack("<I", x)[0]
            d = armas.get(a & 0xFFFFFF) if a >> 24 >= n else None
            if d is None:
                continue
            _edid, m3, _slots, rnam, races = arma_info(d)
            if m3 and (rnam == NORD or NORD in races):
                ok.append(a & 0xFFFFFF)
        if ok:
            out.append((fid & 0xFFFFFF, ok))
    return out


def find_new_plugins(log=None, covered=None):
    """{plugin file name: (path, todo)} for enabled plugins with armors usable by UBE but no UBE patch yet.
    covered = covered_armos() when the caller has it already."""
    cov, aware = covered or covered_armos()
    loc = plugin_locations()
    import merged_patch
    have = {os.path.splitext(p)[0].lower() for p in merged_patch.load_state()["plugins"]}
    cache_path = os.path.join(env.WORK, "tailor_plugins.json")
    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    found = {}
    for name in enabled_plugins():
        low = name.lower()
        if low in aware or low == UBE_PLUGIN.lower() or os.path.splitext(low)[0] in have:
            continue
        path = loc.get(low)
        if not path:
            continue
        st = os.stat(path)
        key = [st.st_mtime, st.st_size]
        c = cache.get(path)
        if c and c[0] == key and not c[1]:
            continue                      # known to hold no own wearable armors (whatever covers what)
        try:
            todo_all = patchable(path, name, set())
        except Exception as e:            # unreadable plugin: report, keep going
            if log:
                log(f"   could not read {name}: {e!r}")
            continue
        # the cache only says whether the plugin has armors at all: what other patches cover changes on its own
        cache[path] = [key, bool(todo_all)]
        todo = [(o, al) for o, al in todo_all if (low, o) not in cov]
        if todo:
            found[name] = (path, todo)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    return found


def ube_races():
    """(target race object id, [additional race object ids]) in UBE_AllRace.esp: 00UBE_BretonRace as the armor
    addon's race, the other playable UBE races (and their vampire versions) as additional races."""
    path = plugin_locations().get(UBE_PLUGIN.lower())
    if not path:
        raise RuntimeError(f"{UBE_PLUGIN} was not found. Install UBE 2.0 and enable its plugin.")
    ms, recs = read_plugin(path, {b"RACE"})
    found = {}
    for _sig, fid, data, _fl in recs:
        if fid >> 24 < len(ms):
            continue
        edid = next((zstr(x) for t, x in subrecords(data) if t == b"EDID"), "")
        if UBE_RACE_RX.match(edid):
            found[edid.lower()] = fid & 0xFFFFFF
    target = found.get("00ube_bretonrace")
    if target is None:
        raise RuntimeError(f"{UBE_PLUGIN} has no 00UBE_BretonRace - is it the UBE 2.0 race plugin?")
    return target, sorted(v for v in found.values() if v != target)


def _sub(t, x):
    if len(x) > 0xFFFF:
        return b"XXXX" + struct.pack("<HI", 4, len(x)) + t + struct.pack("<H", 0) + x
    return t + struct.pack("<H", len(x)) + x


def _rec(sig, fid, flags, data):
    return struct.pack("<4sIIIIHH", sig, len(data), flags & ~0x40000, fid, 0, 44, 0) + data


def _grup(label, body):
    return struct.pack("<4sI4sIII", b"GRUP", 24 + len(body), label, 0, 0, 0) + body


def backup_dir():
    return env.backup_dir()


def inside_mo2():
    return env.inside_mo2()


def repoint(dry=False, items=None):
    """Rebuild the merged patch: add the outfit mods that now have converted pieces, and point every UBE copy at
    its UBE mesh once BodySlide has built it (and back at the original while it is not built). Returns log text;
    its last line is the summary."""
    import merged_patch
    if items is None:
        items = scan()
    add = sorted({i["file"] for i in items if i.get("file") and i["state"] == "built"}, key=str.lower)
    add_f = sorted({i["foreign"] for i in items if i.get("foreign") and i["state"] == "built"}, key=str.lower)
    st = merged_patch.load_state()
    lines = [f"outfit mod(s) with converted pieces to add to the patch: {len(add)}"] if add else []
    if add_f:
        lines.append(f"other UBE patch(es) with converted pieces to override: {len(add_f)}")
    if dry:
        lines.append(f"(dry run) {len(st['plugins']) + len(add)} outfit mod(s) and "
                     f"{len(st['foreign']) + len(add_f)} other UBE patch(es) would be in the patch")
        return "\n".join(lines)
    if not (add or add_f or st["plugins"] or st["foreign"]):
        lines.append("Nothing to patch yet: convert some outfits first.")
        return "\n".join(lines)
    res = merged_patch.build(add=add, add_foreign=add_f, log=lines.append)
    placed = merged_patch.place_in_load_order([r[0] for r in res])
    summary = "patch rebuilt: " + ", ".join(f"{f} ({n} mods, {a} armor addons)" for f, n, _o, a, _m in res)
    if not placed:
        summary += (" - MO2 is open: close it and press Scan again, or press F5 in MO2, enable the mod '"
                    + os.path.basename(env.OUT_MOD) + "' and tick " + ", ".join(r[0] for r in res)
                    + " at the bottom of the load order")
    lines.append(summary)
    return "\n".join(lines)


# ---------------------------------------------------------------- convert (parallel)
_G = {}


def _init():
    _G["ref"] = ube_field.load_cache()
    _G["refs"] = mp.load_refs()
    _G["resolver"] = Resolver()


def _convert_one(job):
    base, src, slots = job
    lines = []
    try:
        name = mp.make_project(base, src, _G["ref"], _G["refs"], _G["resolver"], log=lines.append, slots=slots)
        return base, name, lines, None
    except mp.HeadPiece as e:
        return base, None, lines, "HEAD: " + str(e)
    except mp.OldrimMesh as e:
        return base, None, lines, "OLDRIM: " + str(e)
    except Exception as e:
        return base, None, lines, repr(e)


def project_sources():
    """{output mesh base, lower-case: source nif} of the 3BA/CBBE BodySlide projects in enabled mods.
    Used for outfits that were never built (the mod ships only the BodySlide project). Cached per mod list."""
    ml = os.path.join(env.PROFILE, "modlist.txt")
    st = os.stat(ml)
    key = [st.st_mtime, st.st_size]
    cache = os.path.join(env.WORK, "tailor_projects.json")
    try:
        with open(cache, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("key") == key:
            return c["map"]
    except (OSError, ValueError, KeyError):
        pass
    out = {}
    ours = os.path.normcase(os.path.join(mp.BS, "SliderSets"))
    for d in env.bodyslide_dirs("SliderSets"):     # highest priority first
        if os.path.normcase(d) == ours:
            continue
        for fn in os.listdir(d):
            if not fn.lower().endswith(".osp"):
                continue
            try:
                root = ET.parse(os.path.join(d, fn)).getroot()
            except (ET.ParseError, OSError):
                continue
            for ss in root.iter("SliderSet"):
                folder, srcf, op, of = (ss.findtext(k) for k in ("DataFolder", "SourceFile", "OutputPath", "OutputFile"))
                if not (folder and srcf and op and of):
                    continue
                op = op.strip().replace("/", "\\").strip("\\")
                op = op[7:] if op.lower().startswith("meshes\\") else ("" if op.lower() == "meshes" else op)
                if op.lower().startswith("!ube"):
                    continue                       # already a UBE project
                src = os.path.join(os.path.dirname(d), "ShapeData", folder, srcf)
                if os.path.isfile(src):
                    out.setdefault(os.path.join(op, of.strip()).lower(), src)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"key": key, "map": out}, f)
    return out


SRC_SIG = os.path.join(env.WORK, "tailor_sources.json") if env.WORK else None
SOURCE_SIGS = {}                         # base -> signature of the source used by the last prepare_sources()


def source_sig(resolver, base):
    """(kind, path, meshes-relative name, signature) of the mesh the game uses for an outfit: _1.nif, or _0.nif
    when the mod ships only that one. signature = [file, modified time, size] (the BSA's for a packed mesh), so a
    mod update shows as a changed signature. kind None when the game has neither."""
    for w in ("_1.nif", "_0.nif"):
        rel = base + w
        kind, src = resolver.resolve(rel)
        if kind:
            st = os.stat(src)
            return kind, src, rel, [os.path.normcase(src), int(st.st_mtime), st.st_size]
    return None, None, None, None


def prepare_sources(bases, log=None):
    """{base: source nif or None}. Each outfit's winning mesh is copied into work\\src, and copied again when the
    mod changed it (the copy is checked against the source's signature). Packed meshes are read straight out of
    their BSA. Outfits that were never built use their 3BA BodySlide project's source nif."""
    from resolve_mesh import read_from_bsa
    resolver = Resolver()
    try:
        with open(SRC_SIG, encoding="utf-8") as f:
            sigs = json.load(f)
    except (OSError, ValueError):
        sigs = {}
    srcs = {}
    for base in bases:
        kind, src, rel, sig = source_sig(resolver, base)
        srcs[base] = None
        if not kind:
            continue
        dst = os.path.join(mp.WORK, "meshes", rel)
        if not (os.path.isfile(dst) and sigs.get(rel.lower()) == sig):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if kind == "loose":
                shutil.copy2(src, dst)
            else:
                data = read_from_bsa(src, "meshes\\" + rel)
                if data is None:
                    if log:
                        log(f"could not read {rel} from {os.path.basename(src)}")
                    continue
                with open(dst, "wb") as f:
                    f.write(data)
            sigs[rel.lower()] = sig
        srcs[base] = dst
        SOURCE_SIGS[base] = sig
    with open(SRC_SIG, "w", encoding="utf-8") as f:
        json.dump(sigs, f)
    missing = [b for b in bases if not srcs[b]]
    if missing:
        if log:
            log(f"{len(missing)} outfit(s) were never built: looking for their 3BA BodySlide projects")
        proj = project_sources()
        for b in missing:
            srcs[b] = proj.get(b.lower())
            if srcs[b]:
                st = os.stat(srcs[b])
                SOURCE_SIGS[b] = [os.path.normcase(srcs[b]), int(st.st_mtime), st.st_size]
    return srcs


def _results(pool, fn, jobs, stop):
    """Results of pool.imap_unordered, checking the stop flag twice a second (terminates the pool on stop)."""
    it = pool.imap_unordered(fn, jobs)
    got = 0
    while got < len(jobs):
        try:
            res = it.next(timeout=0.5)
        except multiprocessing.TimeoutError:
            if stop and stop():
                pool.terminate()
                return
            continue
        got += 1
        yield res


def _pool(workers, init):
    for v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[v] = "2"               # workers run side by side; keep each one's math library small
    return multiprocessing.get_context("spawn").Pool(workers, initializer=init)


def convert(bases, workers=6, on=None, stop=None):
    """Make UBE projects for the mesh bases. on(i, total, base, set name or None, error or None, log lines)."""
    db = load_db()
    total = len(bases)
    srcs = prepare_sources(bases, log=(lambda s: on(0, total, s, None, None, [])) if on else None)
    # biped slots per piece (from the patches): a stocking that does not take the feet slot gets flat feet
    slot_map = {}
    for _plugin, data in _patch_armas():
        _e, m3, slots, _r, _a = arma_info(data)
        if m3:
            mo = re.match(r"(?:!ube\\)?(.*)_[01]\.nif$", m3.replace("/", "\\"), re.I)
            if mo:
                slot_map.setdefault(mo.group(1).lower(), set()).update(slots)
    made, failed, i = [], [], 0
    jobs = []
    for b in bases:
        if srcs.get(b):
            jobs.append((b, srcs[b], slot_map.get(b.lower())))
        else:                               # fail at once instead of letting a worker search for it
            i += 1
            msg = ("MISSING: the mod does not ship this mesh (no _1/_0 nif loose, in a BSA or as a BodySlide "
                   "project) - it is invisible in game too")
            db[set_name_of(b)] = {"base": b, "missing": True}
            if on:
                on(i, total, b, None, msg, [])
    if jobs:
        ube_field.load_cache()            # build the reference cache once here, not in every worker at the same time
        with _pool(max(1, min(workers, len(jobs))), _init) as pool:
            for base, name, lines, err in _results(pool, _convert_one, jobs, stop):
                i += 1
                if err and err.startswith("HEAD: "):
                    db[set_name_of(base)] = {"base": base, "head": True}     # listed as a head piece from now on
                elif err and err.startswith("OLDRIM: "):
                    db[set_name_of(base)] = {"base": base, "oldrim": True}   # listed as "old format" from now on
                elif err:
                    failed.append((base, err))
                else:
                    made.append(name)
                    line = next((l for l in lines if l.startswith("== ")), "")
                    db[name] = {"base": base, "heel": "HEELS" in line, "log": line, "method": mp.METHOD,
                                "src": SOURCE_SIGS.get(base)}      # to notice when the mod updates the mesh
                if on:
                    on(i, total, base, name, err, lines)
                if i % 25 == 0:
                    mp.write_group(made)
                    save_db(db)
    mp.write_group(made)
    save_db(db)
    return made, failed


# ---------------------------------------------------------------- quality check at a preset
def preset_dirs():
    return env.bodyslide_dirs("SliderPresets")


def list_presets():
    names = []
    for d in preset_dirs():
        for fn in os.listdir(d):
            if not fn.lower().endswith(".xml"):
                continue
            try:
                root = ET.parse(os.path.join(d, fn)).getroot()
            except ET.ParseError:
                continue
            for p in root.iter("Preset"):
                if any(g.get("name") == "UBE" for g in p.findall("Group")) and p.get("name") not in names:
                    names.append(p.get("name"))
    return sorted(names, key=str.lower)


def preset_values(name):
    for d in preset_dirs():
        for fn in os.listdir(d):
            if not fn.lower().endswith(".xml"):
                continue
            try:
                root = ET.parse(os.path.join(d, fn)).getroot()
            except ET.ParseError:
                continue
            for p in root.iter("Preset"):
                if p.get("name") == name:
                    pv = {}
                    for s in p.iter("SetSlider"):
                        pv.setdefault(s.get("name"), {})[s.get("size")] = float(s.get("value"))
                    return pv
    raise KeyError(name)


def _slider_value(attrs, pv, size):
    v = pv.get(attrs.get("name"), {}).get(size, float(attrs.get(size, 0) or 0))
    return 100 - v if attrs.get("invert") == "true" else v


def body_surface(refs, pv, w, heel):
    """UBE body + feet + hands at the preset (weight w), as one triangle surface with face normals."""
    size = "big" if w else "small"
    SV, SF, off = [], [], 0
    for r in refs:
        v = r.verts.copy()
        for name, (attrs, dn) in r.sliders.items():
            if attrs.get("zap") == "true" or attrs.get("uv") == "true" or not dn or dn not in r.osd:
                continue
            val = 100.0 if (heel and r.key == "feet" and name == mp.HEEL) else _slider_value(attrs, pv, size)
            if val:
                v += val / 100.0 * r.osd[dn]
        SV.append(v)
        SF.append(r.tris + off)
        off += len(v)
    SV, SF = np.vstack(SV), np.vstack(SF)
    FN = np.cross(SV[SF[:, 1]] - SV[SF[:, 0]], SV[SF[:, 2]] - SV[SF[:, 0]])
    FN /= np.linalg.norm(FN, axis=1, keepdims=True) + 1e-12
    return SV, SF, FN


def _osd_sparse(path):
    with open(path, "rb") as f:
        b = f.read()
    o, n, out = 12, struct.unpack_from("<I", b, 8)[0], {}
    for _ in range(n):
        ln = b[o]
        name = b[o + 1:o + 1 + ln].decode("utf-8", "replace")
        o += 1 + ln
        c = struct.unpack_from("<H", b, o)[0]
        o += 2
        rec = np.frombuffer(b, dtype=np.dtype([("i", "<u2"), ("d", "<f4", 3)]), count=c, offset=o)
        o += 14 * c
        out[name] = (rec["i"].astype(np.int64), rec["d"].astype(np.float64))
    return out


def outfit_at_preset(set_name, pv, w, ref_names):
    """{shape: vertices} of the project's visible outfit shapes with the preset applied."""
    ss = ET.parse(os.path.join(mp.BS, "SliderSets", mp.safe(set_name) + ".osp")).getroot().find("SliderSet")
    folder, src = ss.findtext("DataFolder"), ss.findtext("SourceFile")
    nif = NifFile(os.path.join(mp.BS, "ShapeData", folder, src))
    osd = _osd_sparse(os.path.join(mp.BS, "ShapeData", folder, src[:-4] + ".osd"))
    zapped = {d.get("target") for sl in ss.findall("Slider") if sl.get("zap") == "true" for d in sl.findall("Data")}
    P = {}
    for s in nif.shapes:
        if s.name in ref_names or s.name in zapped or re.match(r"(virtual|3ba|collision)", s.name, re.I):
            continue
        if not (s.textures.get("Diffuse") or ""):
            continue                       # untextured helper (physics collision body)
        P[s.name] = np.array(s.verts, dtype=np.float64)
    size = "big" if w else "small"
    for sl in ss.findall("Slider"):
        if sl.get("zap") == "true" or sl.get("uv") == "true":
            continue
        v = _slider_value(sl.attrib, pv, size)
        if not v:
            continue
        for d in sl.findall("Data"):
            if d.get("local") != "true" or d.get("target") not in P:
                continue
            dn = d.text.split("\\", 1)[1]
            if dn in osd:
                i, dd = osd[dn]
                P[d.get("target")][i] += v / 100.0 * dd
    return P


def signed_depth(P, S):
    """Signed distance of points to the body surface (negative = inside); 9 where the side is unclear."""
    SV, SF, FN = S
    tri, bary, dist = ube_field.project(P, SV, SF)
    q = ube_field.interp(SV, SF, tri, bary)
    dot = ((P - q) * FN[tri]).sum(1)
    sd = np.sign(dot) * dist
    ok = (sd > -1.5) & ((np.abs(dot) >= 0.6 * dist) | (dist < 0.02))
    return np.where(ok, sd, 9.0)


MOTION_NEAR = 3.0        # outfit points this close to the UBE body must move with it
MOTION_BAD = 0.35        # share of bone weight that differs from the body under it (0 = same, 1 = other bones)


def motion_check(set_name, refs):
    """How the outfit follows the body when it moves (walking, combat, sitting): every outfit point lying on the
    body is compared with the UBE body's bone weights under it. A point weighted to other bones separates from or
    sinks into the body as soon as those bones turn, though the outfit fits in the standing pose.
    Returns {"motion": grade or None, "motion_pct": % of on-body points that move differently, "motion_bone": ...}."""
    import ube_weights
    bones, UW, _stb, _node = ube_weights.ref_weights(refs)
    col = {b: i for i, b in enumerate(bones)}
    U = np.vstack([r.verts for r in refs])
    ss = ET.parse(os.path.join(mp.BS, "SliderSets", mp.safe(set_name) + ".osp")).getroot().find("SliderSet")
    folder, src = ss.findtext("DataFolder"), ss.findtext("SourceFile")
    nif = NifFile(os.path.join(mp.BS, "ShapeData", folder, src))
    zapped = {d.get("target") for sl in ss.findall("Slider") if sl.get("zap") == "true" for d in sl.findall("Data")}
    ref_names = {r.shape for r in refs}
    n_on, n_bad, worst = 0, 0, Counter()
    for s in nif.shapes:
        if s.name in ref_names or s.name in zapped or not s.bone_names or not (s.textures.get("Diffuse") or ""):
            continue
        if re.match(r"(virtual|3ba|collision)", s.name, re.I) or not ube_weights._is_plain(s.global_to_skin):
            continue
        P = np.array(s.verts, dtype=np.float64) - np.array(s.global_to_skin.translation[:], dtype=np.float64)
        d, I = knn(U, P, 8)
        near = d[:, 0] <= MOTION_NEAR
        if not near.any():
            continue
        w = 1.0 / (d ** 2 + 1e-4)
        w /= w.sum(1, keepdims=True)
        C = (UW[I] * w[..., None]).sum(1)
        O, other = np.zeros((len(P), len(bones))), np.zeros(len(P))
        for b, lst in s.bone_weights.items():
            c = col.get(b)
            for vi, wt in lst:
                if c is None:
                    other[vi] += wt
                else:
                    O[vi, c] += wt
        share = O.sum(1)
        if ((O.max(1) + other) >= 0.9 * np.maximum(share + other, 1e-9)).mean() >= 0.9:
            continue                                   # a rigid plate (pauldron, shield, chest plate) rides one
            #                                            bone on purpose so it does not bend; that is not a fault
        use = near & (other < 0.5) & (share > 0)       # mostly physics bones: SMP moves those, not the skeleton
        if not use.any():
            continue
        On = O[use] / share[use, None]
        diff = On - C[use]
        bad = 0.5 * np.abs(diff).sum(1) > MOTION_BAD
        n_on += int(use.sum())
        n_bad += int(bad.sum())
        for k in np.abs(diff[bad]).argmax(1):
            worst[bones[k]] += 1
    if not n_on:
        return {"motion": None, "motion_pct": 0.0, "motion_bone": ""}
    pct = 100.0 * n_bad / n_on
    g = "A" if pct <= 3 else "B" if pct <= 12 else "C"
    return {"motion": g, "motion_pct": round(pct, 1), "motion_bone": worst.most_common(1)[0][0] if worst else ""}


def grade(verts, worst_count, worst):
    pct = 100.0 * worst_count / max(verts, 1)
    if pct <= 0.2 and worst >= -0.3:
        return "A"
    if pct <= 2.0 and worst >= -1.0:
        return "B"
    return "C"


def _init_qa():
    _G["refs"] = mp.load_refs()
    _G["surf"], _G["pv"] = {}, {}


def _qa_one(args):
    set_name, heel, preset = args
    try:
        refs = _G["refs"]
        if preset not in _G["pv"]:
            _G["pv"][preset] = preset_values(preset)
        pv = _G["pv"][preset]
        res = {"preset": preset, "verts": 0, "worst": 0.0}
        for w in (0, 1):
            key = (preset, w, bool(heel))
            if key not in _G["surf"]:
                _G["surf"][key] = body_surface(refs, pv, w, heel)
            P = outfit_at_preset(set_name, pv, w, {r.shape for r in refs})
            n_in, nv = 0, 0
            for p in P.values():
                sd = signed_depth(p, _G["surf"][key])
                n_in += int((sd < -0.05).sum())
                nv += len(p)
                res["worst"] = round(min(res["worst"], float(sd.min())), 3)
            res[f"in{w}"] = n_in
            res["verts"] = nv
        res["grade"] = grade(res["verts"], max(res["in0"], res["in1"]), res["worst"])
        res.update(motion_check(set_name, refs))
        return set_name, res, None
    except Exception as e:
        return set_name, None, repr(e)


def qa(set_names, preset, workers=6, on=None, stop=None):
    """Grade projects at a preset. on(i, total, set name, result or None, error or None)."""
    db = load_db()
    jobs = [(n, db.get(n, {}).get("heel", False), preset) for n in set_names]
    results = {}
    if jobs:
        with _pool(max(1, min(workers, len(jobs))), _init_qa) as pool:
            for i, (name, res, err) in enumerate(_results(pool, _qa_one, jobs, stop), 1):
                if res:
                    results[name] = res
                    db.setdefault(name, {})["qa"] = res
                if on:
                    on(i, len(jobs), name, res, err)
    save_db(db)
    return results
