# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Where everything is: the Mod Organizer 2 modpack the user picked, and the tool's own folders.

The user picks the folder of their modpack once (the folder with ModOrganizer.exe / ModOrganizer.ini); the rest
is read from ModOrganizer.ini: game folder, profile, mods, overwrite. Works for portable instances (ini next to the
exe, e.g. Wabbajack lists) and global ones (ini in %LOCALAPPDATA%\\ModOrganizer\\<name>).

Settings: %LOCALAPPDATA%\\UBE Tailor\\settings.json (or the folder in the UBE_TAILOR_HOME environment variable).
The other modules read the paths below at import time; after the modpack changes the program restarts.
"""
import configparser
import ctypes
import hashlib
import json
import os
import re

TOOL = os.path.dirname(os.path.abspath(__file__))
HOME = os.environ.get("UBE_TAILOR_HOME") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "UBE Tailor")
SETTINGS = os.path.join(HOME, "settings.json")
OUTPUT_MOD_NAME = "UBE Tailor Output"
AUTHOR = "Desertravel"
VERSION = "0.9.1-beta"
GAMES = ("Skyrim Special Edition",)
GLOBAL_INSTANCES = os.path.join(os.environ.get("LOCALAPPDATA") or "", "ModOrganizer")


# ---------------------------------------------------------------- ModOrganizer.ini
def _unwrap(v):
    v = v.strip()
    m = re.match(r"^@ByteArray\((.*)\)$", v)
    if m:
        v = m.group(1)
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1]
    return v.replace("\\\\", "\\")


def read_ini(path):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    with open(path, encoding="utf-8", errors="replace") as f:
        cp.read_file(f)

    def g(sec, key):
        return _unwrap(cp.get(sec, key)) if cp.has_option(sec, key) else ""
    return {"game": g("General", "gameName"), "game_path": g("General", "gamePath"),
            "profile": g("General", "selected_profile"), "base": g("Settings", "base_directory"),
            "mods": g("Settings", "mod_directory"), "profiles": g("Settings", "profiles_directory"),
            "overwrite": g("Settings", "overwrite_directory")}


def layout(ini_path, profile=None):
    """All folders of one modpack, from its ModOrganizer.ini."""
    d = read_ini(ini_path)
    inst = os.path.dirname(os.path.abspath(ini_path))
    base = os.path.normpath(d["base"].replace("%BASE_DIR%", inst)) if d["base"] else inst

    def sub(v, default):
        v = (v or default).replace("%BASE_DIR%", base)
        return os.path.normpath(v if os.path.isabs(v) else os.path.join(base, v))
    L = {"ini": os.path.abspath(ini_path), "instance": inst, "base": base, "game_name": d["game"],
         "game": os.path.normpath(d["game_path"]) if d["game_path"] else "",
         "mods": sub(d["mods"], "%BASE_DIR%/mods"), "profiles": sub(d["profiles"], "%BASE_DIR%/profiles"),
         "overwrite": sub(d["overwrite"], "%BASE_DIR%/overwrite")}
    L["profile_name"] = profile or d["profile"]
    L["profile"] = os.path.join(L["profiles"], L["profile_name"])
    L["data"] = os.path.join(L["game"], "Data") if L["game"] else ""
    return L


def profiles(L):
    d = L["profiles"]
    if not os.path.isdir(d):
        return []
    return sorted((p for p in os.listdir(d) if os.path.isfile(os.path.join(d, p, "modlist.txt"))), key=str.lower)


def problems(L):
    """What is wrong with this modpack for the tool (empty list = fine)."""
    out = []
    if L["game_name"] and L["game_name"] not in GAMES:
        out.append(f"This modpack is for '{L['game_name']}'. UBE Tailor works with Skyrim Special Edition only.")
    if not L["data"] or not os.path.isdir(L["data"]):
        out.append(f"Game folder not found: {L['game'] or '(not set in ModOrganizer.ini)'}")
    if not os.path.isdir(L["mods"]):
        out.append(f"Mods folder not found: {L['mods']}")
    if not os.path.isfile(os.path.join(L["profile"], "modlist.txt")):
        out.append(f"Profile not found: {L['profile_name']}")
    elif not os.path.isfile(os.path.join(L["profile"], "plugins.txt")):
        out.append(f"The profile '{L['profile_name']}' has no plugins.txt yet. Start the game from MO2 once.")
    return out


def global_instances():
    d = GLOBAL_INSTANCES
    if not d or not os.path.isdir(d):
        return []
    return [os.path.join(d, n, "ModOrganizer.ini") for n in sorted(os.listdir(d))
            if os.path.isfile(os.path.join(d, n, "ModOrganizer.ini"))]


def inis_in(folder):
    """ModOrganizer.ini files that belong to a folder the user picked (MO2 folder, instance folder, a subfolder)."""
    folder = os.path.abspath(folder)
    for up in (folder, os.path.dirname(folder), os.path.dirname(os.path.dirname(folder))):
        ini = os.path.join(up, "ModOrganizer.ini")
        if os.path.isfile(ini):
            return [ini]
    if os.path.isfile(os.path.join(folder, "ModOrganizer.exe")):
        return global_instances()                 # MO2 installed without a portable instance
    return []


def _running_mo2_dirs():
    out = []
    try:
        psapi, k = ctypes.windll.psapi, ctypes.windll.kernel32
        arr, needed = (ctypes.c_ulong * 8192)(), ctypes.c_ulong()
        psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed))
        for pid in arr[:needed.value // 4]:
            h = k.OpenProcess(0x1000, False, pid)            # query limited information
            if not h:
                continue
            buf, n = ctypes.create_unicode_buffer(1024), ctypes.c_ulong(1024)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and \
                    buf.value.lower().endswith("\\modorganizer.exe"):
                out.append(os.path.dirname(buf.value))
            k.CloseHandle(h)
    except Exception:
        pass
    return out


def guesses():
    """Likely modpacks, best first: an MO2 that is running, a modpack around the tool's folder, global instances."""
    seen, out = set(), []
    for ini in [i for d in _running_mo2_dirs() for i in inis_in(d)] + inis_in(TOOL) + global_instances():
        key = os.path.normcase(os.path.abspath(ini))
        if key not in seen:
            seen.add(key)
            out.append(ini)
    return out


