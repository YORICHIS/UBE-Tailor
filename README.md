# UBE Tailor

**by Desertravel** · version 0.9.1-beta

Your 3BA / CBBE outfits, made for the **UBE 2.0** body. UBE Tailor turns them into real UBE BodySlide projects -
the outfit is fitted to the UBE shape, gets every UBE body slider and UBE's bone weights - plus one small plugin,
`UBE Tailor.esp`, so UBE characters wear the converted meshes. You build them in BodySlide like any other outfit.

Works with any **Mod Organizer 2** modpack for **Skyrim Special Edition / AE**.

## What it does
- Finds every outfit in your load order that UBE races can wear, and shows what is converted and what is not.
- Converts whole outfits (all pieces of a set together) into BodySlide projects in the group
  **UBE Auto Conversions**: UBE body, feet and hands added, the old 3BA body hidden, all UBE sliders, anti-clip.
- Keeps HDT-SMP physics working (never adds bones that would fall), fixes heel-posed stocking feet, and makes the
  converted meshes follow OBody / RaceMenu body presets (morph files).
- Grades each piece: fit at your preset (A / B / C) and how it follows the body while moving.
- Builds `UBE Tailor.esp`: UBE copies of the armor addons, pointed at the UBE meshes only once BodySlide has built
  them (no invisible pieces). Outfits already covered by another UBE patch (for example made with UBE's xEdit
  script) are overridden in `UBE Tailor.esp` - the other patch is never edited.
- **Health check**: finds known problems and fixes them with one button.

## You need
| | |
|---|---|
| [UBE 2.0](https://www.nexusmods.com/skyrimspecialedition/mods/92989) | the body, with `UBE_AllRace.esp` enabled |
| UBE **Conversion references** | optional file on the [UBE 2.0 files page](https://www.nexusmods.com/skyrimspecialedition/mods/92989?tab=files) - install it in MO2 like any mod |
| [CBBE 3BA (3BBB)](https://www.nexusmods.com/skyrimspecialedition/mods/30174) | your 3BA outfits need it anyway |
| [BodySlide and Outfit Studio](https://www.nexusmods.com/skyrimspecialedition/mods/201) | to build the converted outfits |
| optional: [RaceMenu](https://www.nexusmods.com/skyrimspecialedition/mods/19080), [OBody NG](https://www.nexusmods.com/skyrimspecialedition/mods/77016) | body morphs / presets in game |

Python, numpy, scipy and PyNifly come with the full download. The tool checks all of this on the first start and,
for anything missing, opens the official page - **it never downloads anything by itself**.

## Install
1. Unpack the zip anywhere outside the game folder, for example `D:\Modding\UBE Tailor`.
2. Optional: add it to MO2's executables - Binary: `python\pythonw.exe` in the UBE Tailor folder, Arguments:
   `-s -E tailor_gui.py`, Start in: the UBE Tailor folder. It also works when started on its own.

## Use
1. **Start `UBE Tailor.exe`** (0.9.0) or **`UBE Tailor.bat`** (0.9.1) and pick your MO2 folder (the one with `ModOrganizer.exe` / `ModOrganizer.ini`).
2. **Requirements**: install what the screen shows as missing, press *Check again*.
3. Pick your **UBE preset** (top right) - the one you build your UBE body with.
4. Tick outfits and press **Convert selected**. Pieces of the same outfit come along on their own.
5. **Close MO2** (or start the Tailor from MO2) and press **Scan**: the Tailor enables its mod
   `UBE Tailor Output` and ticks `UBE Tailor.esp` at the end of your load order. While MO2 is open on its own the
   Tailor does not touch your profile; then press F5 in MO2, enable `UBE Tailor Output` and tick `UBE Tailor.esp`.
6. **BodySlide** (from MO2): group **UBE Auto Conversions**, your UBE preset, tick *Build Morphs*, **Batch Build**.
7. Back in the Tailor press **Scan** again: every built piece now uses its UBE mesh. Play.

Close the game while the Tailor works. The gold *Next:* lines in the log always say what to do next.

## Where things go
- Projects and the plugin: the mod `UBE Tailor Output` in your MO2 mods folder (one mod; disable it to undo).
- Settings, cache and backups of every profile file the Tailor changes: `%LOCALAPPDATA%\UBE Tailor`.

## Why are there two versions (0.9.0 and 0.9.1)?
Both are the **same tool** and do exactly the same thing. The only difference is how it starts:

| | starts with | notes |
|---|---|---|
| **0.9.0** (main) | `UBE Tailor.exe` | a small launcher I compiled from `launcher.cs`; shows the UBE Tailor icon |
| **0.9.1** | `UBE Tailor.bat` | a plain text start script you can open in Notepad |

What happened: after the first upload, 4 of 64 virus scanners on VirusTotal flagged `UBE Tailor.exe`. They are
machine-learning guesses ("binder") about a new, unsigned little program that starts another program - here it
starts the bundled Python. It is a false positive, nothing harmful, and the whole source is in this repository.
Nexus Mods held the file for a manual review because of it.

To be safe I made 0.9.1 without the .exe: it starts with `UBE Tailor.bat` instead, and VirusTotal shows 0/68.
Nexus still checks this one by hand too, because the official `python.exe` / `pythonw.exe` from python.org are
inside (every download with an .exe in it is reviewed by hand), so both downloads open once Nexus approves them.

Use 0.9.0 if you like the .exe and icon; use 0.9.1 if your antivirus complains about the .exe.

## Build from source
Everything in the download is built from this source:
- `UBE Tailor.bat` is a plain text start script (open it in Notepad to see it): it runs `tailor_gui.py` with the
  bundled Python. `launcher.cs` is an optional .exe launcher (`build_release.py --exe`), not shipped by default.
- `python\` is an unchanged copy of the official Python 3.12 for Windows from python.org, with numpy and scipy from PyPI
  (`py -3.12 -m pip install numpy scipy`); compiled `.pyc` files and pip's install records are left out.
- `pynifly\` is an unchanged copy of PyNifly 30.2.0 (https://github.com/BadDogSkyrim/PyNifly/releases).
- To build the whole release: put PyNifly's `io_scene_nifly` folder in a folder named `pynifly` next to the source,
  then run `py -3.12 build_release.py --icon custom`. It writes `dist\UBE Tailor <version>.zip`.
- Without the download: `py -3.12 -m pip install numpy scipy`, add PyNifly as above, then `py -3.12 tailor_gui.py`.

## Not supported yet
Single-weight meshes (no `_0` / `_1`), Skyrim LE meshes (port them to SE first), localized plugins, other games.

## Credits and license
UBE Tailor is free software under the **GNU GPL v3 or later** ([LICENSE](LICENSE)) - Copyright (C) 2026 Desertravel.
It ships PyNifly (GPL-3.0) and Python with numpy and scipy; see [CREDITS.md](CREDITS.md). UBE 2.0, its references,
CBBE 3BA and BodySlide belong to their authors and are **not** included.
