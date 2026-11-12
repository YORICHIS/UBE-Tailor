# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""One merged UBE patch for every outfit mod the Tailor patches: "UBE Tailor.esp" (then "UBE Tailor 2.esp", ...
when a file would pass MAX_MASTERS masters or 2048 new records, the ESL limit).

The file is rebuilt from the source plugins every time, so it always matches what is installed. Per outfit mod:
  * a UBE copy of each armor addon: race = UBE, body slot 32 also gets slot 53, model = the converted
    meshes\\!UBE mesh once one exists (same rule as repoint_armas.py);
  * an override of the armor that lists those copies first, so UBE races pick them.
Every form id copied from a source plugin is renumbered to the merged file's master list.
Which mods are in it, and the object ids of the copies (kept the same between rebuilds), live in
the work folder (tailor_patch.json).
"""
import json
import os
import re
import shutil
import struct

import make_projects as mp
import repoint_armas
import tailor_core as tc
import env
from plugin_lib import enabled_plugins, plugin_locations, read_plugin, subrecords, zstr

BASE = "UBE Tailor"
STATE = os.path.join(env.WORK, "tailor_patch.json") if env.WORK else None
MAX_MASTERS = 250                      # the game allows 254 (ESL masters count too); keep a margin
FIRST_ID, LAST_ID = 0x800, 0xFFF       # ESL object id range
LOCALIZED = 0x80
FILE_RX = re.compile(r"^UBE Tailor( \d+)?\.esp$", re.I)

ARMA_FIDS = {b"NAM0", b"NAM1", b"NAM2", b"NAM3", b"SNDD", b"ONAM"}
ARMO_FIDS = {b"EITM", b"YNAM", b"ZNAM", b"ETYP", b"BIDS", b"BAMT", b"RNAM", b"TNAM", b"MODL"}
ALT_TEX = {b"MO2S", b"MO3S", b"MO4S", b"MO5S", b"DMDS"}


def file_name(i):
    return f"{BASE}.esp" if i == 0 else f"{BASE} {i + 1}.esp"


def merged_files():
    if not os.path.isdir(mp.MOD):
        return []
    return sorted(f for f in os.listdir(mp.MOD) if FILE_RX.match(f))


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("plugins", [])
    st.setdefault("foreign", [])         # other UBE patches whose armor addons we override (mesh, slot 53)
    st.setdefault("ids", {})
    return st


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE)


def tes4_info(path):
    """(record flags, CNAM author, masters) of a plugin's header."""
    with open(path, "rb") as f:
        hdr = f.read(24)
        data = f.read(struct.unpack_from("<I", hdr, 4)[0])
    flags = struct.unpack_from("<I", hdr, 8)[0]
    cnam = next((zstr(x) for t, x in subrecords(data) if t == b"CNAM"), "")
    return flags, cnam, [zstr(x) for t, x in subrecords(data) if t == b"MAST"]


def load_order():
    """{plugin name lower: position} from the profile's load order."""
    pos = {}
    for name in env.load_order():
        pos.setdefault(name, len(pos))
    return pos


# ---------------------------------------------------------------- form id renumbering
def remapper(ms, name, index):
    def R(fid):
        if fid == 0:
            return 0
        i = fid >> 24
        src = ms[i] if i < len(ms) else name
        return index[src.lower()] << 24 | fid & 0xFFFFFF
    return R


def _u32(x, R):
    return struct.pack("<I", R(struct.unpack("<I", x)[0]))


def remap_array(x, R):
    return b"".join(_u32(x[i:i + 4], R) for i in range(0, len(x) - len(x) % 4, 4)) + x[len(x) - len(x) % 4:]


def remap_alt(x, R):
    """Alternate textures: count, then per entry name (u32 len + chars), TXST form id, index."""
    b = bytearray(x)
    n, i = struct.unpack_from("<I", b, 0)[0], 4
    for _ in range(n):
        i += 4 + struct.unpack_from("<I", b, i)[0]
        struct.pack_into("<I", b, i, R(struct.unpack_from("<I", b, i)[0]))
        i += 8
    if i != len(b):
        raise ValueError("unexpected alternate texture data")
    return bytes(b)


def remap_dstd(x, R):
    b = bytearray(x)
    if len(b) >= 16:
        for off in (8, 12):                    # explosion, debris
            struct.pack_into("<I", b, off, R(struct.unpack_from("<I", b, off)[0]))
    return bytes(b)


