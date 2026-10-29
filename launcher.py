import json
import os
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")
import queue
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

FONT_FAMILY = "Helvetica Neue" if IS_MAC else "Segoe UI"
MONO_FONT = "Menlo" if IS_MAC else "Consolas"


def get_asset_path(relative_path: str) -> str:
    """Resolve an asset path dynamically across dev, onefile, and onedir/bundle environments."""
    # 1. PyInstaller onefile extraction directory
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate_meipass = os.path.join(meipass, relative_path)
        if os.path.exists(candidate_meipass):
            return candidate_meipass

    # 2. Frozen application directory (e.g. Contents/MacOS or dist folder)
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
        # In macOS .app bundle, check Contents/Resources first for data/browsers
        candidate_res = app_dir.parent / "Resources" / relative_path
        if candidate_res.exists():
            return str(candidate_res)
        candidate_app = app_dir / relative_path
        if candidate_app.exists():
            return str(candidate_app)
        return str(candidate_app)

    # 3. Development / source mode
    dev_base = Path(__file__).resolve().parent
    candidate_dev = dev_base / relative_path
    if candidate_dev.exists():
        return str(candidate_dev)

    return str(candidate_dev)


def get_user_data_dir() -> Path:
    """Return an OS-safe writable directory for configuration and crash logs."""
    if IS_MAC:
        path = Path.home() / "Library" / "Application Support" / "Achieve3000"
    elif IS_WIN:
        local_app_data = os.environ.get("LOCALAPPDATA")
        path = Path(local_app_data) / "Achieve3000" if local_app_data else Path.home() / ".achieve3000"
    else:
        path = Path.home() / ".achieve3000"

    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = Path.home() / ".achieve3000"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except OSError:
            import tempfile
            return Path(tempfile.gettempdir())


USER_DATA_DIR = get_user_data_dir()
SETTINGS_FILE = USER_DATA_DIR / "settings.json"
CRASH_LOG_FILE = USER_DATA_DIR / "desktop_crash_log.txt"

# Search locations for bundled or project files
APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
ENV_FILE = Path(get_asset_path(".env"))
AUTOMATION_FILE = Path(get_asset_path("achieve3000_automation.py"))
AUTOMATION_EXE_NAME = "achieve3000_automation.exe" if IS_WIN else "achieve3000_automation"
AUTOMATION_EXE = Path(get_asset_path(AUTOMATION_EXE_NAME))

BG = "#0b1020"
CARD = "#141d31"
CARD_2 = "#0e1729"
TEXT = "#eef4ff"
MUTED = "#9aa9bf"
ACCENT = "#63d2c6"
ACCENT_DARK = "#147d7a"
SUCCESS = "#34d399"
ERROR = "#fb7185"


