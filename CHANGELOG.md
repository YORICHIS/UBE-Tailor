# Changelog

## Unreleased
- Knows which Skyrim the modpack runs (reads SkyrimSE.exe: SE 1.5.97 or AE 1.6.x, shown bottom right and in the
  requirements screen) and asks when it cannot tell. On SE / older AE it warns when plugins of the modpack use the
  newer AE format (header 1.71) and BEES is not installed.
- Outfit mods made for Skyrim LE (never re-saved for SE) are marked "LE plugin" in the list, and the Tailor asks
  before converting them: they usually work, but can have other LE problems.
- Fixed a crash at game start (CTD while loading, e.g. with Hermit Armor or Heels Fix): records copied from old
  plugins that were never re-saved for SE (form version below 40) were written as version 44, but their texture
  hash data was still in the old layout, so the game misread it. Copies now keep their source's form version.
- `UBE Tailor.esp` is written with plugin header version 1.70 instead of 1.71, so it also loads on Skyrim SE 1.5.97
  (1.71 needs AE 1.6.1130 or newer). Nothing else changes: the plugin's ids were already in the 0x800-0xFFF range.

## 0.9.1-beta (2026-11-12)
- Starts with `UBE Tailor.bat` instead of `UBE Tailor.exe`: virus scanners flagged the small unsigned .exe launcher
  as a "binder" (false positive). The .bat is plain text you can read.
- Left out an unused helper .exe of Tcl (`tcl\nmake`). README in English, with build-from-source steps.

## 0.9.0-beta (2026-11-12) - first public beta
- Works with any Mod Organizer 2 modpack (paths, profile and game read from ModOrganizer.ini).
- First start: welcome guide, modpack picker, requirements screen (opens official pages, never downloads).
- One merged plugin `UBE Tailor.esp` (ESL, splits at 250 masters / 2048 records); no xEdit patches needed.
- Outfits covered by other UBE patches are overridden in `UBE Tailor.esp`, never edited.
- Points at UBE meshes only once BodySlide has built them; slot-53 rule per outfit; head pieces judged by the mesh.
- Fit and motion grades, whole-outfit conversion, left-out / outdated detection, health check with "Fix all".
- HDT-SMP safety (no falling bones), BODYTRI fix for OBody / RaceMenu morphs, flat feet for heel-posed stockings.