def remap_vmad(x, R):
    """Script data: renumber object properties (single and arrays)."""
    b = bytearray(x)
    ver, fmt, count = struct.unpack_from("<hhH", b, 0)
    i = 6

    def wstr(i):
        return i + 2 + struct.unpack_from("<H", b, i)[0]

    def obj(i):
        off = i + 4 if fmt == 2 else i
        struct.pack_into("<I", b, off, R(struct.unpack_from("<I", b, off)[0]))
        return i + 8

    for _ in range(count):
        i = wstr(i)
        if ver >= 4:
            i += 1
        props = struct.unpack_from("<H", b, i)[0]
        i += 2
        for _ in range(props):
            i = wstr(i)
            typ = b[i]
            i += 2 if ver >= 4 else 1
            if typ == 1:
                i = obj(i)
            elif typ == 2:
                i = wstr(i)
            elif typ in (3, 4):
                i += 4
            elif typ == 5:
                i += 1
            elif typ in (11, 12, 13, 14, 15):
                n = struct.unpack_from("<I", b, i)[0]
                i += 4
                for _ in range(n):
                    i = obj(i) if typ == 11 else wstr(i) if typ == 12 else i + 4 if typ in (13, 14) else i + 1
            else:
                raise ValueError(f"unknown script property type {typ}")
    return bytes(b)


def remap_sub(t, x, R, fids):
    if t in fids and len(x) == 4:
        return _u32(x, R)
    if t == b"KWDA":
        return remap_array(x, R)
    if t in ALT_TEX:
        return remap_alt(x, R)
    if t == b"DSTD":
        return remap_dstd(x, R)
    if t == b"VMAD":
        return remap_vmad(x, R)
    return x


# ---------------------------------------------------------------- records of one outfit mod
def mod_records(e, index, new_i, ids, ui, target, extra, converted):
    """(armo bytes, arma bytes, armo count, arma count) for one source plugin."""
    R = remapper(e["ms"], e["name"], index)
    n = len(e["ms"])
    armas = {fid & 0xFFFFFF: (d, fl) for sig, fid, d, fl in e["recs"] if sig == b"ARMA" and fid >> 24 >= n}
    armos = {fid & 0xFFFFFF: (d, fl) for sig, fid, d, fl in e["recs"] if sig == b"ARMO" and fid >> 24 >= n}
    # UBE's naked body sits on 32 + 53, so body pieces normally get 53 too. But when the outfit has its own slot-53
    # piece (pants, leggings), two pieces worn together would share slot 53 and the game hides one of them.
    own53 = any(next((struct.unpack_from("<I", x)[0] for t, x in subrecords(d) if t in (b"BOD2", b"BODT")), 0) & 1 << 23
                for sig, fid, d, _fl in e["recs"] if fid >> 24 >= n)
    done, arma_body, armo_body = {}, b"", b""
    for armo_obj, arma_objs in e["todo"]:
        mine = []
        for a in arma_objs:
            if a not in done:
                data, fl = armas[a]
                subs = []
                for t, x in subrecords(data):
                    if t == b"EDID":
                        x = zstr(x).encode("cp1252", "replace") + b"_UBE\0"
                    elif t in (b"BOD2", b"BODT"):
                        f0 = struct.unpack_from("<I", x)[0]
                        if f0 & 4 and not own53:        # body slot 32 -> also UBE slot 53
                            x = struct.pack("<I", f0 | 1 << 23) + x[4:]
                    elif t == b"RNAM":
                        x = struct.pack("<I", ui << 24 | target)
                    elif t == b"MODL" and len(x) == 4:
                        continue                        # the old additional races
                    elif t == b"MOD3":
                        path = zstr(x)
                        key = path.replace("/", "\\").lower()
                        if not key.startswith("!ube\\") and key in converted:
                            x = ("!UBE\\" + path).encode("cp1252", "replace") + b"\0"
                    else:
                        x = remap_sub(t, x, R, ARMA_FIDS)
                    subs.append(tc._sub(t, x))
                subs += [tc._sub(b"MODL", struct.pack("<I", ui << 24 | r)) for r in extra]
                done[a] = new_i << 24 | ids[f"{e['name'].lower()}|{a:06x}"]
                arma_body += tc._rec(b"ARMA", done[a], fl, b"".join(subs))
            mine.append(done[a])
        data, fl = armos[armo_obj]
        subs, placed = [], False
        ins = b"".join(tc._sub(b"MODL", struct.pack("<I", f)) for f in mine)
        for t, x in subrecords(data):
            if t == b"MODL" and len(x) == 4 and not placed:
                subs.append(ins)                        # first in the list so it wins for UBE races
                placed = True
            subs.append(tc._sub(t, remap_sub(t, x, R, ARMO_FIDS)))
        if not placed:
            subs.append(ins)
        armo_body += tc._rec(b"ARMO", R(n << 24 | armo_obj), fl, b"".join(subs))
    return armo_body, arma_body, len(e["todo"]), len(done)


