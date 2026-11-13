# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""UBE Tailor, command line.

  python tailor.py setup <MO2 folder> [--profile NAME] [--output DIR]   pick the modpack (once)
  python tailor.py check                        what is installed / missing (UBE, references, PyNifly, ...)
  python tailor.py presets                      UBE BodySlide presets; --preset NAME saves the one to use
  python tailor.py scan                         what is converted / pending, per mod
  python tailor.py new                          enabled plugins with armors that have no UBE patch yet
  python tailor.py convert [--filter T] [--limit N] [--workers N] [--redo]
  python tailor.py qa [--filter T] [--preset NAME] [--workers N]
  python tailor.py patch [--filter PLUGIN] [--dry]   rebuild "UBE Tailor.esp" (points at built meshes); with
                                                     --filter also add the outfit mods matching it, converted or not
  python tailor.py doctor [--fix] [--deep]      health check: every known problem and its fix (see doctor.py)
  python tailor.py fix [--workers N] [--dry]    convert pieces left out of converted outfits and re-convert projects
                                                made with an older Tailor (make_projects.METHOD), then grade them
"""
import argparse
import os
import sys
import time
from collections import Counter

import env

tc = None                     # tailor_core, imported once the modpack and PyNifly are there


def pick(items, text, states):
    text = (text or "").lower()
    return [i for i in items if i["state"] in states and (text in i["base"].lower() or text in i["plugin"].lower())]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["setup", "check", "presets", "scan", "new", "convert", "qa", "patch", "fix",
                                    "doctor"])
    ap.add_argument("where", nargs="?", help="setup: the MO2 folder (or its ModOrganizer.ini)")
    ap.add_argument("--profile", help="setup: MO2 profile (default: the one MO2 has selected)")
    ap.add_argument("--output", help="setup: where projects + patch go (default: mods\\" + env.OUTPUT_MOD_NAME + ")")
    ap.add_argument("--fix", action="store_true", help="doctor: repair what the Tailor can repair")
    ap.add_argument("--deep", action="store_true", help="doctor: also look for falling HDT-SMP bones (slow)")
    ap.add_argument("--filter")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--preset", default=None, help="UBE BodySlide preset for the fit check (saved)")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    if a.cmd == "setup":
        return setup(a)
    if a.cmd == "check":
        import requirements
        items = requirements.check()
        for it in items:
            print(f"[{'ok' if it.ok else '--'}] {it.name}  ({it.need})\n      {it.detail}")
            if not it.ok:
                print(f"      get it: {it.url or '-'}\n      {it.how}")
        return 1 if requirements.missing(items) else 0
    if not env.READY:
        print("No modpack chosen yet: python tailor.py setup <your MO2 folder>")
        return 1
    global tc
    import tailor_core as tc
    if a.preset:
        env.set_preset(a.preset)
    a.preset = env.preset()
    if a.cmd == "presets":
        for p in tc.list_presets():
            print(("* " if p == a.preset else "  ") + p)
        if not a.preset:
            print("No preset picked yet: python tailor.py presets --preset NAME")
        return 0

    if a.cmd == "scan":
        items = tc.scan()
        c = Counter(i["state"] for i in items)
        print("total", len(items), {tc.STATES[k]: v for k, v in c.items()})
        lo = tc.left_out(items)
        print(f"left out of converted outfits: {len(lo)} pieces in {len({os.path.dirname(i['base']) for i in lo})} outfits")
        for i in lo[:40]:
            print(f"   {i['base']}  slots {i['slots']}")
        le = sorted({(i["format"], i["plugin"]) for i in items if i["format"] != "SE"}, key=lambda x: x[1].lower())
        if le:
            print(f"{len(le)} outfit mod(s) were " + tc.LE_NOTE)
            for f, p in le:
                print(f"   {tc.FORMATS[f]}: {p}")
        ed, ver = env.game_edition()
        print(f"game: Skyrim {ed} {ver}" if ed else "game: Skyrim version unknown (run: tailor.py check)")
        pend = Counter(i["plugin"] for i in items if i["state"] == "pending")
        for p, n in pend.most_common(30):
            print(f"   {n:5}  {p}")
    elif a.cmd == "new":
        found = tc.find_new_plugins(log=print)
        print(f"{len(found)} plugin(s) need a UBE patch")
        for name, (_path, todo) in sorted(found.items(), key=lambda kv: -len(kv[1][1])):
            print(f"   {len(todo):5} outfits  {name}")
    elif a.cmd == "convert":
        sel = pick(tc.scan(), a.filter, ("pending", "built", "done") if a.redo else ("pending",))[:a.limit]
        print(f"converting {len(sel)} pieces with {a.workers} workers")

        def on(i, total, base, name, err, lines):
            if err:
                print(f"[{i}/{total}] !! {base}: {err}", flush=True)
            elif name:
                print(f"[{i}/{total}] {time.time() - t0:.0f}s {next((l for l in lines if l.startswith('== ')), name)}", flush=True)
            else:
                print(base, flush=True)
        made, failed = tc.convert([i["base"] for i in sel], a.workers, on)
        print(f"done: {len(made)} ok, {len(failed)} failed, {time.time() - t0:.0f} s")
    elif a.cmd == "qa":
        sel = pick(tc.scan(), a.filter, ("built", "done"))[:a.limit]
        if not a.preset:
            print("Pick your UBE body preset first: python tailor.py presets --preset NAME")
            return 1
        print(f"checking the fit of {len(sel)} projects on {a.preset}")

        def on(i, total, name, res, err):
            if err:
                print(f"[{i}/{total}] !! {name}: {err}", flush=True)
            else:
                print(f"[{i}/{total}] {res['grade']} inside w0={res['in0']} w1={res['in1']} of {res['verts']} deepest {res['worst']}  {name[11:]}", flush=True)
        res = tc.qa([i["set"] for i in sel], a.preset, a.workers, on)
        print(dict(Counter(tc.GRADES[r["grade"]] for r in res.values())), f"{time.time() - t0:.0f} s")
    elif a.cmd == "patch":
        if tc.running("SkyrimSE.exe"):
            print("The game is running. Close it first.")
            return 1
        import merged_patch
        found = tc.find_new_plugins(log=print) if a.filter else {}   # new outfits only for plugins named by --filter
        chosen = [n for n in found if a.filter.lower() in n.lower()]
        for name in chosen:
            print(f"{'(dry run) ' if a.dry else ''}adding {name}: {len(found[name][1])} outfits")
        if chosen and not a.dry:
            res = merged_patch.build(add=chosen, log=print)
            for fname, n_mods, n_armo, n_arma, n_m in res:
                print(f"{fname}: {n_mods} mods, {n_armo} outfits, {n_arma} armor addons, {n_m} masters")
            if not merged_patch.place_in_load_order([r[0] for r in res]):
                print("  <- MO2 is open: press F5, tick the UBE Tailor plugin(s) and keep them at the bottom")
        print(tc.repoint(a.dry)[-1500:])
    elif a.cmd == "doctor":
        import doctor
        found = doctor.check(a.deep, log=print)
        marks = {"fix": "FIX ", "you": "YOU ", "info": "INFO"}
        for f in found:
            print(f"[{marks[f.level]}] {f.title}")
            for x in f.items[:5]:
                print(f"         {x}")
        if not found:
            print("All good: nothing to repair.")
        elif a.fix:
            doctor.fix(found, a.preset, a.workers, log=print)
        elif any(f.level == "fix" for f in found):
            print("Run 'python tailor.py doctor --fix' to repair the FIX lines.")
    elif a.cmd == "fix":
        items = tc.scan()
        lo, old = tc.left_out(items), tc.outdated(items)
        print(f"left out of converted outfits: {len(lo)}, made with an older Tailor: {len(old)}")
        if a.dry or not (lo or old):
            return 0
        if tc.running("SkyrimSE.exe"):
            print("The game is running. Close it first.")
            return 1

        def on(i, total, base, name, err, lines):
            if err:
                print(f"[{i}/{total}] {'skipped' if err.startswith('HEAD: ') else '!!'} {base}: {err}", flush=True)
        made, failed = tc.convert([i["base"] for i in lo + old], a.workers, on)
        print(f"converted {len(made)}, failed {len(failed)}, {time.time() - t0:.0f} s")
        if a.preset:
            res = tc.qa(made, a.preset, a.workers)
            print("fit:", dict(Counter(r["grade"] for r in res.values())),
                  "moving:", dict(Counter(r.get("motion") for r in res.values())))
        print(tc.repoint(False).strip().splitlines()[-1])
        print("Next: Batch Build in BodySlide, then Scan in the Tailor.")
    return 0


def setup(a):
    """Pick the modpack: remember its ModOrganizer.ini + profile (+ output folder) in the settings."""
    where = a.where or ""
    inis = [where] if where.lower().endswith(".ini") and os.path.isfile(where) else env.inis_in(where) if where else []
    if not inis:
        print("No ModOrganizer.ini found there. Modpacks found on this PC:")
        for ini in env.guesses():
            print("   ", os.path.dirname(ini))
        return 1
    L = env.layout(inis[0], a.profile)
    probs = env.problems(L)
    for p in probs:
        print("!!", p)
    if probs:
        print("Profiles:", ", ".join(env.profiles(L)))
        return 1
    s = env.load_settings()
    s.update(ini=L["ini"], profile=L["profile_name"])
    if a.output:
        s["output_dir"] = os.path.abspath(a.output)
    else:
        s.pop("output_dir", None)
    env.save_settings(s)
    print(f"Modpack: {L['instance']}\nGame:    {L['game']}\nProfile: {L['profile_name']}\nOutput:  "
          f"{s.get('output_dir') or os.path.join(L['mods'], env.OUTPUT_MOD_NAME)}")
    print("Next: python tailor.py check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
