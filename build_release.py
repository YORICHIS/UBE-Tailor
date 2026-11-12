# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Build the release folder + zip: the tool, UBE Tailor.bat, a bundled Python (numpy, scipy, tkinter) and PyNifly.

  python build_release.py [--icon default|custom] [--no-python] [--no-zip] [--exe]
  (--exe also builds the old UBE Tailor.exe launcher from launcher.cs; virus scanners flag it, so it is off)

Output: dist\\UBE Tailor <version>\\ and dist\\UBE Tailor <version>.zip. Nothing outside dist\\ is written.
The Python runtime is copied from the Python running this script (same version everywhere: build with 3.12).
Before zipping, every file is scanned for the builder's user name, home folder and e-mail addresses; the build stops
if one is found (compiled .pyc files and pip's install records, which carry local paths, are never copied).
"""
import argparse
import fnmatch
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import env  # noqa: E402

APP_FILES = ["*.py", "README.md", "CREDITS.md", "CHANGELOG.md", "LICENSE", "UBE Tailor.bat"]
NOT_SHIPPED = {"build_release.py"}
ICONS = {"default": ["tailor_icon_256.png", "tailor_icon_64.png", "tailor_icon_32.png"],
         "custom": ["tailor_icon_custom.png", "tailor_icon_custom_96.png", "tailor_icon_custom_64.png",
                    "tailor_icon_custom_32.png", "tailor_icon_256.png", "tailor_icon_64.png", "tailor_icon_32.png"]}
SKIP_DIRS = {"__pycache__", "test", "tests", "idlelib", "ensurepip", "lib2to3", "turtledemo", "site-packages",
             "pydoc_data", "venv", "nmake"}          # tcl\nmake: a build helper .exe the tool never needs
SKIP_FILES = ["*.pyc", "*.pyo", "direct_url.json", "RECORD", "INSTALLER", "REQUESTED", "*.whl"]
KEEP_PACKAGES = ["numpy", "numpy.libs", "numpy-*.dist-info", "scipy", "scipy.libs", "scipy-*.dist-info"]
SCIPY_KEEP = {"_lib", "_external", "constants", "linalg", "sparse", "spatial", "special"}   # what cKDTree loads
CSC = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")


def skip(name, patterns):
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def copytree(src, dst, skip_dirs=SKIP_DIRS, prune=None):
    for dp, dn, fn in os.walk(src):
        rel = os.path.relpath(dp, src)
        dn[:] = [d for d in dn if d not in skip_dirs and not (prune and prune(rel, d))]
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in fn:
            if not skip(f, SKIP_FILES):
                shutil.copy2(os.path.join(dp, f), os.path.join(dst, rel, f))


def make_ico(pngs, out):
    """A Windows .ico made of PNG images (Vista and later read PNG icon entries)."""
    datas = [open(p, "rb").read() for p in pngs]
    head = struct.pack("<HHH", 0, 1, len(datas))
    off = 6 + 16 * len(datas)
    entries = b""
    for d in datas:
        w, h = struct.unpack(">II", d[16:24])
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(d), off)
        off += len(d)
    with open(out, "wb") as f:
        f.write(head + entries + b"".join(datas))


def bundle_python(dst):
    base = sys.base_prefix
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(base):
        p = os.path.join(base, f)
        if os.path.isfile(p) and (f.lower().endswith((".exe", ".dll")) or f == "LICENSE.txt"):
            shutil.copy2(p, dst)
    for d in ("DLLs", "Lib", "tcl"):
        if os.path.isdir(os.path.join(base, d)):
            copytree(os.path.join(base, d), os.path.join(dst, d))
    site_src = os.path.join(base, "Lib", "site-packages")
    site_dst = os.path.join(dst, "Lib", "site-packages")
    os.makedirs(site_dst, exist_ok=True)
    for name in os.listdir(site_src):
        if not skip(name, KEEP_PACKAGES):
            continue
        src = os.path.join(site_src, name)
        if os.path.isdir(src):
            prune = (lambda rel, d: rel == "." and not d.startswith("__") and d not in SCIPY_KEEP) \
                if name == "scipy" else None
            copytree(src, os.path.join(site_dst, name), skip_dirs={"__pycache__", "tests"}, prune=prune)


def bundle_pynifly(dst):
    src = env.find_pynifly()
    if not src:
        sys.exit("PyNifly not found: put it in a folder named 'pynifly' next to this script")
    copytree(os.path.join(src, "io_scene_nifly"), os.path.join(dst, "io_scene_nifly"),
             skip_dirs={"__pycache__", "tests"})
    shutil.copy2(os.path.join(HERE, "LICENSE"), os.path.join(dst, "LICENSE"))
    with open(os.path.join(dst, "README.txt"), "w", encoding="utf-8") as f:
        f.write("PyNifly by BadDogSkyrim, GNU GPL v3 (see LICENSE). Unchanged copy, shipped with UBE Tailor.\n"
                "Source code and releases: https://github.com/BadDogSkyrim/PyNifly\n")


def privacy_scan(root):
    """Hits of the builder's user name / home folder in any file, and of e-mail addresses in UBE Tailor's own files
    (Python, numpy, scipy and PyNifly carry their authors' public addresses). Extra private words to look for can be
    given in the UBE_TAILOR_PRIVATE_WORDS environment variable ("a;b"), so they are never written into a file."""
    home = os.path.expanduser("~")
    user = os.environ.get("USERNAME") or os.path.basename(home)
    extra = [w.strip() for w in os.environ.get("UBE_TAILOR_PRIVATE_WORDS", "").split(";") if w.strip()]
    needles = {home, home.replace("\\", "/"), home.replace("\\", "\\\\"), user, *extra}
    needles = {n for n in needles if n and len(n) >= 3}
    third_party = (os.path.join(root, "python"), os.path.join(root, "pynifly"))
    raw = [n.encode("utf-8") for n in needles] + [n.encode("utf-16-le") for n in needles]
    mail = re.compile(rb"[A-Za-z0-9._%+-]+@(gmail|hotmail|outlook|yahoo|icloud|proton)\.", re.I)
    hits = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            try:
                b = open(p, "rb").read()
            except OSError:
                continue
            low = b.lower()
            for n in raw:
                if n.lower() in low:
                    hits.append((os.path.relpath(p, root), n.decode("utf-8", "replace")))
                    break
            if not p.startswith(third_party) and mail.search(b):
                hits.append((os.path.relpath(p, root), "e-mail address"))
    return hits


def smoke_test(out):
    py = os.path.join(out, "python", "python.exe")
    if not os.path.isfile(py):
        return
    code = ("import sys, tkinter, numpy; from scipy.spatial import cKDTree; import nifly_env, requirements; "
            "print('python', sys.version.split()[0], '| numpy', numpy.__version__, '| PyNifly', nifly_env.PYNIFLY)")
    r = subprocess.run([py, "-s", "-E", "-c", code], cwd=out, capture_output=True, text=True)
    print("   smoke test:", (r.stdout or r.stderr).strip()[-400:])
    if r.returncode:
        sys.exit("smoke test failed")
    if os.path.normcase(os.path.join(out, "pynifly")) not in os.path.normcase(r.stdout):
        sys.exit("smoke test: the bundled PyNifly was not the one used")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--icon", choices=list(ICONS), default="default")
    ap.add_argument("--no-python", action="store_true", help="leave the Python runtime out (small download)")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--exe", action="store_true", help="also build UBE Tailor.exe from launcher.cs")
    a = ap.parse_args()
    name = f"UBE Tailor {env.VERSION}"
    dist = os.path.join(HERE, "dist")
    out = os.path.join(dist, name)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    print(f"building {name} ({'with' if not a.no_python else 'without'} Python, {a.icon} icon)")
    for pat in APP_FILES + ICONS[a.icon]:
        for f in sorted(os.listdir(HERE)):
            if fnmatch.fnmatch(f, pat) and f not in NOT_SHIPPED and os.path.isfile(os.path.join(HERE, f)):
                shutil.copy2(os.path.join(HERE, f), out)
    if a.exe:                  # optional .exe launcher (unsigned: virus scanners flag it as a "binder")
        ico = os.path.join(out, "tailor.ico")
        if a.icon == "custom":
            shutil.copy2(os.path.join(HERE, "tailor.ico"), ico)
        else:
            make_ico([os.path.join(HERE, n) for n in ICONS["default"]], ico)
        shutil.copy2(os.path.join(HERE, "launcher.cs"), out)
        r = subprocess.run([CSC, "/nologo", "/target:winexe", f"/win32icon:{ico}", "/r:System.Windows.Forms.dll",
                            f"/out:{os.path.join(out, 'UBE Tailor.exe')}", os.path.join(out, "launcher.cs")],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit("launcher build failed:\n" + r.stdout + r.stderr)
        print("   UBE Tailor.exe built")
    print("   start with: UBE Tailor.bat")
    bundle_pynifly(os.path.join(out, "pynifly"))
    print("   PyNifly copied")
    if not a.no_python:
        bundle_python(os.path.join(out, "python"))
        print(f"   Python {sys.version.split()[0]} + numpy + scipy copied")
    smoke_test(out)
    for dp, dn, _fn in os.walk(out):                  # the smoke test may have compiled files: never ship them
        for d in list(dn):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dp, d))
                dn.remove(d)
    hits = privacy_scan(out)
    if hits:
        for p, what in hits[:30]:
            print("   PRIVACY:", p, "->", what)
        sys.exit(f"privacy scan found {len(hits)} file(s) with personal data - nothing zipped")
    print("   privacy scan: clean")
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _d, fn in os.walk(out) for f in fn)
    print(f"   folder: {size / 1e6:.0f} MB")
    if not a.no_zip:
        z = out + ".zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for dp, _dn, fn in os.walk(out):
                for f in fn:
                    p = os.path.join(dp, f)
                    zf.write(p, os.path.join(name, os.path.relpath(p, out)))
        print(f"   zip: {z} ({os.path.getsize(z) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