def assign_ids(entries, old):
    """Object ids for the new armor addons of one file: keep earlier ones, fill the rest from the lowest free."""
    keys = [f"{e['name'].lower()}|{a:06x}" for e in entries for a in dict.fromkeys(x for _o, al in e["todo"] for x in al)]
    ids, used = {}, set()
    for k in keys:
        v = old.get(k)
        if v is not None and FIRST_ID <= v <= LAST_ID and v not in used:
            ids[k] = v
            used.add(v)
    nxt = FIRST_ID
    for k in keys:
        if k not in ids:
            while nxt in used:
                nxt += 1
            ids[k] = nxt
            used.add(nxt)
    return ids


# ---------------------------------------------------------------- other UBE patches: override, never edit
FOREIGN_FIDS = ARMA_FIDS | {b"RNAM", b"MODL"}


def owner_key(ms, name, fid):
    """(plugin that owns the record, lower case, object id): the same key in every plugin that lists it."""
    i = fid >> 24
    return (ms[i] if i < len(ms) else name).lower(), fid & 0xFFFFFF


def override_records():
    """{owner_key: armor addon data} of the overrides of other plugins' armor addons in the merged files."""
    out = {}
    for f in merged_files():
        ms, recs = read_plugin(os.path.join(mp.MOD, f), {b"ARMA"})
        for _sig, fid, data, _fl in recs:
            if fid >> 24 < len(ms):
                out[owner_key(ms, f, fid)] = data
    return out


def foreign_overrides(patch, converted, log=print):
    """Entries for one other UBE patch: its UBE armor addons whose mesh is built as UBE (MOD3 -> !UBE) or whose body
    piece clashes on slot 53 with the outfit's own slot-53 piece. Returns [dict(key, ms, name, data, flags, new,
    masters)] - masters = the plugins the record refers to (only those become masters of UBE Tailor.esp)."""
    found = [f for f in tc.foreign_armas() if f["patch"].lower() == patch.lower()]
    loc = plugin_locations()
    s53 = {}
    out = []
    for f in found:
        src = f["src"].lower()
        if src not in s53:
            s53[src] = tc.slot53_models(loc[src]) if src in loc else set()
        subs, changed = [], False
        m3 = next((zstr(x) for t, x in subrecords(f["data"]) if t == b"MOD3"), "")
        key = m3.replace("/", "\\").lower()
        for t, x in subrecords(f["data"]):
            if t == b"MOD3" and not key.startswith("!ube\\") and key in converted:
                x = ("!UBE\\" + m3).encode("cp1252", "replace") + b"\0"
                changed = True
            elif t in (b"BOD2", b"BODT") and key.replace("!ube\\", "", 1) in s53[src]:
                f0 = struct.unpack_from("<I", x)[0]
                if f0 & 4 and f0 & 1 << 23:
                    x = struct.pack("<I", f0 & ~(1 << 23)) + x[4:]
                    changed = True
            subs.append((t, x))
        if not changed:
            continue                              # the other patch's own record is right as it is
        used = set()

        def note(fid, ms=f["ms"], name=f["patch"]):
            if fid:
                i = fid >> 24
                used.add(ms[i] if i < len(ms) else name)
            return fid
        note(f["fid"])
        for t, x in subs:
            remap_sub(t, x, note, FOREIGN_FIDS)
        out.append(dict(key=owner_key(f["ms"], f["patch"], f["fid"]), ms=f["ms"], name=f["patch"], fid=f["fid"],
                        subs=subs, flags=f["flags"], masters={u.lower(): u for u in used}))
    return out


