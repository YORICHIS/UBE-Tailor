// UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
// UBE Tailor launcher: starts tailor_gui.py (in this exe's folder) and waits for it to close.
// Uses the Python that ships with the tool (python\pythonw.exe next to this exe) first, then an installed Python.
// Build: csc /target:winexe /win32icon:tailor.ico /out:"UBE Tailor.exe" /r:System.Windows.Forms.dll launcher.cs
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static int Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(dir, "tailor_gui.py");
        if (!File.Exists(script))
        {
            MessageBox.Show("tailor_gui.py was not found next to this program. Unpack the whole UBE Tailor folder.",
                            "UBE Tailor");
            return 1;
        }
        var candidates = new List<string>();
        string bundled = Path.Combine(dir, "python", "pythonw.exe");
        if (File.Exists(bundled)) candidates.Add(bundled);
        string pyRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                     "Programs", "Python");
        if (Directory.Exists(pyRoot))
            foreach (string d in Directory.GetDirectories(pyRoot, "Python3*"))
                candidates.Add(Path.Combine(d, "pythonw.exe"));
        candidates.Add("pythonw.exe");
        foreach (string exe in candidates)
        {
            try
            {
                // -s: ignore the user's own Python packages, -E: ignore PYTHON* settings (the tool runs the same everywhere)
                var psi = new ProcessStartInfo(exe, "-s -E \"" + script + "\"") { WorkingDirectory = dir, UseShellExecute = false };
                using (Process p = Process.Start(psi)) { p.WaitForExit(); return p.ExitCode; }
            }
            catch (System.ComponentModel.Win32Exception) { }
        }
        MessageBox.Show("Python was not found. Use the full UBE Tailor download (it has Python inside), or install " +
                        "Python 3 from python.org.", "UBE Tailor");
        return 1;
    }
}
