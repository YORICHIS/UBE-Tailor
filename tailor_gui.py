# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""UBE Tailor window: pick outfits, convert them to UBE BodySlide projects, grade the fit, patch the plugins.
Start it with "UBE Tailor.exe" (or "UBE Tailor.bat") or from MO2's executables. The final Batch Build is done
in BodySlide. On the first start it asks for the Mod Organizer 2 modpack and shows what is installed / missing.
"""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from collections import Counter
from tkinter import filedialog, messagebox, ttk

import env

tc = None                     # tailor_core: imported once the modpack and PyNifly are there (see main())

ALL = "All"
LEFT_OUT = "Left out of a converted outfit"
OUTDATED = "Made with an older Tailor"
# palette (dark teal + gold, matching the icon)
BG, PANEL, FIELD, HOVER = "#0f2228", "#17343c", "#0a181c", "#1f4650"
FG, MUTED, ACCENT, ACCENT2, GOLD, SEL = "#e8f2f3", "#8fb3b8", "#1fa6ac", "#2cc4ca", "#ffd166", "#1f5560"
GRADE = {"A": "#5fd38d", "B": GOLD, "C": "#ff7b7b"}
FONT, FONT_B, MONO = ("Segoe UI", 10), ("Segoe UI Semibold", 10), ("Consolas", 10)


def apply_theme(root):
    root.configure(bg=BG)
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=BG, foreground=FG, font=FONT, bordercolor=PANEL, lightcolor=PANEL,
                 darkcolor=PANEL, troughcolor=FIELD, focuscolor=BG)
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("Title.TLabel", font=("Segoe UI Semibold", 20))
    st.configure("Sub.TLabel", foreground=MUTED)
    st.configure("TButton", background=PANEL, foreground=FG, padding=(14, 7), borderwidth=0, relief="flat")
    st.map("TButton", background=[("disabled", "#13282e"), ("pressed", ACCENT), ("active", HOVER)],
           foreground=[("disabled", "#56757a")])
    st.configure("Accent.TButton", background=ACCENT, foreground="#041417", font=FONT_B)
    st.map("Accent.TButton", background=[("disabled", "#14484c"), ("pressed", GOLD), ("active", ACCENT2)],
           foreground=[("disabled", "#5d8a8d")])
    st.configure("Card.TButton", background=HOVER, foreground=FG)       # a plain button on a PANEL card
    st.map("Card.TButton", background=[("pressed", ACCENT), ("active", "#2a5a66")])
    st.configure("Danger.TButton", background="#5a2a2e")
    st.map("Danger.TButton", background=[("disabled", "#13282e"), ("active", "#8a3138")])
    st.configure("TCombobox", fieldbackground=FIELD, background=PANEL, foreground=FG, arrowcolor=GOLD,
                 selectbackground=FIELD, selectforeground=FG, padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
           selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)])
    for k, v in (("background", FIELD), ("foreground", FG), ("selectBackground", SEL), ("selectForeground", FG)):
        root.option_add("*TCombobox*Listbox." + k, v)
    st.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG, padding=4)
    st.configure("TSpinbox", fieldbackground=FIELD, foreground=FG, insertcolor=FG, arrowcolor=GOLD,
                 background=PANEL, padding=3)
    st.configure("TCheckbutton", background=BG, foreground=FG)
    st.map("TCheckbutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])
    st.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=FG, rowheight=26, borderwidth=0)
    st.map("Treeview", background=[("selected", SEL)], foreground=[("selected", FG)])
    st.configure("Treeview.Heading", background=PANEL, foreground=GOLD, font=FONT_B, relief="flat", padding=(6, 6))
    st.map("Treeview.Heading", background=[("active", HOVER)])
    st.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG, arrowcolor=MUTED, bordercolor=BG)
    st.map("Vertical.TScrollbar", background=[("active", ACCENT)])
    st.configure("Horizontal.TProgressbar", troughcolor=FIELD, background=ACCENT, bordercolor=FIELD,
                 lightcolor=ACCENT, darkcolor=ACCENT, thickness=12)
    try:                                  # dark title bar on Windows 10/11
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        v = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("UBE Tailor")
        root.geometry("1200x800")
        root.minsize(980, 620)
        self.items, self.db, self.checked = [], {}, set()
        self.q = queue.Queue()
        self.busy = False
        self.stop_flag = False
        self.offered_fix = False

        # header: picture, title, live counters
        head = ttk.Frame(root, padding=(14, 12, 14, 6))
        head.pack(fill="x")
        if getattr(root, "_art", None) is not None:
            ttk.Label(head, image=root._art).pack(side="left", padx=(0, 12))
        names = ttk.Frame(head)
        names.pack(side="left")
        ttk.Label(names, text="UBE Tailor", style="Title.TLabel").pack(anchor="w")
        ttk.Label(names, text="Turns 3BA outfits into UBE BodySlide projects", style="Sub.TLabel").pack(anchor="w")
        side = ttk.Frame(head)
        side.pack(side="left", padx=(24, 0))
        ttk.Label(side, style="Sub.TLabel", text=f"{os.path.basename(env.INSTANCE)}  ·  profile {env.L['profile_name']}"
                  ).pack(anchor="w")
        links = ttk.Frame(side)
        links.pack(anchor="w", pady=(4, 0))
        ttk.Button(links, text="Modpack...", command=lambda: SetupWindow(root)).pack(side="left", padx=(0, 6))
        ttk.Button(links, text="Requirements", command=lambda: RequirementsWindow(root, None, first=True)).pack(side="left")
        ttk.Button(links, text="Guide", command=lambda: WelcomeWindow(root)).pack(side="left", padx=(6, 0))
        self.chips = {}
        chips = ttk.Frame(head)
        chips.pack(side="right")
        for key, label, col in (("done", "Done", GRADE["A"]), ("built", "Needs patch", ACCENT2),
                                ("pending", "To convert", GOLD)):
            box = tk.Frame(chips, bg=PANEL, padx=14, pady=6)
            box.pack(side="right", padx=4)
            num = tk.Label(box, text="-", bg=PANEL, fg=col, font=("Segoe UI Semibold", 16))
            num.pack()
            tk.Label(box, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack()
            self.chips[key] = num

        top = ttk.Frame(root, padding=(14, 6))
        top.pack(fill="x")
        self.btn_scan = ttk.Button(top, text="Scan", command=self.do_scan)
        self.btn_conv = ttk.Button(top, text="Convert selected", command=self.do_convert, style="Accent.TButton")
        self.btn_qa = ttk.Button(top, text="Check fit", command=self.do_qa)
        self.btn_patch = ttk.Button(top, text="Update patch", command=self.do_patch)
        self.btn_doc = ttk.Button(top, text="Health check", command=self.do_doctor)
        self.btn_stop = ttk.Button(top, text="Stop", command=self.do_stop, state="disabled", style="Danger.TButton")
        for b in (self.btn_scan, self.btn_conv, self.btn_qa, self.btn_patch, self.btn_doc, self.btn_stop):
            b.pack(side="left", padx=(0, 6))
        self.redo = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Re-convert done ones", variable=self.redo).pack(side="right")
        self.workers = tk.IntVar(value=min(6, max(1, (os.cpu_count() or 4) // 2)))
        ttk.Spinbox(top, from_=1, to=16, width=4, textvariable=self.workers).pack(side="right", padx=(4, 14))
        ttk.Label(top, text="Workers", style="Sub.TLabel").pack(side="right")
        self.preset = ttk.Combobox(top, width=15, state="readonly")
        self.preset.pack(side="right", padx=(4, 14))
        self.preset.bind("<<ComboboxSelected>>", lambda _e: env.set_preset(self.preset.get()))
        ttk.Label(top, text="Preset", style="Sub.TLabel").pack(side="right")

        flt = ttk.Frame(root, padding=(14, 4))
        flt.pack(fill="x")
        ttk.Label(flt, text="Search", style="Sub.TLabel").pack(side="left")
        self.text = tk.StringVar()
        e = ttk.Entry(flt, textvariable=self.text, width=28)
        e.pack(side="left", padx=(6, 14))
        e.bind("<KeyRelease>", lambda _e: self.populate())
        ttk.Label(flt, text="Show", style="Sub.TLabel").pack(side="left")
        self.kind = ttk.Combobox(flt, width=16, state="readonly", values=list(tc.KINDS.values()) + [ALL])
        self.kind.set(tc.KINDS["clothing"])            # default: outfits only, no jewelry / devices / NPC parts
        self.kind.pack(side="left", padx=(6, 14))
        self.kind.bind("<<ComboboxSelected>>", lambda _e: self.populate())
        ttk.Label(flt, text="State", style="Sub.TLabel").pack(side="left")
        self.state = ttk.Combobox(flt, width=26, state="readonly", values=[ALL, LEFT_OUT, OUTDATED] + list(tc.STATES.values()))
        self.state.set(tc.STATES["pending"])
        self.state.pack(side="left", padx=(6, 14))
        self.state.bind("<<ComboboxSelected>>", lambda _e: self.populate())
        ttk.Button(flt, text="Select shown", command=lambda: self.check_visible(True)).pack(side="left", padx=(0, 6))
        ttk.Button(flt, text="Clear selection", command=lambda: self.check_visible(False)).pack(side="left")
        self.count = ttk.Label(flt, text="", style="Sub.TLabel")
        self.count.pack(side="right")

        mid = ttk.Frame(root, padding=(14, 6))
        mid.pack(fill="both", expand=True)
        cols = ("check", "state", "grade", "slots")
        self.tree = ttk.Treeview(mid, columns=cols, selectmode="none")
        self.tree.heading("#0", text="Mod / piece", anchor="w")
        for c, t, w in (("check", "✓", 46), ("state", "State", 210), ("grade", "Fit · moving", 330), ("slots", "Slots", 120)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center", stretch=False)
        self.tree.column("#0", width=540)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.tag_configure("grp", font=FONT_B, foreground="#bfe9ec", background=PANEL)
        self.tree.tag_configure("odd", background="#0d1e23")
        for g, col in GRADE.items():
            self.tree.tag_configure(g, foreground=col)

        bot = ttk.Frame(root, padding=(14, 4))
        bot.pack(fill="x")
        self.bar = ttk.Progressbar(bot, maximum=100)
        self.bar.pack(fill="x")
        line = ttk.Frame(bot)
        line.pack(fill="x", pady=(3, 0))
        self.status = ttk.Label(line, text="Ready", style="Sub.TLabel")
        self.status.pack(side="left")
        tk.Label(line, text=f"UBE Tailor {env.VERSION}  ·  by {env.AUTHOR}", bg=BG, fg=GOLD,
                 font=("Segoe UI Semibold", 9)).pack(side="right")
        self.log = tk.Text(root, height=9, wrap="word", bg=FIELD, fg="#cfe6e8", insertbackground=FG, font=MONO,
                           relief="flat", padx=10, pady=8, highlightthickness=0)
        self.log.tag_configure("bad", foreground=GRADE["C"])
        self.log.tag_configure("next", foreground=GOLD)
        self.log.pack(fill="both", padx=14, pady=(4, 14))

        root.after(100, self.poll)
        root.after(200, self.do_scan)

    # ------------------------------------------------------------ helpers
    def say(self, s):
        self.q.put(("log", s))

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    tag = "bad" if ("failed:" in val or val.startswith("Error")) else "next" if val.startswith("Next:") else ""
                    self.log.insert("end", val + "\n", tag)
                    self.log.see("end")
                elif kind == "prog":
                    i, total, text = val
                    self.bar["value"] = 100.0 * i / max(total, 1)
                    self.status["text"] = text
                elif kind == "scan":
                    self.items, self.db, presets = val
                    if presets and not self.preset["values"]:
                        self.preset["values"] = presets
                        if env.preset() in presets:
                            self.preset.set(env.preset())
                        else:
                            self.say("Next: pick your UBE body preset (top right) - the one you build your UBE body "
                                     "with in BodySlide. The fit check uses it.")
                    self.populate()
                elif kind == "ask":
                    self.ask_new(val)
                elif kind == "fix":
                    self.root.after(300, lambda v=val: self.offer_fix(*v))   # after the busy state clears
                elif kind == "doctor":
                    self.root.after(300, lambda v=val: self.show_doctor(v))
                elif kind == "done":
                    self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_busy(self, b):
        self.busy = b
        self.stop_flag = False
        for w in (self.btn_scan, self.btn_conv, self.btn_qa, self.btn_patch, self.btn_doc):
            w["state"] = "disabled" if b else "normal"
        self.btn_stop["state"] = "normal" if b else "disabled"
        if not b:
            self.status["text"] = "Ready"

    def run(self, fn):
        if self.busy:
            return
        self.set_busy(True)

        def work():
            try:
                fn()
            except Exception as e:
                self.say(f"Error: {e!r}")
            self.q.put(("done", None))
        threading.Thread(target=work, daemon=True).start()

    def do_stop(self):
        self.stop_flag = True
        self.say("Stopping...")

    def rescan(self):
        items = tc.scan()
        db = tc.load_db()
        self.q.put(("scan", (items, db, tc.list_presets())))
        return items

    @staticmethod
    def counts(items):
        c = Counter(i["state"] for i in items)
        return ", ".join(f"{tc.STATES[k]} {v}" for k, v in c.items())

    # ------------------------------------------------------------ list
    def of_kind(self):
        """Items of the type picked in 'Show' (clothing only by default)."""
        k = self.kind.get()
        return [i for i in self.items if k == ALL or tc.KINDS[i["kind"]] == k]

    def visible(self):
        text = self.text.get().lower()
        st = self.state.get()
        pool = tc.left_out(self.items) if st == LEFT_OUT else tc.outdated(self.items) if st == OUTDATED else self.of_kind()
        return [i for i in pool
                if (st in (ALL, LEFT_OUT, OUTDATED) or tc.STATES[i["state"]] == st)
                and (text in i["base"].lower() or text in i["plugin"].lower())]

    def grade_text(self, it):
        qa = self.db.get(it["set"], {}).get("qa")
        if not qa:
            return "", None
        worst = max(qa.get("in0", 0), qa.get("in1", 0))
        text, g = f"{tc.GRADES[qa['grade']]} ({worst} pts inside)", qa["grade"]
        mg = qa.get("motion")
        if mg:                                   # moving: how the piece follows the body's bones
            text += f" · moving {mg}" + (f" ({qa['motion_pct']}% at {qa['motion_bone']})" if mg != "A" else "")
            g = max(g, mg)                       # the worse of the two colours the row
        return text, g

    def populate(self):
        opened = {p for p in self.tree.get_children() if self.tree.item(p, "open")}
        self.tree.delete(*self.tree.get_children())
        vis = self.visible()
        groups = {}
        for it in vis:
            groups.setdefault(it["plugin"], []).append(it)
        for plugin, lst in groups.items():
            pid = "p:" + plugin
            n = sum(1 for i in lst if i["base"].lower() in self.checked)
            mark = "☑" if n == len(lst) else ("◪" if n else "☐")
            self.tree.insert("", "end", iid=pid, text=f"  {plugin}   ({len(lst)})", values=(mark, "", "", ""),
                             open=pid in opened or len(groups) <= 3, tags=("grp",))
            for k, it in enumerate(lst):
                g, grade = self.grade_text(it)
                tags = tuple(t for t in (grade, "odd" if k % 2 else None) if t)
                self.tree.insert(pid, "end", iid=it["base"].lower(), text=it["base"], tags=tags,
                                 values=("☑" if it["base"].lower() in self.checked else "☐", tc.STATES[it["state"]], g,
                                         ", ".join(map(str, it["slots"]))))
        kind = self.of_kind()
        c = Counter(i["state"] for i in kind)
        for key, lab in self.chips.items():
            lab["text"] = f"{c.get(key, 0):,}"
        self.count["text"] = f"shown {len(vis):,}    selected {len(self.checked):,}    of {len(kind):,}"

    def on_click(self, ev):
        row = self.tree.identify_row(ev.y)
        if not row or self.tree.identify_column(ev.x) != "#1":
            return
        if row.startswith("p:"):
            kids = self.tree.get_children(row)
            on = not all(k in self.checked for k in kids)
            (self.checked.update if on else self.checked.difference_update)(kids)
        else:
            self.checked.symmetric_difference_update({row})
        self.populate()
        return "break"

    def check_visible(self, on):
        keys = {i["base"].lower() for i in self.visible()}
        (self.checked.update if on else self.checked.difference_update)(keys)
        self.populate()

    def chosen(self, states):
        return [i for i in self.items if i["base"].lower() in self.checked and i["state"] in states]

    # ------------------------------------------------------------ actions
    def do_scan(self):
        def work():
            if not tc.running("SkyrimSE.exe"):
                self.say("Updating the patches to the meshes BodySlide has built...")
                for line in tc.repoint(False).strip().splitlines()[-2:]:
                    self.say("   " + line)
            self.say("Scanning the mod list...")
            items = self.rescan()
            self.say(f"Found {len(items)} pieces: {self.counts(items)}")
            lo, old = tc.left_out(items), tc.outdated(items)
            if lo:
                outfits = sorted({os.path.dirname(i["base"]) for i in lo})
                self.say(f"Next: {len(lo)} piece(s) of {len(outfits)} outfit(s) you converted are still 3BA and will not "
                         f"fit the UBE body (State: '{LEFT_OUT}').")
            if old:
                self.say(f"Next: {len(old)} piece(s) were converted with an older version of the Tailor "
                         f"(State: '{OUTDATED}').")
            if not self.offered_fix:
                self.offered_fix = True                 # health check once per start, not after every scan
                self._doctor(auto=True)
        self.run(work)

    # ------------------------------------------------------------ health check
    def _doctor(self, auto=False):
        import doctor
        found = doctor.check(log=self.say)
        if found and (not auto or any(f.level in ("fix", "you") for f in found)):
            self.q.put(("doctor", found))
        elif not auto:
            self.say("Health check: all good, nothing to repair.")

    def do_doctor(self):
        self.run(lambda: self._doctor(auto=False))

    def show_doctor(self, found):
        win = tk.Toplevel(self.root, bg=BG, padx=16, pady=12)
        win.title("Health check")
        win.transient(self.root)
        ttk.Label(win, text="Health check", style="Title.TLabel").pack(anchor="w")
        ttk.Label(win, style="Sub.TLabel", text="What the Tailor found, and what it can repair by itself.").pack(
            anchor="w", pady=(0, 8))
        colour = {"fix": GOLD, "you": ACCENT2, "info": MUTED}
        label = {"fix": "Can repair", "you": "Your step", "info": "Good to know"}
        for f in found:
            row = tk.Frame(win, bg=BG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label[f.level], bg=BG, fg=colour[f.level], font=FONT_B, width=12, anchor="w").pack(
                side="left", anchor="n")
            tk.Label(row, text=f.title, bg=BG, fg=FG, font=FONT, wraplength=640, justify="left", anchor="w").pack(
                side="left", fill="x")
        btns = ttk.Frame(win)
        btns.pack(anchor="e", pady=(12, 0))
        fixable = [f for f in found if f.level == "fix"]

        def go():
            win.destroy()
            if tc.running("SkyrimSE.exe"):
                messagebox.showwarning("UBE Tailor", "The game is running. Close it first.")
                return
            import doctor

            def work():
                doctor.fix(found, self.preset.get(), self.workers.get(), log=self.say, stop=lambda: self.stop_flag)
                self.rescan()
            self.run(work)
        if fixable:
            ttk.Button(btns, text=f"Fix all ({len(fixable)})", command=go, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="left", padx=4)

    def offer_fix(self, lo, old):
        parts = []
        if lo:
            parts.append(f"{len(lo)} piece(s) left out of outfits you converted (they would not fit the UBE body)")
        if old:
            parts.append(f"{len(old)} piece(s) converted with an older version of the Tailor")
        if messagebox.askyesno("UBE Tailor", "The Tailor found:\n\n- " + "\n- ".join(parts) +
                               "\n\nConvert them now? Head pieces are skipped on their own. "
                               "Afterwards run Batch Build in BodySlide."):
            self.convert_items(lo + old, self.preset.get())

    def _qa(self, sets, preset):
        t0 = time.time()
        grades = Counter()

        def on(i, total, name, res, err):
            if err:
                self.say(f"   failed: could not check {name[11:]}: {err}")
            else:
                grades[res["grade"]] += 1
            self.q.put(("prog", (i, total, f"Checking fit {i}/{total}")))
        tc.qa(sets, preset, self.workers.get(), on, lambda: self.stop_flag)
        self.say(f"Fit on {preset}: " + ", ".join(f"{tc.GRADES[g]} {n}" for g, n in sorted(grades.items()))
                 + f"  ({time.time() - t0:.0f} s)")

    def do_convert(self):
        sel = self.chosen(("pending", "built", "done") if self.redo.get() else ("pending",))
        if not sel:
            messagebox.showinfo("UBE Tailor", f"Tick some pieces with state '{tc.STATES['pending']}' first, "
                                              "or enable 'Re-convert finished ones'.")
            return
        if tc.running("SkyrimSE.exe"):
            messagebox.showwarning("UBE Tailor", "The game is running. Close it first.")
            return
        self.convert_items(sel, self.preset.get())

    def convert_items(self, sel, preset):
        if tc.running("SkyrimSE.exe"):
            messagebox.showwarning("UBE Tailor", "The game is running. Close it first.")
            return
        mates = tc.outfit_mates(sel, self.items)     # never leave half an outfit in 3BA
        sel = sel + mates

        def work():
            t0 = time.time()
            if mates:
                self.say(f"Also converting {len(mates)} more piece(s) of the same outfits, so each outfit is complete.")
            self.say(f"Converting {len(sel)} pieces...")

            def on(i, total, base, name, err, lines):
                if err and err.startswith(("HEAD: ", "OLDRIM: ", "MISSING: ")):
                    self.say(f"   skipped: {base}  ({err.split(': ', 1)[1]})")
                elif err:
                    self.say(f"   failed: {base}  {err}")
                elif name is None:
                    self.say("   " + base)
                self.q.put(("prog", (i, total, f"Converting {i}/{total}   {(time.time() - t0) / max(i, 1):.1f} s per piece")))
            made, failed = tc.convert([i["base"] for i in sel], self.workers.get(), on, lambda: self.stop_flag)
            self.say(f"Converted {len(made)}, failed {len(failed)}  ({time.time() - t0:.0f} s)")
            if made and preset and not self.stop_flag:
                self._qa(made, preset)
            if made and not self.stop_flag:
                self.say(tc.repoint(False).strip().splitlines()[-1])
                self.say("Next: open BodySlide from MO2 -> group 'UBE Auto Conversions' -> pick your preset -> Batch Build."
                         " Then press Scan here: the patch switches each piece to its UBE mesh once it is built.")
            self.rescan()
        self.run(work)

    def do_qa(self):
        sel = self.chosen(("built", "done"))
        if not sel:
            messagebox.showinfo("UBE Tailor", f"Tick some converted pieces first (set State above to '{tc.STATES['done']}').")
            return
        preset = self.preset.get()
        if not preset:
            messagebox.showinfo("UBE Tailor", "Pick your UBE body preset first (top right).")
            return

        def work():
            self._qa([i["set"] for i in sel], preset)
            self.rescan()
        self.run(work)

    def do_patch(self):
        if tc.running("SkyrimSE.exe"):
            messagebox.showwarning("UBE Tailor", "The game is running. Close it first.")
            return

        def work():
            self.say("Looking for new outfits without a UBE patch...")
            found = tc.find_new_plugins(log=self.say)
            self.say(f"Found {len(found)} mod(s) without a patch.")
            self.q.put(("ask", found))
        self.run(work)

    def ask_new(self, found):
        """Let the user choose which new plugins get a UBE patch, then repoint everything."""
        win = tk.Toplevel(self.root, bg=BG, padx=16, pady=12)
        win.title("New outfits")
        win.transient(self.root)
        ttk.Label(win, text="New outfits", style="Title.TLabel").pack(anchor="w")
        ttk.Label(win, style="Sub.TLabel",
                  text="These mods have outfits with no UBE patch. Tick the ones the tool should patch.").pack(anchor="w", pady=(0, 8))
        picks = {}
        for name, (_p, todo) in sorted(found.items()):
            v = tk.BooleanVar(value=False)
            picks[name] = v
            ttk.Checkbutton(win, text=f"{name}   ({len(todo)} outfits)", variable=v).pack(anchor="w", pady=2)
        if not found:
            ttk.Label(win, text="No new mods.").pack(anchor="w")

        def go():
            chosen = [n for n, v in picks.items() if v.get()]
            win.destroy()

            def work():
                import merged_patch
                if chosen:
                    res = merged_patch.build(add=chosen, log=self.say)
                    for fname, n_mods, n_armo, _n_arma, n_m in res:
                        self.say(f"Patch {fname}: {n_mods} mods, {n_armo} outfits, {n_m} masters")
                    if merged_patch.place_in_load_order([r[0] for r in res]):
                        self.say("   ticked and placed at the end of the load order")
                    else:
                        self.say("   <- MO2 is open: press F5, tick " + ", ".join(r[0] for r in res)
                                 + " and keep it at the bottom of the load order")
                self.say(tc.repoint(False).strip().splitlines()[-1])
                if chosen:
                    self.say("Press Scan to list the new outfits.")
                self.rescan()
            self.run(work)
        ttk.Button(win, text="Apply", command=go, style="Accent.TButton").pack(anchor="e", pady=(12, 0))


# ---------------------------------------------------------------- first start: welcome, modpack, requirements

class WelcomeWindow:
    """First start (and the Guide button): who made the tool, what it does, and the way from start to playing."""

    STEPS = (
        ("Pick your modpack", "Choose your Mod Organizer 2 folder. The Tailor reads everything else from MO2."),
        ("Check what you need", "The Tailor shows what is installed and what is missing (UBE 2.0, its Conversion "
                                "references, CBBE 3BA, BodySlide). 'Download' only opens the official page."),
        ("Pick outfits and convert", "Tick outfits in the list and press 'Convert selected'. Whole outfits are "
                                     "converted together, and each piece gets a fit grade (A is best)."),
        ("Build in BodySlide", "Start BodySlide from MO2, pick the group 'UBE Auto Conversions' and your UBE "
                               "preset, tick 'Build Morphs' and press Batch Build."),
        ("Scan, then play", "Back in the Tailor press Scan: the patch switches every built piece to its UBE "
                            "mesh. Close the Tailor and play."),
    )

    def __init__(self, root, on_done=None, first=False):
        self.root, self.on_done, self.first = root, on_done, first
        self.win = win = tk.Toplevel(root, bg=BG, padx=26, pady=20)
        win.title("Welcome to UBE Tailor")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.close)
        head = tk.Frame(win, bg=BG)
        head.pack(fill="x")
        if getattr(root, "_art", None) is not None:
            tk.Label(head, image=root._art, bg=BG).pack(side="left", padx=(0, 14))
        names = tk.Frame(head, bg=BG)
        names.pack(side="left", anchor="w")
        tk.Label(names, text="UBE Tailor", bg=BG, fg=FG, font=("Segoe UI Semibold", 22)).pack(anchor="w")
        tk.Label(names, text=f"by {env.AUTHOR}   ·   version {env.VERSION}", bg=BG, fg=GOLD,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w")
        tk.Label(win, bg=BG, fg=FG, font=("Segoe UI", 11), wraplength=620, justify="left", anchor="w",
                 text="Your 3BA / CBBE outfits, made for the UBE 2.0 body. The Tailor turns them into real UBE "
                      "BodySlide projects - shape, sliders and bone weights from UBE - and one small plugin, so "
                      "UBE characters can wear them without the body poking through.").pack(fill="x", pady=(14, 10))
        tk.Label(win, text="Where we go, step by step", bg=BG, fg=GOLD, font=FONT_B, anchor="w").pack(fill="x")
        for n, (title, text) in enumerate(self.STEPS, 1):
            row = tk.Frame(win, bg=PANEL, padx=12, pady=8)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=str(n), bg=ACCENT, fg="#041417", font=("Segoe UI Semibold", 12), width=2).pack(
                side="left", anchor="n", padx=(0, 12))
            col = tk.Frame(row, bg=PANEL)
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=title, bg=PANEL, fg=FG, font=FONT_B, anchor="w").pack(fill="x")
            tk.Label(col, text=text, bg=PANEL, fg=MUTED, font=("Segoe UI", 9), wraplength=540, justify="left",
                     anchor="w").pack(fill="x")
        tk.Label(win, bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=620, justify="left", anchor="w",
                 text="Tips: close the game while the Tailor works. 'Health check' finds known problems and fixes "
                      "them. The gold 'Next:' lines in the log always tell you the next step.").pack(fill="x", pady=(10, 0))
        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", pady=(14, 0))
        tk.Label(btns, text=f"Made by {env.AUTHOR}", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(btns, text="Let's go" if first else "Close", command=self.go, style="Accent.TButton").pack(side="right")
        win.transient(root) if not first else None
        win.focus_force()

    def go(self):
        s = env.load_settings()
        s["welcome_seen"] = True
        env.save_settings(s)
        env.S.update(s)
        self.win.destroy()
        if self.on_done:
            self.on_done()

    def close(self):
        self.win.destroy()
        if self.first:                    # closed at the very first start: nothing else to show
            self.root.destroy()

def restart(root):
    """Start a fresh copy of the tool (the modules read the modpack's paths when they load) and close this one."""
    flags = (["-s"] if sys.flags.no_user_site else []) + (["-E"] if sys.flags.ignore_environment else [])
    subprocess.Popen([sys.executable] + flags + sys.argv, cwd=env.TOOL)
    root.destroy()


class SetupWindow:
    """Pick the Mod Organizer 2 modpack and profile. Saved in the settings; the tool then restarts."""

    def __init__(self, root, first=False):
        self.root = root
        self.win = win = tk.Toplevel(root, bg=BG, padx=18, pady=14) if not first else root
        if first:
            root.title("UBE Tailor - pick your modpack")
            root.geometry("760x420")
        else:
            win.title("Modpack")
            win.transient(root)
        ttk.Label(win, text="Your modpack", style="Title.TLabel").pack(anchor="w")
        ttk.Label(win, style="Sub.TLabel", wraplength=700, justify="left",
                  text="Pick the Mod Organizer 2 folder of your Skyrim SE modpack (the folder with ModOrganizer.exe "
                       "or ModOrganizer.ini). Everything else is read from MO2's own settings.").pack(anchor="w")
        row = ttk.Frame(win)
        row.pack(fill="x", pady=(12, 4))
        self.ini = ttk.Combobox(row, width=78)
        guesses = env.guesses()
        self.ini["values"] = [os.path.dirname(g) for g in guesses]
        cur = env.S.get("ini")
        self.ini.set(os.path.dirname(cur) if cur else (self.ini["values"][0] if guesses else ""))
        self.ini.pack(side="left", fill="x", expand=True)
        self.ini.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.ini.bind("<FocusOut>", lambda _e: self.refresh())
        ttk.Button(row, text="Browse...", command=self.browse).pack(side="left", padx=(6, 0))
        row2 = ttk.Frame(win)
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="Profile", style="Sub.TLabel").pack(side="left")
        self.profile = ttk.Combobox(row2, width=30, state="readonly")
        self.profile.pack(side="left", padx=8)
        self.msg = tk.Label(win, text="", bg=BG, fg=MUTED, font=FONT, wraplength=700, justify="left", anchor="w")
        self.msg.pack(fill="x", pady=(8, 4))
        tk.Label(win, bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=700, justify="left", anchor="w",
                 text=f"The Tailor writes its BodySlide projects and its plugin into one mod, '{env.OUTPUT_MOD_NAME}'. "
                      "It adds that mod and its plugin to your profile only while MO2 is closed (or when MO2 "
                      "started the Tailor), and copies each profile file it changes to "
                      + os.path.join(env.HOME, "backups") + " first.").pack(fill="x", pady=(4, 8))
        btns = ttk.Frame(win)
        btns.pack(anchor="e", pady=(6, 0))
        self.ok = ttk.Button(btns, text="Use this modpack", command=self.save, style="Accent.TButton")
        self.ok.pack(side="left", padx=4)
        if not first:
            ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=4)
        self.layout = None
        self.refresh()

    def browse(self):
        d = filedialog.askdirectory(parent=self.win, title="Your Mod Organizer 2 folder")
        if d:
            self.ini.set(os.path.normpath(d))
            self.refresh()

    def refresh(self):
        inis = env.inis_in(self.ini.get()) if self.ini.get() else []
        self.layout = None
        if not inis:
            self.profile["values"] = []
            self.profile.set("")
            self.msg.config(text="No ModOrganizer.ini there.", fg=GRADE["C"])
            self.ok["state"] = "disabled"
            return
        try:
            L = env.layout(inis[0])
        except Exception as e:                       # unreadable ini
            self.msg.config(text=f"Cannot read {inis[0]}: {e}", fg=GRADE["C"])
            self.ok["state"] = "disabled"
            return
        profs = env.profiles(L)
        self.profile["values"] = profs
        want = env.S.get("profile") if env.S.get("ini") == L["ini"] else L["profile_name"]
        self.profile.set(want if want in profs else (profs[0] if profs else ""))
        L = env.layout(inis[0], self.profile.get() or None)
        probs = env.problems(L)
        self.layout = L if not probs else None
        self.msg.config(text=("\n".join(probs) if probs else
                              f"Game: {L['game']}\nMods: {L['mods']}\nProfile: {L['profile_name']}"),
                        fg=GRADE["C"] if probs else FG)
        self.ok["state"] = "normal" if self.layout else "disabled"
        self.profile.bind("<<ComboboxSelected>>", lambda _e: self.refresh_profile(inis[0]))

    def refresh_profile(self, ini):
        env.S["profile"] = self.profile.get()
        env.S["ini"] = env.layout(ini)["ini"]
        self.refresh()

    def save(self):
        if not self.layout:
            return
        s = env.load_settings()
        if s.get("ini") != self.layout["ini"]:
            s.pop("preset", None)                    # presets belong to a modpack
        s.update(ini=self.layout["ini"], profile=self.layout["profile_name"])
        env.save_settings(s)
        restart(self.root)


