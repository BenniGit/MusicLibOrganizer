"""Mac-Oberfläche (Tkinter) für die Kommandozeilen-Funktionen.

Jede Aktion ruft dieselbe Funktion wie `musiclib …` im Terminal auf; die Ausgabe
landet im Protokollfeld. Geschrieben wird nur nach ausdrücklicher Bestätigung.
"""

from __future__ import annotations

import contextlib
import io
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, credentials
from .cli import iter_files, main as cli_main

APP_NAME = "MusicLib Organizer"
DEFAULT_LIBRARY = Path.home() / "Nextcloud" / "Music" / "LibOrganized"
DEFAULT_BACKUP = Path.home() / "MusicLib Backup"

# Retro-Farben aus dem Icon
CREAM, BROWN, ORANGE, TEAL = "#F7E9CC", "#5B3A29", "#E8772E", "#2F7F7A"


class _QueueWriter(io.TextIOBase):
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> int:
        # Hinweise der Kommandozeile in Fenster-Sprache übersetzen
        self.q.put(s.replace("Zum Ausführen --apply angeben.", "Zum Ausführen „Tags zurücksetzen …“ wählen."))
        return len(s)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.busy = False
        root.title(APP_NAME)
        root.geometry("820x600")
        root.minsize(640, 460)
        root.configure(bg=CREAM)

        style = ttk.Style(root)
        style.configure("TFrame", background=CREAM)
        style.configure("TLabel", background=CREAM, foreground=BROWN)
        style.configure("Title.TLabel", font=("Helvetica", 20, "bold"), foreground=BROWN)

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(frame, text="Zugangsdaten …", command=self.edit_credentials).grid(row=0, column=2, sticky="e")
        ttk.Label(frame, text="Tags prüfen, komplett zurücksetzen und wiederherstellen.").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self.library = tk.StringVar(value=str(DEFAULT_LIBRARY) if DEFAULT_LIBRARY.exists() else "")
        self.backup = tk.StringVar(value=str(DEFAULT_BACKUP))
        self._path_row(frame, 2, "Musikordner:", self.library)
        self._path_row(frame, 3, "Sicherung nach:", self.backup)

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="w", pady=12)
        self.action_buttons = [
            ttk.Button(buttons, text="Tags anzeigen", command=self.show),
            ttk.Button(buttons, text="Reset-Vorschau", command=self.preview),
            ttk.Button(buttons, text="Tags zurücksetzen …", command=self.apply_reset),
            ttk.Button(buttons, text="Wiederherstellen …", command=self.restore),
            ttk.Button(buttons, text="Quellen prüfen", command=self.check_sources),
        ]
        for i, b in enumerate(self.action_buttons):
            b.grid(row=0, column=i, padx=(0, 8))

        self.log = tk.Text(frame, wrap="word", bg="#FFF8EA", fg=BROWN, relief="flat",
                           font=("Menlo", 12), padx=10, pady=10, highlightthickness=1,
                           highlightbackground="#D9BF8F")
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(5, weight=1)
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        scroll.grid(row=5, column=3, sticky="ns")
        self.log["yscrollcommand"] = scroll.set

        self.status = tk.StringVar(value=f"Version {__version__}")
        ttk.Label(frame, textvariable=self.status).grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.write("Ordner wählen und mit „Reset-Vorschau“ starten – die Vorschau ändert nichts.\n")
        self.root.after(100, self._drain_log)

    # ---- Aufbau -------------------------------------------------------------
    def _path_row(self, frame, row, label, var):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(frame, text="Wählen …", command=lambda: self._choose(var)).grid(
            row=row, column=2, padx=(8, 0), pady=3)

    def _choose(self, var):
        start = var.get() if var.get() and Path(var.get()).exists() else str(Path.home())
        if chosen := filedialog.askdirectory(initialdir=start, mustexist=False):
            var.set(chosen)

    # ---- Protokoll ----------------------------------------------------------
    def write(self, text: str):
        self.log.insert("end", text)
        self.log.see("end")

    def _drain_log(self):
        try:
            while True:
                self.write(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    def _run(self, title: str, argv: list[str]):
        """Führt einen CLI-Befehl im Hintergrund aus und leitet die Ausgabe ins Protokoll."""
        if self.busy:
            return
        self.busy = True
        for b in self.action_buttons:
            b.state(["disabled"])
        self.status.set(f"{title} läuft …")
        self.write(f"\n── {title} ──\n")

        def work():
            writer = _QueueWriter(self.log_queue)
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    code = cli_main(argv)
            except SystemExit as e:
                code = e.code
            except Exception as e:  # nichts darf die Oberfläche abstürzen lassen
                self.log_queue.put(f"Unerwarteter Fehler: {e}\n")
                code = 1
            self.root.after(0, self._done, title, code)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, title, code):
        self.busy = False
        for b in self.action_buttons:
            b.state(["!disabled"])
        self.status.set(f"{title}: {'fertig' if code == 0 else 'mit Fehlern beendet'}")

    # ---- Aktionen -----------------------------------------------------------
    def _library(self) -> str | None:
        path = self.library.get().strip()
        if not path or not Path(path).exists():
            messagebox.showwarning(APP_NAME, "Bitte zuerst einen vorhandenen Musikordner wählen.")
            return None
        return path

    def _backup(self) -> str | None:
        backup = self.backup.get().strip()
        if not backup:
            messagebox.showwarning(APP_NAME, "Bitte einen Ordner für die Sicherung wählen.")
            return None
        lib = Path(self.library.get()).expanduser().resolve()
        bak = Path(backup).expanduser().resolve()
        if bak == lib or lib in bak.parents:
            messagebox.showwarning(APP_NAME, "Die Sicherung darf nicht im Musikordner liegen.")
            return None
        if "nextcloud" in str(bak).lower() and not messagebox.askyesno(
                APP_NAME, "Die Sicherung liegt in Nextcloud und würde mit synchronisiert. Trotzdem?"):
            return None
        return str(bak)

    def show(self):
        if lib := self._library():
            self._run("Tags anzeigen", ["show", lib])

    def preview(self):
        if lib := self._library():
            self._run("Reset-Vorschau", ["reset", lib])

    def apply_reset(self):
        lib, bak = self._library(), None
        if lib:
            bak = self._backup()
        if not (lib and bak):
            return
        count = sum(1 for _ in iter_files([Path(lib)]))
        if not messagebox.askokcancel(
                APP_NAME,
                f"{count} Dateien in\n{lib}\n\nwerden zuerst nach\n{bak}\ngesichert, danach werden "
                "ALLE Tags entfernt (Titel, Interpret, Cover, Kommentare …).\n\n"
                "Die Dateien sind danach leer, bis sie neu getaggt werden. Fortfahren?",
                icon="warning"):
            return
        self._run("Tags zurücksetzen", ["reset", lib, "--backup-dir", bak, "--apply"])

    def restore(self):
        lib = self._library()
        if not lib:
            return
        bak = self.backup.get().strip()
        if not messagebox.askokcancel(
                APP_NAME, f"Alle Dateien in\n{lib}\nmit ihrer Sicherung aus\n{bak}\nüberschreiben?"):
            return
        self._run("Wiederherstellen", ["restore", lib, "--backup-dir", bak])

    def check_sources(self):
        self._run("Quellen prüfen", ["check-sources"])

    def edit_credentials(self):
        CredentialsDialog(self.root)


