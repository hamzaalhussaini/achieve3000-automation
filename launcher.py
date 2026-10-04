import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
SETTINGS_FILE = APP_DIR / ".achieve3000_settings.json"
ENV_FILE = APP_DIR / ".env"
AUTOMATION_FILE = APP_DIR / "achieve3000_automation.py"
AUTOMATION_EXE = APP_DIR / ("achieve3000_automation.exe" if os.name == "nt" else "achieve3000_automation")

BG = "#0f172a"
CARD = "#172033"
CARD_2 = "#1e293b"
TEXT = "#e5edf7"
MUTED = "#94a3b8"
ACCENT = "#38bdf8"
ACCENT_DARK = "#075985"
SUCCESS = "#34d399"
ERROR = "#fb7185"


class AutomationLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Achieve3000 Runner")
        self.geometry("780x680")
        self.minsize(700, 580)
        self.configure(bg=BG)

        self.output_queue = queue.Queue()
        self.process = None
        self.reader_thread = None
        self._save_job = None

        self.api_key = tk.StringVar()
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.lesson_count = tk.StringVar(value="40")
        self.headless = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready to run")

        self._configure_styles()
        self._build_ui()
        self._load_settings()
        self._save_settings()
        for variable in (self.api_key, self.username, self.password, self.headless):
            variable.trace_add("write", self._schedule_save)
        self.after(100, self._drain_output)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT,
                        font=("Segoe UI", 24, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED,
                        font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT,
                        font=("Segoe UI", 12, "bold"))
        style.configure("Field.TLabel", background=CARD, foreground=MUTED,
                        font=("Segoe UI", 9, "bold"))
        style.configure("TEntry", fieldbackground=CARD_2, foreground=TEXT,
                        insertcolor=TEXT, borderwidth=0, padding=9)
        style.configure("TSpinbox", fieldbackground=CARD_2, foreground=TEXT,
                        arrowsize=14, borderwidth=0, padding=8)
        style.configure("Accent.TButton", background=ACCENT, foreground="#082f49",
                        font=("Segoe UI", 10, "bold"), borderwidth=0, padding=(18, 10))
        style.map("Accent.TButton", background=[("active", "#7dd3fc")])
        style.configure("Stop.TButton", background="#7f1d1d", foreground="#ffe4e6",
                        font=("Segoe UI", 10, "bold"), borderwidth=0, padding=(18, 10))
        style.map("Stop.TButton", background=[("active", "#be123c")])

    def _build_ui(self):
        outer = ttk.Frame(self, padding=(28, 24))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Achieve3000 Runner", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Configure your session, then launch the Playwright workflow.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 20))

        card = ttk.Frame(outer, style="Card.TFrame", padding=22)
        card.pack(fill="x")
        ttk.Label(card, text="Connection", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 18)
        )

        self._field(card, 1, "Groq API key", self.api_key, secret=True)
        self._field(card, 2, "Achieve3000 username", self.username)
        self._field(card, 3, "Achieve3000 password", self.password, secret=True)

        ttk.Label(card, text="Lessons this run", style="Field.TLabel").grid(
            row=4, column=0, sticky="w", pady=(16, 6)
        )
        ttk.Spinbox(card, from_=1, to=9999, textvariable=self.lesson_count,
                    width=12).grid(row=4, column=1, sticky="w", pady=(16, 6))
        ttk.Label(card, text="Defaults to 40 and is never saved.", style="Muted.TLabel").grid(
            row=5, column=1, sticky="w", pady=(0, 2)
        )

        ttk.Checkbutton(
            card, text="Run browser headless", variable=self.headless,
            style="TCheckbutton"
        ).grid(row=6, column=1, sticky="w", pady=(14, 0))
        card.columnconfigure(1, weight=1)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(18, 12))
        self.start_button = ttk.Button(
            controls, text="▶  Start automation", style="Accent.TButton",
            command=self._start
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            controls, text="■  Stop", style="Stop.TButton",
            command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(10, 0))
        ttk.Label(controls, textvariable=self.status, style="Muted.TLabel").pack(
            side="right", pady=10
        )

        output_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        output_card.pack(fill="both", expand=True)
        ttk.Label(output_card, text="Live output", style="CardTitle.TLabel").pack(
            anchor="w", padx=6, pady=(0, 8)
        )
        text_frame = ttk.Frame(output_card, style="Card.TFrame")
        text_frame.pack(fill="both", expand=True)
        self.output = tk.Text(
            text_frame, bg="#0b1220", fg="#cbd5e1", insertbackground=TEXT,
            relief="flat", borderwidth=0, wrap="word", font=("Consolas", 9),
            padx=12, pady=10, state="disabled"
        )
        scrollbar = ttk.Scrollbar(text_frame, command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _field(self, parent, row, label, variable, secret=False):
        ttk.Label(parent, text=label, style="Field.TLabel").grid(
            row=row, column=0, sticky="w", pady=6
        )
        entry = ttk.Entry(parent, textvariable=variable, show="•" if secret else "")
        entry.grid(row=row, column=1, sticky="ew", padx=(24, 0), pady=4)

    def _load_settings(self):
        env_values = {}
        try:
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env_values[key.strip()] = value.strip().strip('"').strip("'")
        except OSError:
            pass

        settings = {}
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        self.api_key.set(settings.get("groq_api_key") or env_values.get("GROQ_API_KEY", ""))
        self.username.set(settings.get("username") or env_values.get("ACHIEVE3000_USERNAME", ""))
        self.password.set(settings.get("password") or env_values.get("ACHIEVE3000_PASSWORD", ""))
        if "headless" in settings:
            self.headless.set(bool(settings["headless"]))

    def _save_settings(self):
        settings = {
            "groq_api_key": self.api_key.get().strip(),
            "username": self.username.get().strip(),
            "password": self.password.get(),
            "headless": self.headless.get(),
        }
        try:
            temporary_file = SETTINGS_FILE.with_suffix(".tmp")
            temporary_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
            temporary_file.replace(SETTINGS_FILE)
        except OSError as exc:
            messagebox.showerror("Could not save settings", str(exc))

    def _schedule_save(self, *_):
        """Persist field changes shortly after typing stops."""
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(500, self._save_settings)

    def _start(self):
        if self.process and self.process.poll() is None:
            return
        if not self.api_key.get().strip():
            messagebox.showwarning("Missing API key", "Enter your Groq API key first.")
            return
        if not self.username.get().strip() or not self.password.get():
            messagebox.showwarning("Missing login", "Enter your Achieve3000 username and password.")
            return
        try:
            lessons = int(self.lesson_count.get())
            if lessons < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid lesson count", "Lessons must be a positive whole number.")
            return

        self._save_settings()
        env = os.environ.copy()
        env.update({
            "GROQ_API_KEY": self.api_key.get().strip(),
            "ACHIEVE3000_USERNAME": self.username.get().strip(),
            "ACHIEVE3000_PASSWORD": self.password.get(),
            "ITERATIONS": str(lessons),
            "HEADLESS": "true" if self.headless.get() else "false",
        })

        try:
            if getattr(sys, "frozen", False) and AUTOMATION_EXE.exists():
                command = [str(AUTOMATION_EXE)]
            else:
                command = [sys.executable, str(AUTOMATION_FILE)]
            self.process = subprocess.Popen(
                command,
                cwd=str(APP_DIR), env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=(os.name != "nt"),
            )
        except OSError as exc:
            messagebox.showerror("Could not start automation", str(exc))
            return

        self._clear_output()
        self._write_output(f"Starting {lessons} lesson iteration(s)...\n")
        self.status.set("Running")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.reader_thread = threading.Thread(target=self._read_process, daemon=True)
        self.reader_thread.start()

    def _read_process(self):
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self.output_queue.put(line)
        self.output_queue.put(None)

    def _drain_output(self):
        finished = False
        while True:
            try:
                line = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if line is None:
                finished = True
            else:
                self._write_output(line)
        if finished and self.process:
            code = self.process.poll()
            if code is not None:
                self.status.set("Finished" if code == 0 else f"Stopped with code {code}")
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
        self.after(100, self._drain_output)

    def _write_output(self, value):
        self.output.configure(state="normal")
        self.output.insert("end", value)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _clear_output(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def _stop(self):
        if self.process and self.process.poll() is None:
            self.status.set("Stopping...")
            self._terminate_process_tree()

    def _terminate_process_tree(self):
        if not self.process or self.process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                os.killpg(self.process.pid, 15)
                self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self.process.kill()
            except OSError:
                pass

    def _close(self):
        self._save_settings()
        self._terminate_process_tree()
        self.destroy()


if __name__ == "__main__":
    AutomationLauncher().mainloop()