# ---------------------------------------------------------------- settings
def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    os.makedirs(HOME, exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, SETTINGS)


S = load_settings()
L = None
try:
    if S.get("ini") and os.path.isfile(S["ini"]):
        L = layout(S["ini"], S.get("profile"))
except (OSError, configparser.Error):
    L = None
READY = L is not None and not problems(L)

if READY:
    INSTANCE, MODS, OVERWRITE, PROFILE, DATA = L["instance"], L["mods"], L["overwrite"], L["profile"], L["data"]
    OUT_MOD = os.path.normpath(S.get("output_dir") or os.path.join(MODS, OUTPUT_MOD_NAME))
    _key = hashlib.sha1(os.path.normcase(L["ini"] + "|" + L["profile_name"]).encode("utf-8")).hexdigest()[:10]
    WORK = os.path.join(HOME, "work", re.sub(r"[^A-Za-z0-9_\-]", "_", L["profile_name"])[:30] + "_" + _key)
    os.makedirs(WORK, exist_ok=True)
else:
    INSTANCE = MODS = OVERWRITE = PROFILE = DATA = OUT_MOD = WORK = None


def need_ready():
    if not READY:
        raise RuntimeError("No modpack chosen yet. Start UBE Tailor and pick your Mod Organizer 2 folder.")


# ---------------------------------------------------------------- the modpack's virtual file system
def enabled_mods():
    """Enabled mods, highest priority first (modlist.txt lists the highest priority first)."""
    with open(os.path.join(PROFILE, "modlist.txt"), encoding="utf-8", errors="replace") as f:
        return [ln[1:].rstrip("\r\n") for ln in f if ln.startswith("+") and not ln.rstrip().endswith("_separator")]


def _hidden(name):
    """Tests only: UBE_TAILOR_HIDE_PLUGINS="a*.esp;b.esp" makes the tool act as if those plugins were not
    enabled (to try a modpack as if it had no UBE patches yet)."""
    import fnmatch
    pats = [p.strip().lower() for p in os.environ.get("UBE_TAILOR_HIDE_PLUGINS", "").split(";") if p.strip()]
    return any(fnmatch.fnmatch(name.lower(), p) for p in pats)