class CredentialsDialog(tk.Toplevel):
    LABELS = {
        "DISCOGS_TOKEN": "Discogs-Token",
        "BEATPORT_USERNAME": "Beatport-Benutzer",
        "BEATPORT_PASSWORD": "Beatport-Passwort",
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Zugangsdaten")
        self.configure(bg=CREAM)
        self.transient(parent)
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        if not credentials.keychain_available():
            ttk.Label(frame, text="Kein Schlüsselbund verfügbar – Speichern nicht möglich.").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(frame, text="Wird im macOS-Schlüsselbund gespeichert (Dienst „musiclib“).").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.vars = {}
        for i, (name, label) in enumerate(self.LABELS.items(), start=2):
            ttk.Label(frame, text=label + ":").grid(row=i, column=0, sticky="w", padx=(0, 8), pady=3)
            var = tk.StringVar(value=credentials.get(name) or "")
            ttk.Entry(frame, textvariable=var, width=40,
                      show="•" if name != "BEATPORT_USERNAME" else "").grid(row=i, column=1, pady=3)
            self.vars[name] = var
        row = ttk.Frame(frame)
        row.grid(row=10, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(row, text="Abbrechen", command=self.destroy).pack(side="right")
        ttk.Button(row, text="Speichern", command=self.save).pack(side="right", padx=8)
        self.grab_set()

    def save(self):
        try:
            for name, var in self.vars.items():
                credentials.set(name, var.get().strip())
        except Exception as e:
            messagebox.showerror("Zugangsdaten", f"Speichern fehlgeschlagen: {e}", parent=self)
            return
        self.destroy()


def selftest() -> int:
    """Für den Build: Fenster aufbauen und sofort schließen."""
    root = tk.Tk()
    root.withdraw()
    App(root)
    root.update()
    root.destroy()
    keychain = credentials.keychain_available()
    print(f"{APP_NAME} {__version__}: Fenster ok, Schlüsselbund {'ok' if keychain else 'NICHT verfügbar'}")
    # Auf dem Mac muss der Schlüsselbund im fertigen Bundle funktionieren
    return 0 if keychain or sys.platform != "darwin" else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