def log_crash(exc_type, exc_value, exc_traceback):
    """Global crash logger outputting to desktop_crash_log.txt."""
    try:
        with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n")
            f.write(f"CRASH OCCURRED: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Platform: {sys.platform} ({os.name})\n")
            f.write(f"Python: {sys.version}\n")
            f.write(f"Executable: {sys.executable}\n")
            f.write(f"Frozen: {getattr(sys, 'frozen', False)}\n")
            f.write(f"Bundle dir (_MEIPASS): {getattr(sys, '_MEIPASS', 'N/A')}\n")
            f.write(f"App dir: {APP_DIR}\n")
            f.write(f"{'-' * 60}\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            f.flush()
    except Exception:
        pass


sys.excepthook = log_crash


class AutomationLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Achieve3000 Runner")
        self.geometry("820x720")
        self.minsize(720, 600)
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

        self._load_icon()
        self._configure_styles()
        self._build_ui()
        self._load_settings()

        # Save settings on field edits
        for variable in (self.api_key, self.username, self.password, self.headless):
            variable.trace_add("write", self._schedule_save)

        self.after(100, self._drain_output)
        self.protocol("WM_DELETE_WINDOW", self._close)

        # Force initial layout and schedule Darwin/Cocoa expose refresh
        self.update_idletasks()
        if IS_MAC:
            self.after(100, self._darwin_window_refresh)

    def _load_icon(self):
        """Safely load application icon without crashing on macOS."""
        icon_path = get_asset_path("achieve3000.ico")
        if os.path.exists(icon_path):
            try:
                if IS_WIN:
                    self.iconbitmap(icon_path)
            except Exception:
                pass

    def _darwin_window_refresh(self):
        """Fix blank window rendering quirk on macOS Cocoa by triggering an expose event."""
        try:
            self.lift()
            w = self.winfo_width()
            h = self.winfo_height()
            self.geometry(f"{w + 1}x{h}")
            self.update_idletasks()
            self.geometry(f"{w}x{h}")
        except Exception:
            pass

    def _configure_styles(self):
        style = ttk.Style(self)
        available_themes = style.theme_names()
        if "clam" in available_themes:
            style.theme_use("clam")
        elif "default" in available_themes:
            style.theme_use("default")

        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=(FONT_FAMILY, 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT_FAMILY, 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=(FONT_FAMILY, 24, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=(FONT_FAMILY, 10))
        style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT, font=(FONT_FAMILY, 12, "bold"))
        style.configure("Field.TLabel", background=CARD, foreground=MUTED, font=(FONT_FAMILY, 9, "bold"))
        style.configure("TEntry", fieldbackground=CARD_2, foreground=TEXT, insertcolor=TEXT, borderwidth=1, padding=10, relief="flat")
        style.configure("TSpinbox", fieldbackground=CARD_2, foreground=TEXT, arrowsize=14, borderwidth=0, padding=8)
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#082f49",
            font=(FONT_FAMILY, 10, "bold"),
            borderwidth=0,
            padding=(18, 10),
        )
        style.map("Accent.TButton", background=[("active", "#8ce6db"), ("disabled", "#526978")], foreground=[("disabled", "#c5d3df")])
        style.configure(
            "Stop.TButton",
            background="#7f1d1d",
            foreground="#ffe4e6",
            font=(FONT_FAMILY, 10, "bold"),
            borderwidth=0,
            padding=(18, 10),
        )
        style.map("Stop.TButton", background=[("active", "#be123c")])

        # Explicitly configure checkbutton styling to prevent invisible elements on macOS
        style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=(FONT_FAMILY, 9))
        style.map(
            "TCheckbutton",
            background=[("active", CARD), ("focus", CARD)],
            foreground=[("active", TEXT)],
        )

    def _build_ui(self):
        outer = ttk.Frame(self, padding=(30, 26))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Achieve3000", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Lesson automation · Configure your session and follow progress below.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 20))

        card = ttk.Frame(outer, style="Card.TFrame", padding=24)
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
        ttk.Spinbox(card, from_=1, to=9999, textvariable=self.lesson_count, width=12).grid(
            row=4, column=1, sticky="w", pady=(16, 6)
        )
        ttk.Label(card, text="Defaults to 40 and is never saved.", style="Muted.TLabel").grid(
            row=5, column=1, sticky="w", pady=(0, 2)
        )

        ttk.Checkbutton(
            card,
            text="Run browser headless",
            variable=self.headless,
            style="TCheckbutton",
        ).grid(row=6, column=1, sticky="w", pady=(14, 0))
        card.columnconfigure(1, weight=1)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(18, 12))
        self.start_button = ttk.Button(
            controls,
            text="▶  Start automation",
            style="Accent.TButton",
            command=self._start,
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            controls,
            text="■  Stop",
            style="Stop.TButton",
            command=self._stop,
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=(10, 0))
        ttk.Label(controls, textvariable=self.status, style="Muted.TLabel").pack(
            side="right", pady=10
        )

        output_card = ttk.Frame(outer, style="Card.TFrame", padding=16)
        output_card.pack(fill="both", expand=True)
        ttk.Label(output_card, text="Live output", style="CardTitle.TLabel").pack(
            anchor="w", padx=6, pady=(0, 8)
        )
        text_frame = ttk.Frame(output_card, style="Card.TFrame")
        text_frame.pack(fill="both", expand=True)
        self.output = tk.Text(
            text_frame,
            bg="#0b1220",
            fg="#cbd5e1",
            insertbackground=TEXT,
            relief="flat",
            borderwidth=0,
            wrap="word",
            font=(MONO_FONT, 9),
            padx=12,
            pady=10,
            state="disabled",
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
        if ENV_FILE.exists():
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
        if SETTINGS_FILE.exists():
            try:
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
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
            temp_file = SETTINGS_FILE.with_suffix(".tmp")
            temp_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
            temp_file.replace(SETTINGS_FILE)
        except OSError as exc:
            # Fall back to logging rather than a blocking error dialog
            try:
                with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"Settings save warning: {exc}\n")
            except Exception:
                pass

    def _schedule_save(self, *_):
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(500, self._save_settings)

    def _start(self):
        """Handle Start button click by launching automation asynchronously."""
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

        self._clear_output()
        self._write_output(f"Preparing {lessons} lesson iteration(s)...\n")
        self.status.set("Starting...")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        # Recommendation 2: Decouple automation launch & execution into a non-blocking thread
        launcher_thread = threading.Thread(
            target=self._launch_process_worker,
            args=(lessons,),
            daemon=True,
        )
        launcher_thread.start()

    def _resolve_browser_dir(self) -> str:
        """Find bundled or local Playwright browser directory."""
        candidates = [
            get_asset_path("playwright-browsers"),
            str(APP_DIR / "playwright-browsers"),
            str(APP_DIR.parent / "Resources" / "playwright-browsers"),
            str(APP_DIR.parent / "SharedSupport" / "playwright-browsers"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return ""

    def _launch_process_worker(self, lessons: int):
        """Background worker thread: resolves paths, prepares environment, and spawns process."""
        env = os.environ.copy()
        env.update({
            "GROQ_API_KEY": self.api_key.get().strip(),
            "ACHIEVE3000_USERNAME": self.username.get().strip(),
            "ACHIEVE3000_PASSWORD": self.password.get(),
            "ITERATIONS": str(lessons),
            "HEADLESS": "true" if self.headless.get() else "false",
        })

        # Inject bundled Playwright browser directory if present
        browser_dir = self._resolve_browser_dir()
        if browser_dir:
            env["PLAYWRIGHT_BROWSERS_PATH"] = browser_dir
            self.output_queue.put(f"[Launcher] Using Playwright browsers: {browser_dir}\n")

        # Determine target executable/script
        command = []
        is_frozen = getattr(sys, "frozen", False)
        exe_path = AUTOMATION_EXE

        if is_frozen and exe_path.exists():
            if not IS_WIN:
                try:
                    os.chmod(str(exe_path), 0o755)
                except OSError:
                    pass
            command = [str(exe_path)]
        elif AUTOMATION_FILE.exists():
            command = [sys.executable, str(AUTOMATION_FILE)]
        elif exe_path.exists():
            command = [str(exe_path)]
        else:
            self.output_queue.put(
                f"[Error] Neither {AUTOMATION_EXE.name} nor {AUTOMATION_FILE.name} could be found.\n"
            )
            self.after(0, lambda: self._on_process_launch_failed("Automation script not found."))
            return

        try:
            self.output_queue.put(f"[Launcher] Spawning process: {' '.join(command)}\n")
            self.process = subprocess.Popen(
                command,
                cwd=str(APP_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=(os.name != "nt"),
            )
            self.after(0, lambda: self.status.set("Running"))
        except Exception as exc:
            log_crash(*sys.exc_info())
            self.output_queue.put(f"[Error] Subprocess launch failed: {exc}\n")
            self.after(0, lambda: self._on_process_launch_failed(str(exc)))
            return

        # Start continuous reading thread for process output
        self.reader_thread = threading.Thread(target=self._read_process, daemon=True)
        self.reader_thread.start()

    def _on_process_launch_failed(self, error_message: str):
        self.status.set("Launch failed")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        messagebox.showerror("Could not start automation", error_message)

    def _read_process(self):
        if not self.process or not self.process.stdout:
            return
        try:
            for line in self.process.stdout:
                self.output_queue.put(line)
        except Exception as exc:
            self.output_queue.put(f"[Reader Error] {exc}\n")
        finally:
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
            threading.Thread(target=self._terminate_process_tree, daemon=True).start()

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


def main():
    if IS_MAC:
        try:
            import mac_launcher
            mac_launcher.main()
            return
        except Exception:
            log_crash(*sys.exc_info())

    try:
        app = AutomationLauncher()
        app.mainloop()
    except Exception:
        log_crash(*sys.exc_info())
        try:
            messagebox.showerror(
                "Achieve3000 Launcher Error",
                f"An unhandled error occurred during startup.\nA crash log was saved to:\n{CRASH_LOG_FILE}",
            )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