def enabled_plugins():
    out = []
    with open(os.path.join(PROFILE, "plugins.txt"), encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("*") and not _hidden(line[1:]):
                out.append(line[1:])
    return out


def load_order():
    """Plugin names (lower case) in load order."""
    p = os.path.join(PROFILE, "loadorder.txt")
    if not os.path.isfile(p):
        p = os.path.join(PROFILE, "plugins.txt")
    with open(p, encoding="utf-8", errors="replace") as f:
        return [ln.strip().lstrip("*").lower() for ln in f if ln.strip() and not ln.startswith("#")]


def loose_dirs():
    """Folders whose files the game sees, highest priority first (overwrite, mods, then the game's Data)."""
    return [OVERWRITE] + [os.path.join(MODS, m) for m in enabled_mods()] + [DATA]


def find(rel, dirs=None):
    """Winning loose file for a Data-relative path, or None."""
    for d in dirs or loose_dirs():
        p = os.path.join(d, rel)
        if os.path.isfile(p):
            return p
    return None


def bodyslide_dirs(sub):
    """Existing CalienteTools\\BodySlide\\<sub> folders of the modpack, highest priority first."""
    out = []
    for d in loose_dirs():
        p = os.path.join(d, "CalienteTools", "BodySlide", sub)
        if os.path.isdir(p):
            out.append(p)
    return out


def find_shapedata(filename, folder=None):
    """A BodySlide ShapeData file by name, in any mod (whatever the mod is called). folder = its ShapeData folder
    if known (faster). Returns the path or None."""
    for d in bodyslide_dirs("ShapeData"):
        names = [folder] if folder else os.listdir(d)
        for n in names:
            p = os.path.join(d, n, filename)
            if os.path.isfile(p):
                return p
    if folder:
        return find_shapedata(filename)
    return None


def output_mod_enabled():
    return os.path.normcase(os.path.dirname(OUT_MOD)) != os.path.normcase(MODS) or \
        os.path.basename(OUT_MOD).lower() in (m.lower() for m in enabled_mods())


def mo2_running():
    return bool(_running_mo2_dirs())


def inside_mo2():
    """True when MO2 started this process (its virtual file system DLL is loaded in us)."""
    try:
        k = ctypes.windll.kernel32
        return bool(k.GetModuleHandleW("usvfs_x64.dll") or k.GetModuleHandleW("usvfs_x86.dll"))
    except Exception:
        return False


def can_edit_profile():
    """MO2 keeps the profile files in memory and writes them back, so they may only be changed while MO2 is
    closed, or while MO2 itself is running us (it re-reads them when we exit).
    UBE_TAILOR_READONLY_PROFILE=1 (tests) never allows it."""
    if os.environ.get("UBE_TAILOR_READONLY_PROFILE"):
        return False
    return inside_mo2() or not mo2_running()


def enable_output_mod():
    """Put the output mod at the top priority of modlist.txt, enabled. True if written (or already there)."""
    if output_mod_enabled():
        return True
    if not can_edit_profile():
        return False
    name = os.path.basename(OUT_MOD)
    p = os.path.join(PROFILE, "modlist.txt")
    with open(p, "rb") as f:
        raw = f.read()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    lines = [ln for ln in raw.decode("utf-8", "replace").splitlines() if ln[1:].lower() != name.lower()]
    head = [i for i, ln in enumerate(lines) if ln.startswith("#")]
    lines.insert(head[-1] + 1 if head else 0, "+" + name)      # modlist.txt: first line = highest priority
    backup(p)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(lines) + nl)
    return True


def backup_dir():
    import datetime
    d = os.path.join(HOME, "backups", datetime.date.today().isoformat())
    os.makedirs(d, exist_ok=True)
    return d


def backup(path):
    """Copy a file into today's backup folder once (the first copy of the day is kept)."""
    import shutil
    bk = os.path.join(backup_dir(), os.path.basename(path))
    if os.path.isfile(path) and not os.path.exists(bk):
        shutil.copy2(path, bk)
    return bk


