# UBE Tailor

**by Desertravel** · version 0.9.0-beta · [العربية](#العربية)

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
2. Optional: add `UBE Tailor.exe` to MO2's executables (it also works when started on its own).

## Use
1. **Start `UBE Tailor.exe`** and pick your MO2 folder (the one with `ModOrganizer.exe` / `ModOrganizer.ini`).
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

## Build from source
Everything in the download is built from this source:
- `UBE Tailor.exe` is compiled from `launcher.cs` with the C# compiler that ships with Windows (.NET Framework 4):
  `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /target:winexe /win32icon:tailor.ico /r:System.Windows.Forms.dll /out:"UBE Tailor.exe" launcher.cs`
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

---

<div dir="rtl">

## العربية

# UBE Tailor
**من Desertravel** · النسخة 0.9.0-beta

ملابسك حق 3BA و CBBE، تصير مقاسها على جسم **UBE 2.0**. الأداة تحوّلها لمشاريع BodySlide حقيقية لـ UBE: اللبس
يتظبط على شكل UBE، وياخذ كل سلايدرات الجسم وأوزان عظام UBE. وتسوي بلقن صغير واحد اسمه `UBE Tailor.esp`، عشان
شخصيات UBE تلبس النسخ المحوّلة. وأنت تبنيها في BodySlide مثل أي لبس.

تشتغل مع أي مود باك **Mod Organizer 2** لـ **Skyrim Special Edition / AE**.

## وش تسوي
- تلقى كل الملابس في لستتك اللي تقدر عروق UBE تلبسها، وتوريك وش اتحوّل ووش لا.
- تحوّل الطقم كامل (كل قطعه مع بعض) لمشاريع BodySlide في مجموعة **UBE Auto Conversions**.
- تخلي فيزياء SMP تشتغل (ما تضيف عظام تطيح)، وتصلح أرجل الشراب اللي على وضعية الكعب، وتخلي اللبس يمشي مع بريسيتات
  OBody و RaceMenu.
- تعطي كل قطعة درجة: المقاس على بريسيتك (A أو B أو C)، وكيف تمشي مع الجسم وهو يتحرك.
- تسوي `UBE Tailor.esp`: وما تأشّر على مش UBE إلا بعد ما BodySlide يبنيه، فما في قطع مخفية. والملابس اللي عليها باتش
  UBE ثاني ما تعدّل باتشها، تحط عليه override داخل `UBE Tailor.esp`.
- **فحص الصحة (Health check)**: يلقى المشاكل المعروفة ويصلحها بزر واحد.

## تحتاج
UBE 2.0 (مع `UBE_AllRace.esp` مفعّل)، وملف **Conversion references** من صفحة UBE 2.0 (تبويب Files)، و CBBE 3BA،
و BodySlide. واختياري: RaceMenu و OBody NG.
Python و numpy و scipy و PyNifly يجون مع التحميل الكامل. الأداة تشيّك على كل شي أول مرة تشتغل، وأي شي ناقص تفتح لك
صفحته الرسمية، **وعمرها ما تحمّل شي بروحها**.

## التثبيت
1. فك الملف المضغوط في أي مكان برّا مجلد اللعبة، مثلاً `D:\Modding\UBE Tailor`.
2. اختياري: ضيف `UBE Tailor.exe` لقائمة البرامج في MO2.

## الاستخدام
1. **شغّل `UBE Tailor.exe`** واختر مجلد الـ MO2 حقك.
2. **المتطلبات**: ثبّت اللي ناقص واضغط *Check again*.
3. اختر **بريسيت UBE** حقك (فوق يمين).
4. علّم على الملابس واضغط **Convert selected**. باقي قطع نفس الطقم تنضاف بروحها.
5. **سكّر MO2** (أو شغّل الأداة من داخل MO2) واضغط **Scan**: الأداة تفعّل مودها `UBE Tailor Output` وتعلّم على
   `UBE Tailor.esp` آخر الترتيب. ولو MO2 مفتوح لحاله، الأداة ما تلمس البروفايل. وقتها اضغط F5 في MO2، وفعّل
   `UBE Tailor Output`، وعلّم على `UBE Tailor.esp`.
6. **BodySlide**: اختر مجموعة **UBE Auto Conversions** وبريسيتك، علّم على *Build Morphs*، واضغط **Batch Build**.
7. ارجع للأداة واضغط **Scan** مرة ثانية، وكل قطعة انبنت تصير على مش UBE. العب.

سكّر اللعبة وقت ما الأداة تشتغل. والسطور الذهبية اللي تبدأ بـ *Next:* في السجل تقولك الخطوة الجاية.

## الترخيص
الأداة مجانية تحت رخصة **GNU GPL v3 أو أحدث**، والحقوق © 2026 Desertravel. أي أحد يعدّلها وينشرها لازم يخلي
اسم صاحبها والترخيص. ملفات UBE 2.0 والـ references و CBBE 3BA و BodySlide ملك أصحابها، **وما هي موجودة** في
الأداة.

</div>