class RequirementsWindow:
    """One card per thing the Tailor needs: installed or missing, its official page, and Download / Skip.
    'Download' only opens the page in the browser: the Tailor never downloads or installs anything itself."""

    def __init__(self, root, on_done, first=False):
        import requirements
        self.req, self.root, self.on_done, self.skipped = requirements, root, on_done, set()
        self.win = tk.Toplevel(root, bg=BG, padx=18, pady=14)
        self.win.title("UBE Tailor - requirements")
        self.win.geometry("820x640")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        ttk.Label(self.win, text="What UBE Tailor needs", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.win, style="Sub.TLabel", wraplength=760, justify="left",
                  text="The Tailor checked your PC and your modpack. For anything missing, 'Download' opens its "
                       "official page in your browser - you download and install it yourself (in MO2), then press "
                       "'Check again'. The Tailor never downloads anything on its own.").pack(anchor="w")
        self.show_all = tk.BooleanVar(value=first)
        ttk.Checkbutton(self.win, text="Show installed ones too", variable=self.show_all,
                        command=self.fill).pack(anchor="w", pady=(8, 4))
        outer = tk.Frame(self.win, bg=BG)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.cards = tk.Frame(self.canvas, bg=BG)
        self.cards.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.cards, anchor="nw", width=770)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        btns = ttk.Frame(self.win)
        btns.pack(fill="x", pady=(10, 0))
        self.note = ttk.Label(btns, text="", style="Sub.TLabel")
        self.note.pack(side="left")
        self.go = ttk.Button(btns, text="Continue", command=self.done, style="Accent.TButton")
        self.go.pack(side="right", padx=4)
        ttk.Button(btns, text="Check again", command=self.recheck).pack(side="right", padx=4)
        self.items = requirements.check()
        self.fill()

    def recheck(self):
        self.items = self.req.check()
        self.fill()

    def card(self, it):
        box = tk.Frame(self.cards, bg=PANEL, padx=14, pady=10)
        box.pack(fill="x", pady=5, padx=(0, 6))
        top = tk.Frame(box, bg=PANEL)
        top.pack(fill="x")
        if it.ok:
            chip, col = "Installed", GRADE["A"]
        elif it.key in self.skipped:
            chip, col = "Skipped", MUTED
        else:
            chip, col = ("Missing" if it.need == "required" else "Optional - not installed"), \
                (GRADE["C"] if it.need == "required" else GOLD)
        tk.Label(top, text=it.name, bg=PANEL, fg=FG, font=FONT_B, anchor="w").pack(side="left")
        tk.Label(top, text=chip, bg=PANEL, fg=col, font=FONT_B).pack(side="right")
        tk.Label(box, text=it.detail, bg=PANEL, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left",
                 wraplength=720).pack(fill="x", pady=(2, 0))
        if it.ok:
            return
        tk.Label(box, text=it.how, bg=PANEL, fg=FG, font=FONT, anchor="w", justify="left",
                 wraplength=720).pack(fill="x", pady=(6, 4))
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x")
        if it.key == "modpack":
            ttk.Button(row, text="Pick my modpack...", style="Accent.TButton",
                       command=lambda: SetupWindow(self.root)).pack(side="left")
            return
        if it.url:
            ttk.Button(row, text="Download (opens the page)", style="Accent.TButton",
                       command=lambda u=it.url: webbrowser.open(u)).pack(side="left")
            tk.Label(row, text=it.url, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=8)
        if it.key not in self.skipped:
            ttk.Button(row, text="Skip", style="Card.TButton", command=lambda k=it.key: self.skip(k)).pack(side="right")

    def skip(self, key):
        self.skipped.add(key)
        self.fill()

    def fill(self):
        for w in self.cards.winfo_children():
            w.destroy()
        shown = [i for i in self.items if self.show_all.get() or not i.ok]
        for it in shown:
            self.card(it)
        if not shown:
            tk.Label(self.cards, text="Everything is installed.", bg=BG, fg=GRADE["A"], font=FONT_B).pack(anchor="w")
        blocking = [i for i in self.items if not i.ok and i.need == "required"
                    and (i.key in ("python", "pynifly", "modpack") or i.key not in self.skipped)]
        hard = [i for i in blocking if i.key in ("python", "pynifly", "modpack")]
        self.go["state"] = "disabled" if hard else "normal"
        self.go["text"] = "Continue" if not blocking else "Continue anyway"
        self.note["text"] = ("The Tailor cannot start without: " + ", ".join(i.name.split(" (")[0] for i in hard)) \
            if hard else (f"{len(blocking)} required item(s) missing - converting will not work until they are "
                          "installed" if blocking else "")

    def done(self):
        s = env.load_settings()
        s["requirements_seen"] = True
        env.save_settings(s)
        env.S.update(s)
        self.win.destroy()
        if self.on_done:
            self.on_done()

    def close(self):
        self.win.destroy()
        if self.on_done:                  # closed at the first start: nothing to run
            self.root.destroy()