# ---------------------------------------------------------------- what the tool needs from other mods / programs
# Found by their file names wherever they are installed (any mod name, overwrite or the game's Data folder).
UBE_PLUGIN = "UBE_AllRace.esp"
UBE_PARTS = (("body", 32, "UBE SE 2.0 Release Body"), ("feet", 37, "UBE SE 2.0 Release Feet"),
             ("hands", 33, "UBE SE 2.0 Release Hands"))
CONVERSION_REF = "3BA to UBE 2.0"                   # optional file "Conversion references" of UBE 2.0
T3_REF = ("CBBE 3BA Reference", "CBBE 3BA Ref.nif")  # part of CBBE 3BA (3BBB)


def find_sliderset(folder):
    """The BodySlide project (.osp) whose SliderSet uses ShapeData folder `folder`, or None."""
    import xml.etree.ElementTree as ET
    dirs = bodyslide_dirs("SliderSets")
    for d in dirs:                                  # usual name first: "<folder>.osp"
        p = os.path.join(d, folder + ".osp")
        if os.path.isfile(p):
            return p
    for d in dirs:
        for fn in os.listdir(d):
            if not fn.lower().endswith(".osp"):
                continue
            try:
                root = ET.parse(os.path.join(d, fn)).getroot()
            except (ET.ParseError, OSError):
                continue
            if any((ss.findtext("DataFolder") or "").strip() == folder for ss in root.iter("SliderSet")):
                return os.path.join(d, fn)
    return None


def ube_part(folder):
    """(nif, osd, osp) of a UBE base part (body / feet / hands); missing files are None."""
    nif = find_shapedata(folder + ".nif", folder)
    osd = os.path.join(os.path.dirname(nif), folder + ".osd") if nif else None
    return nif, osd if osd and os.path.isfile(osd) else None, find_sliderset(folder)


def conversion_ref():
    """(nif, osd) of UBE's official '3BA to UBE 2.0' conversion reference, or (None, None)."""
    nif = find_shapedata(CONVERSION_REF + ".nif", CONVERSION_REF)
    if not nif:
        for d in (S.get("refs_dir") or "", os.path.join(HOME, "refs", CONVERSION_REF)):
            p = os.path.join(d, CONVERSION_REF + ".nif") if d else ""
            if p and os.path.isfile(p):
                nif = p
                break
    osd = nif[:-4] + ".osd" if nif else None
    return (nif, osd) if osd and os.path.isfile(osd) else (None, None)


def t3_ref():
    return find_shapedata(T3_REF[1], T3_REF[0])


def bodyslide_exe():
    for d in loose_dirs():
        for n in ("BodySlide x64.exe", "BodySlide.exe"):
            p = os.path.join(d, "CalienteTools", "BodySlide", n)
            if os.path.isfile(p):
                return p
    return None


def plugin_path(name):
    """Winning file of a plugin (mods by priority, overwrite, game Data), or None."""
    return find(name)


def _pynifly_ok(d):
    return bool(d) and os.path.isfile(os.path.join(d, "io_scene_nifly", "pyn", "pynifly.py"))


def pynifly_candidates():
    import glob
    out = [S.get("pynifly") or "", os.path.join(TOOL, "pynifly"), os.path.join(TOOL, "lib", "pynifly"),
           os.path.join(os.path.dirname(TOOL), "pynifly")]
    appdata = os.environ.get("APPDATA") or ""
    if appdata:                                     # PyNifly installed in Blender (add-on or 4.2+ extension)
        for pat in (r"Blender Foundation\Blender\*\scripts\addons",
                    r"Blender Foundation\Blender\*\extensions\*"):
            out += sorted(glob.glob(os.path.join(appdata, pat)), reverse=True)
    return out


def find_pynifly():
    """Folder that holds PyNifly's io_scene_nifly package, or None."""
    return next((os.path.normpath(d) for d in pynifly_candidates() if _pynifly_ok(d)), None)


def preset():
    return S.get("preset") or ""


def set_preset(name):
    S["preset"] = name
    save_settings(S)
