# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""What UBE Tailor needs, and whether this PC / modpack has it. Used by the requirements screen and `tailor.py check`.

The tool never downloads anything: each missing item only has the address of its official page, which the window
opens in the browser when the user asks for it. Nothing here imports PyNifly, numpy or scipy (they may be the
missing items); everything is looked up by file name.
"""
import importlib.util
import os
import sys

import env

NEXUS = "https://www.nexusmods.com/skyrimspecialedition/mods/"


class Item:
    """need = 'required' | 'optional' | 'info' (information about the modpack: never blocks, shown as a warning when
    not ok). chip = short text the requirements screen shows when ok (default 'Installed')."""

    def __init__(self, key, name, need, ok, detail, url, how, chip=""):
        self.key, self.name, self.need, self.ok, self.detail, self.url, self.how = key, name, need, ok, detail, url, how
        self.chip = chip

    def __repr__(self):
        return f"[{'ok' if self.ok else 'MISSING'}] {self.name}"


def _has(mod):
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def check():
    """[Item] in the order the screen shows them. need = 'required' | 'optional'."""
    out = []
    out.append(Item("python", "Python 3.10+ with numpy and scipy", "required",
                    sys.version_info >= (3, 10) and _has("numpy") and _has("scipy"),
                    f"Python {sys.version.split()[0]}, numpy {'yes' if _has('numpy') else 'no'}, "
                    f"scipy {'yes' if _has('scipy') else 'no'}",
                    "https://www.python.org/downloads/windows/",
                    "Install Python 3 (tick 'Add python.exe to PATH'), then run:  py -m pip install numpy scipy"))
    py = env.find_pynifly()
    out.append(Item("pynifly", "PyNifly (reads and writes .nif files)", "required", bool(py),
                    py or "not found next to the tool, in the settings or in Blender",
                    "https://github.com/BadDogSkyrim/PyNifly/releases",
                    "Download the release zip and put its 'io_scene_nifly' folder into a folder named 'pynifly' "
                    "next to UBE Tailor (or install it in Blender)."))
    if not env.READY:
        out.append(Item("modpack", "Your Mod Organizer 2 modpack", "required", False,
                        "; ".join(env.problems(env.L)) if env.L else "not chosen yet", "",
                        "Pick the folder that holds ModOrganizer.exe / ModOrganizer.ini."))
        return out
    out.append(game_item())
    parts = [env.ube_part(f) for _k, _p, f in env.UBE_PARTS]
    ube_files = all(all(p) for p in parts)
    ube_esp = env.UBE_PLUGIN.lower() in (p.lower() for p in env.enabled_plugins())
    out.append(Item("ube", "UBE 2.0 body (BodySlide files + UBE_AllRace.esp)", "required", ube_files and ube_esp,
                    ("BodySlide files " + ("found" if ube_files else "missing")) + ", " +
                    (f"{env.UBE_PLUGIN} " + ("enabled" if ube_esp else "not enabled")),
                    NEXUS + "92989", "Install UBE 2.0 in MO2 and tick UBE_AllRace.esp."))
    rn, _ro = env.conversion_ref()
    out.append(Item("refs", "UBE 'Conversion references' (3BA to UBE 2.0)", "required", bool(rn),
                    rn or "'3BA to UBE 2.0' reference not found",
                    NEXUS + "92989?tab=files",
                    "On the UBE 2.0 page, Files tab, download the optional file 'Conversion references' and "
                    "install it in MO2 like any mod."))
    t3 = env.t3_ref()
    out.append(Item("3ba", "CBBE 3BA (3BBB) reference body", "required", bool(t3), t3 or "CBBE 3BA Ref.nif not found",
                    NEXUS + "30174", "Install CBBE 3BA in MO2 (your 3BA outfits need it anyway)."))
    bs = env.bodyslide_exe()
    out.append(Item("bodyslide", "BodySlide and Outfit Studio", "required", bool(bs), bs or "BodySlide x64.exe not found",
                    NEXUS + "201", "Install BodySlide in MO2. You build the converted outfits with it (Batch Build)."))
    on = {p.lower() for p in env.enabled_plugins()}
    mods = {m.lower() for m in env.enabled_mods()}
    rm = any("racemenu" in p for p in on) or env.find(os.path.join("SKSE", "Plugins", "skee64.dll")) is not None
    out.append(Item("racemenu", "RaceMenu (body morphs in game)", "optional", rm, "found" if rm else "not found",
                    NEXUS + "19080", "Optional: lets converted outfits follow body sliders in game."))
    ob = env.find(os.path.join("SKSE", "Plugins", "OBody.dll")) is not None or any("obody" in m for m in mods)
    out.append(Item("obody", "OBody NG (body presets for NPCs)", "optional", ob, "found" if ob else "not found",
                    NEXUS + "77016", "Optional: gives NPCs UBE body presets; converted outfits follow them."))
    return out


def plugins_171():
    """Enabled plugins written with header version 1.71 (the plugin format of Skyrim AE 1.6.1130 and newer)."""
    import struct
    from plugin_lib import plugin_locations
    loc = plugin_locations()
    out = []
    for name in env.enabled_plugins():
        p = loc.get(name.lower())
        try:
            with open(p, "rb") as f:
                h = f.read(34)
        except (OSError, TypeError):
            continue
        if h[:4] == b"TES4" and h[24:28] == b"HEDR" and struct.unpack_from("<f", h, 30)[0] > 1.705:
            out.append(name)
    return out


def game_item():
    """Which Skyrim the modpack runs (read from SkyrimSE.exe, else the user's answer), and whether that version can
    load every plugin of the modpack. UBE Tailor's own plugin works on SE 1.5.97 and on every AE version."""
    ed, ver = env.game_edition()
    name = "Skyrim version"
    if ed is None:
        return Item("game", name, "info", False,
                    "UBE Tailor could not read the game's version (no SkyrimSE.exe in the game folder MO2 uses).",
                    "", "Which Skyrim does this modpack run? Pick it below - the Tailor remembers it.")
    label = f"Skyrim {'Special Edition' if ed == 'SE' else 'Anniversary Edition'} {ver}".rstrip() + f" ({ed})"
    v = env.game_version()
    old_runtime = (v < env.NEW_ESL_RUNTIME) if v else ed == "SE"
    if old_runtime and env.find(env.BEES_DLL) is None:
        new = plugins_171()
        if new:
            return Item("game", name, "info", False,
                        f"{label}. {len(new)} plugin(s) in this modpack use the newer AE plugin format (header 1.71), "
                        f"which this game version loads only with BEES - without it they can crash the game: "
                        + ", ".join(new[:8]) + (" ..." if len(new) > 8 else ""),
                        NEXUS + "106441",
                        "Install 'Backported Extended ESL Support' (BEES, needs SKSE) in MO2. UBE Tailor's own "
                        "plugin uses the SE format and does not need it.")
    return Item("game", name, "info", True, label + (" - can load every plugin of this modpack" if old_runtime
                                                    else ""), "", "", chip=f"{ed} {ver}".strip())


def missing(items=None, need="required"):
    return [i for i in (items if items is not None else check()) if not i.ok and i.need == need]


if __name__ == "__main__":
    for it in check():
        print(f"[{'ok' if it.ok else '--'}] {it.name}  ({it.need})\n      {it.detail}")
        if not it.ok:
            print(f"      get it: {it.url or '-'}\n      {it.how}")