def set_icon(root):
    """Window + taskbar icon. Uses tailor_icon_custom*.png if present, else the built-in needle icon."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UBETailor")   # own taskbar icon, not Python's
    except Exception:
        pass
    custom = os.path.isfile(os.path.join(here, "tailor_icon_custom.png"))
    names = ["tailor_icon_custom.png", "tailor_icon_custom_64.png", "tailor_icon_custom_32.png"] if custom else \
        ["tailor_icon_256.png", "tailor_icon_64.png", "tailor_icon_32.png"]
    try:
        root._icons = [tk.PhotoImage(file=os.path.join(here, n)) for n in names
                       if os.path.isfile(os.path.join(here, n))]
        root.iconphoto(True, *root._icons)
    except Exception:
        pass                                  # a missing or unreadable picture must never stop the tool
    try:                                      # small picture shown in the window's header
        root._art = tk.PhotoImage(file=os.path.join(here, "tailor_icon_custom_96.png" if custom else "tailor_icon_64.png"))
    except Exception:
        root._art = None


def main():
    root = tk.Tk()
    set_icon(root)
    apply_theme(root)

    def start():
        global tc
        try:
            import tailor_core
        except Exception as e:                # e.g. PyNifly / numpy missing after all
            messagebox.showerror("UBE Tailor", f"UBE Tailor cannot start:\n\n{e}")
            root.destroy()
            return
        tc = tailor_core
        root.deiconify()
        App(root)

    def flow():
        if not env.READY:                     # first start (or the modpack moved): pick it
            root.deiconify()
            SetupWindow(root, first=True)
            return
        import requirements
        items = requirements.check()
        if not env.S.get("requirements_seen") or requirements.missing(items):
            root.withdraw()
            RequirementsWindow(root, start, first=not env.S.get("requirements_seen"))
        else:
            start()

    if not env.S.get("welcome_seen"):
        root.withdraw()
        WelcomeWindow(root, flow, first=True)
    else:
        flow()
    root.mainloop()

if __name__ == "__main__":
    main()