def foreign_bytes(e, index):
    R = remapper(e["ms"], e["name"], index)
    body = b"".join(tc._sub(t, remap_sub(t, x, R, FOREIGN_FIDS)) for t, x in e["subs"])
    return tc._rec(b"ARMA", R(e["fid"]), e["flags"], body)


# ---------------------------------------------------------------- build
def build(add=(), exclude=(), log=print, add_foreign=()):
    """Rebuild every UBE Tailor*.esp. add = outfit plugins to include from now on; add_foreign = other UBE patches
    whose armor addons get overridden from now on; exclude = patch files to leave out of the 'already covered'
    check. Returns [(file, mods, armors, addons, masters)]."""
    st = load_state()
    order = st["plugins"]
    for n in add:
        if n.lower() not in (p.lower() for p in order):
            order.append(n)
    forder = st["foreign"]
    for n in add_foreign:
        if n.lower() not in (p.lower() for p in forder):
            forder.append(n)
    skip = {f.lower() for f in merged_files()} | {x.lower() for x in exclude}
    cov, _aware = tc.covered_armos(exclude=skip)
    loc = plugin_locations()
    enabled = {p.lower() for p in enabled_plugins()}
    target, extra = tc.ube_races()
    converted = repoint_armas.converted_set()

    entries = []
    for name in order:
        low = name.lower()
        if low not in enabled or low not in loc:
            log(f"   left out {name}: not enabled")
            continue
        path = loc[low]
        if tes4_info(path)[0] & LOCALIZED:
            log(f"   left out {name}: localized plugin (not supported yet)")
            continue
        todo = tc.patchable(path, name, cov)
        if not todo:
            log(f"   left out {name}: no armor left to patch (another UBE patch covers it)")
            continue
        ms, recs = read_plugin(path, {b"ARMO", b"ARMA"})
        names = {m.lower(): m for m in ms}
        names[low] = name
        names[tc.UBE_PLUGIN.lower()] = tc.UBE_PLUGIN
        e = dict(name=name, path=path, ms=ms, recs=recs, todo=todo, masters=names,
                 n_arma=len({a for _o, al in todo for a in al}))
        try:                                   # renumber once on a throw-away index to catch odd data early
            mod_records(e, {k: 0 for k in names}, 0, {f"{low}|{a:06x}": FIRST_ID for _o, al in todo for a in al},
                        0, target, extra, converted)
        except (ValueError, struct.error, KeyError) as ex:
            log(f"   left out {name}: could not copy its records ({ex})")
            continue
        entries.append(e)
    n_over = 0
    for pname in forder:
        if pname.lower() not in enabled:
            log(f"   left out overrides of {pname}: not enabled")
            continue
        try:
            fo = foreign_overrides(pname, converted, log)
        except (ValueError, struct.error, KeyError) as ex:
            log(f"   left out overrides of {pname}: could not copy its records ({ex})")
            continue
        if fo:
            allm = {}
            for x in fo:
                allm.update(x["masters"])
            entries.append(dict(name=pname, foreign=fo, masters=allm, n_arma=0, todo=[]))
            n_over += len(fo)
    if n_over:
        log(f"   {n_over} armor addon(s) of other UBE patches overridden (built UBE mesh / slot 53)")

    groups, cur, cur_m, cur_n = [], [], set(), 0
    for e in entries:
        m = set(e["masters"])
        if len(m) > MAX_MASTERS or e["n_arma"] > LAST_ID - FIRST_ID + 1:
            log(f"   left out {e['name']}: too big for one patch file")
            continue
        if cur and (len(cur_m | m) > MAX_MASTERS or cur_n + e["n_arma"] > LAST_ID - FIRST_ID + 1):
            groups.append(cur)
            cur, cur_m, cur_n = [], set(), 0
        cur.append(e)
        cur_m |= m
        cur_n += e["n_arma"]
    if cur:
        groups.append(cur)

    lo = load_order()
    result, new_ids = [], {}
    for gi, group in enumerate(groups):
        fname = file_name(gi)
        allm = {}
        for e in group:
            allm.update(e["masters"])
        masters = sorted(allm.values(), key=lambda m: (lo.get(m.lower(), 1 << 30), m.lower()))
        index = {m.lower(): i for i, m in enumerate(masters)}
        new_i = len(masters)
        ids = assign_ids([e for e in group if "foreign" not in e], st["ids"].get(fname.lower(), {}))
        new_ids[fname.lower()] = ids
        if tc.UBE_PLUGIN.lower() not in index:            # only overrides in this file
            masters.append(tc.UBE_PLUGIN)
            index[tc.UBE_PLUGIN.lower()] = len(masters) - 1
            new_i = len(masters)
        ui = index[tc.UBE_PLUGIN.lower()]
        armo_body, arma_body, n_armo, n_arma = b"", b"", 0, 0
        for e in group:
            if "foreign" in e:
                for x in e["foreign"]:
                    arma_body += foreign_bytes(x, index)
                n_arma += len(e["foreign"])
                continue
            a, b, c, d = mod_records(e, index, new_i, ids, ui, target, extra, converted)
            armo_body += a
            arma_body += b
            n_armo += c
            n_arma += d
        tes4 = tc._sub(b"HEDR", struct.pack("<fiI", 1.71, n_armo + n_arma + 2, max(ids.values(), default=FIRST_ID - 1) + 1))
        tes4 += tc._sub(b"CNAM", b"UBE Tailor\0")
        tes4 += tc._sub(b"SNAM", b"UBE versions of outfits, made by UBE Tailor (by Desertravel). The tool rebuilds this file; "
                                 b"do not edit it by hand.\0")
        for m in masters:
            tes4 += tc._sub(b"MAST", m.encode("cp1252", "replace") + b"\0") + tc._sub(b"DATA", b"\0" * 8)
        blob = struct.pack("<4sIIIIHH", b"TES4", len(tes4), 0x200, 0, 0, 44, 0) + tes4
        blob += tc._grup(b"ARMO", armo_body) + tc._grup(b"ARMA", arma_body)
        out = os.path.join(mp.MOD, fname)
        os.makedirs(mp.MOD, exist_ok=True)
        with open(out + ".tmp", "wb") as f:
            f.write(blob)
        os.replace(out + ".tmp", out)
        result.append((fname, len(group), n_armo, n_arma, len(masters)))

    keep = {r[0].lower() for r in result}
    for f in merged_files():
        if f.lower() not in keep:                       # no longer needed (fewer files than before)
            shutil.move(os.path.join(mp.MOD, f), os.path.join(env.backup_dir(), f))
            log(f"   removed {f} (moved to the backup folder)")
    st["plugins"] = order
    st["foreign"] = forder
    st["ids"] = new_ids
    save_state(st)
    return result


def place_in_load_order(files, drop=()):
    """Enable the output mod, tick the merged files and put them at the end of the load order (after all their
    masters); remove the drop plugins. Only when MO2 is closed or launched us (env.can_edit_profile). True if
    written (or nothing had to change). Every profile file is backed up first (env.backup)."""
    if not env.can_edit_profile():
        return False
    env.enable_output_mod()
    ours = {f.lower() for f in files} | {d.lower() for d in drop}
    for txt, prefix in (("plugins.txt", "*"), ("loadorder.txt", "")):
        p = os.path.join(env.PROFILE, txt)
        if not os.path.isfile(p):
            continue
        with open(p, "rb") as f:
            raw = f.read()
        nl = "\r\n" if b"\r\n" in raw else "\n"
        lines = raw.decode("utf-8", "replace").splitlines()
        keep = [ln for ln in lines if ln.strip().lstrip("*").lower() not in ours]
        keep += [prefix + f for f in files]
        if keep == lines:
            continue
        env.backup(p)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(nl.join(keep) + nl)
    return True


def scan_records():
    """(source plugin label, armor addon data) for every UBE copy in the merged files; label = plugin w/o extension."""
    for f in merged_files():
        ms, recs = read_plugin(os.path.join(mp.MOD, f), {b"ARMO", b"ARMA"})
        own = len(ms)
        src = {}
        for sig, fid, data, _fl in recs:
            if sig != b"ARMO":
                continue
            label = os.path.splitext(ms[fid >> 24])[0] if fid >> 24 < own else BASE
            for t, x in subrecords(data):
                if t == b"MODL" and len(x) == 4:
                    a = struct.unpack("<I", x)[0]
                    if a >> 24 == own:
                        src.setdefault(a, label)
        for sig, fid, data, _fl in recs:
            if sig == b"ARMA" and fid >> 24 == own:       # our own UBE copies (overrides: override_records)
                yield src.get(fid, BASE), data


