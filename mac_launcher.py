#!/usr/bin/env python3
"""
Achieve3000 Modern Mac Launcher
A robust, native-feeling launcher designed specifically for macOS.
Features auto-saving credentials, live metrics, terminal log colorization,
sound/desktop notifications, and seamless execution in both frozen bundles and development mode.
"""

import os
import sys
import json
import time
import queue
import signal
import socket
import logging
import threading
import subprocess
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Base paths
ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"
ICON_PNG = ROOT_DIR / "achieve3000.png"


def get_settings_file() -> Path:
    """Return an OS-safe writable path for persisting user credentials."""
    # 1. Primary standard macOS Application Support directory
    app_support = Path.home() / "Library" / "Application Support" / "Achieve3000"
    try:
        app_support.mkdir(parents=True, exist_ok=True)
        return app_support / "settings.json"
    except Exception:
        pass

    # 2. Secondary user home directory fallback
    home_dir = Path.home() / ".achieve3000"
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        return home_dir / "settings.json"
    except Exception:
        pass

    return Path.home() / ".achieve3000_settings.json"


SETTINGS_FILE = get_settings_file()


def send_mac_notification(title: str, message: str):
    """Trigger a native macOS desktop notification."""
    if sys.platform == "darwin":
        try:
            escaped_msg = message.replace('"', '\\"')
            escaped_title = title.replace('"', '\\"')
            subprocess.run([
                "osascript", "-e",
                f'display notification "{escaped_msg}" with title "{escaped_title}"'
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass


class AutomationManager:
    def __init__(self):
        self.process = None
        self.lock = threading.RLock()
        self.log_queue = queue.Queue()
        self.log_history = []
        self.status = "Ready to run"
        self.start_time = None
        self.questions_answered = 0

    def load_settings(self):
        data = {
            "groq_api_key": "",
            "username": "",
            "password": "",
            "lessons": 40,
            "headless": False
        }

        # 1. Check primary persistent settings.json
        target = get_settings_file()
        if target.exists():
            try:
                saved = json.loads(target.read_text(encoding="utf-8"))
                for k in data:
                    if k in saved and saved[k] is not None:
                        data[k] = saved[k]
            except Exception:
                pass

        # 2. Check alternative user locations if fields are still empty
        alt_locations = [
            Path.home() / ".achieve3000" / "settings.json",
            Path.home() / ".achieve3000_settings.json",
            ROOT_DIR / ".achieve3000_settings.json",
        ]
        for alt in alt_locations:
            if not data["username"] and alt.exists():
                try:
                    saved = json.loads(alt.read_text(encoding="utf-8"))
                    for k in data:
                        if k in saved and saved[k] is not None and not data[k]:
                            data[k] = saved[k]
                except Exception:
                    pass

        # 3. Fallback to .env file if available
        if not data["groq_api_key"] and not data["username"] and ENV_FILE.exists():
            try:
                for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k == "GROQ_API_KEY" and not data["groq_api_key"]:
                        data["groq_api_key"] = v
                    elif k == "ACHIEVE3000_USERNAME" and not data["username"]:
                        data["username"] = v
                    elif k == "ACHIEVE3000_PASSWORD" and not data["password"]:
                        data["password"] = v
                    elif k == "ITERATIONS" and v.isdigit() and data["lessons"] == 40:
                        data["lessons"] = int(v)
                    elif k == "HEADLESS" and not data["headless"]:
                        data["headless"] = v.lower() in ("true", "1", "yes")
            except Exception:
                pass

        return data

    def save_settings(self, data):
        try:
            target = get_settings_file()
            target.parent.mkdir(parents=True, exist_ok=True)
            to_save = {
                "groq_api_key": str(data.get("groq_api_key", "")).strip(),
                "username": str(data.get("username", "")).strip(),
                "password": str(data.get("password", "")),
                "lessons": int(data.get("lessons", 40)),
                "headless": bool(data.get("headless", False)),
            }
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(to_save, indent=2), encoding="utf-8")
            tmp.replace(target)
            return True
        except Exception:
            return False

    def add_log(self, text):
        with self.lock:
            # Track live question statistics
            if "selected option:" in text or "[MCQ] Answering questions" in text:
                if "selected option:" in text:
                    self.questions_answered += 1

            self.log_history.append(text)
            if len(self.log_history) > 3000:
                self.log_history.pop(0)
        self.log_queue.put(text)

    def _resolve_command(self):
        """Find executable in bundled .app or fallback to python script."""
        exe_candidates = [
            ROOT_DIR / "achieve3000_automation",
            ROOT_DIR.parent / "MacOS" / "achieve3000_automation",
        ]
        for exe in exe_candidates:
            if exe.exists():
                try:
                    os.chmod(str(exe), 0o755)
                except OSError:
                    pass
                return [str(exe)]

        script_candidates = [
            ROOT_DIR / "achieve3000_automation.py",
            ROOT_DIR.parent / "Resources" / "achieve3000_automation.py",
        ]
        for s in script_candidates:
            if s.exists():
                return [sys.executable, "-u", str(s)]

        return [str(ROOT_DIR / "achieve3000_automation")]

    def _resolve_browsers(self):
        """Find bundled Playwright Chromium runtime."""
        browser_candidates = [
            ROOT_DIR.parent / "Resources" / "playwright-browsers",
            ROOT_DIR / "playwright-browsers",
            ROOT_DIR.parent / "MacOS" / "playwright-browsers",
        ]
        for bc in browser_candidates:
            if bc.exists():
                return str(bc)
        return None

    def start(self, config):
        with self.lock:
            if self.process and self.process.poll() is None:
                return False, "Automation is already running."

            self.save_settings(config)
            self.log_history.clear()
            self.questions_answered = 0
            self.start_time = time.time()

            while not self.log_queue.empty():
                try:
                    self.log_queue.get_nowait()
                except queue.Empty:
                    break

            env = os.environ.copy()
            env.update({
                "GROQ_API_KEY": str(config.get("groq_api_key", "")).strip(),
                "ACHIEVE3000_USERNAME": str(config.get("username", "")).strip(),
                "ACHIEVE3000_PASSWORD": str(config.get("password", "")),
                "ITERATIONS": str(config.get("lessons", 40)),
                "HEADLESS": "true" if config.get("headless") else "false",
                "PYTHONUNBUFFERED": "1",
            })

            browser_path = self._resolve_browsers()
            if browser_path:
                env["PLAYWRIGHT_BROWSERS_PATH"] = browser_path
                self.add_log(f"[Launcher] Using bundled Playwright browser: {browser_path}\n")

            cmd = self._resolve_command()
            self.add_log(f"[Launcher] Command: {' '.join(cmd)}\n")
            self.add_log(f"[Launcher] Starting run (Lessons: {config.get('lessons')}, Headless: {config.get('headless')})...\n")

            try:
                self.process = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT_DIR),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
                self.status = "Running"
            except Exception as e:
                self.status = "Failed to start"
                self.add_log(f"[Error] Failed to spawn process: {e}\n")
                return False, str(e)

            threading.Thread(target=self._monitor_output, daemon=True).start()
            return True, "Started"

    def _monitor_output(self):
        p = self.process
        if not p or not p.stdout:
            return
        try:
            for line in iter(p.stdout.readline, ''):
                if not line:
                    break
                self.add_log(line)
        except Exception as e:
            self.add_log(f"\n[Reader error: {e}]\n")
        finally:
            code = p.wait()
            with self.lock:
                self.status = "Completed" if code == 0 else f"Stopped (Code {code})"
            self.add_log(f"\n[Launcher] Process exited with code {code}\n")
            if code == 0:
                send_mac_notification("Achieve3000 Runner", "All lesson iterations completed successfully!")
            else:
                send_mac_notification("Achieve3000 Runner", f"Automation stopped with exit code {code}.")

    def stop(self):
        with self.lock:
            p = self.process
            if not p or p.poll() is not None:
                return False, "Not running."

            self.status = "Stopping..."
            self.add_log("\n[Launcher] Stopping automation...\n")
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except Exception:
                try:
                    p.terminate()
                except Exception:
                    pass

        threading.Thread(target=self._force_kill_if_stuck, args=(p,), daemon=True).start()
        return True, "Stopping"

    def _force_kill_if_stuck(self, p):
        time.sleep(3)
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


manager = AutomationManager()

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Achieve3000 Runner</title>
<link rel="icon" type="image/png" href="/icon.png">
<style>
  :root {
    --bg: #090e17;
    --card: #111a2e;
    --card-border: #1e293b;
    --input-bg: #0b1220;
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --accent: #38bdf8;
    --accent-hover: #0ea5e9;
    --accent-glow: rgba(56, 189, 248, 0.25);
    --stop: #f43f5e;
    --stop-hover: #e11d48;
    --terminal-bg: #050811;
    --success: #34d399;
    --font: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif;
    --mono: "SF Mono", Menlo, Consolas, Monaco, monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    display: flex;
    justify-content: center;
    padding: 22px;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
    user-select: none;
  }
  .container {
    width: 100%;
    max-width: 780px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: 4px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .brand-logo {
    width: 38px;
    height: 38px;
    border-radius: 9px;
    box-shadow: 0 4px 14px rgba(56, 189, 248, 0.2);
  }
  h1 {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #fff;
  }
  .subtitle {
    color: var(--text-muted);
    font-size: 12px;
  }
  .quit-btn {
    background: transparent;
    border: 1px solid var(--card-border);
    color: #64748b;
    font-size: 11px;
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .quit-btn:hover {
    color: #f43f5e;
    border-color: #f43f5e;
  }

  /* Stats Bar */
  .stats-bar {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
  }
  .stat-card {
    background: var(--card);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .stat-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    color: var(--text-muted);
    letter-spacing: 0.04em;
  }
  .stat-val {
    font-size: 16px;
    font-weight: 700;
    color: #fff;
    font-family: var(--mono);
  }

  .card {
    background: var(--card);
    border: 1px solid var(--card-border);
    border-radius: 12px;
    padding: 18px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .card-title {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--accent);
  }
  .save-status {
    font-size: 11px;
    font-weight: 600;
    color: var(--success);
    transition: color 0.2s;
  }
  .form-grid {
    display: grid;
    grid-template-columns: 170px 1fr;
    gap: 12px 18px;
    align-items: center;
  }
  label {
    font-size: 13px;
    color: var(--text-muted);
    font-weight: 500;
  }
  input[type="text"], input[type="password"], input[type="number"] {
    width: 100%;
    background: var(--input-bg);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 9px 13px;
    font-size: 13px;
    color: #fff;
    font-family: var(--font);
    outline: none;
    transition: border-color 0.15s, box-shadow 0.15s;
    user-select: text;
  }
  input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-glow);
  }
  .field-desc {
    grid-column: 2;
    font-size: 11px;
    color: #64748b;
    margin-top: -5px;
  }
  .toggle-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .switch {
    position: relative;
    display: inline-block;
    width: 42px;
    height: 22px;
  }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider {
    position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
    background-color: #334155;
    transition: .2s;
    border-radius: 22px;
  }
  .slider:before {
    position: absolute; content: ""; height: 16px; width: 16px; left: 3px; bottom: 3px;
    background-color: white;
    transition: .2s;
    border-radius: 50%;
  }
  input:checked + .slider { background-color: var(--accent); }
  input:checked + .slider:before { transform: translateX(20px); }

  .actions {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  button.action-btn {
    font-family: var(--font);
    font-size: 13px;
    font-weight: 600;
    padding: 10px 22px;
    border-radius: 8px;
    border: none;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    transition: all 0.15s ease;
  }
  .btn-start {
    background: var(--accent);
    color: #082f49;
    box-shadow: 0 4px 14px rgba(56, 189, 248, 0.25);
  }
  .btn-start:hover:not(:disabled) {
    background: var(--accent-hover);
    color: #fff;
    transform: translateY(-1px);
  }
  .btn-stop {
    background: var(--stop);
    color: #fff;
  }
  .btn-stop:hover:not(:disabled) {
    background: var(--stop-hover);
    transform: translateY(-1px);
  }
  button:disabled {
    opacity: 0.35;
    cursor: not-allowed;
    transform: none !important;
  }
  .status-text {
    margin-left: auto;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
  }
  .status-badge {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #64748b;
    transition: all 0.2s;
  }
  .status-badge.active {
    background: var(--success);
    box-shadow: 0 0 10px var(--success);
    animation: pulse 1.6s infinite;
  }
  @keyframes pulse {
    0% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.3); opacity: 0.7; }
    100% { transform: scale(1); opacity: 1; }
  }

  .terminal-wrap {
    background: var(--terminal-bg);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    height: 290px;
  }
  .terminal-header {
    background: #0d1424;
    padding: 8px 14px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--card-border);
  }
  .term-controls {
    display: flex;
    gap: 12px;
    align-items: center;
  }
  .term-action {
    color: #64748b;
    cursor: pointer;
    font-size: 11px;
    transition: color 0.15s;
  }
  .term-action:hover { color: #fff; }
  #terminal {
    flex: 1;
    padding: 12px 14px;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.55;
    color: #cbd5e1;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    user-select: text;
  }
  .log-line { display: block; }
  .log-mcq { color: #38bdf8; font-weight: 500; }
  .log-err { color: #fb7185; font-weight: 600; }
  .log-ok  { color: #34d399; }
  .log-dim { color: #64748b; }
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="brand">
      <img src="/icon.png" alt="Logo" class="brand-logo" onerror="this.style.display='none'">
      <div>
        <h1>Achieve3000 Runner</h1>
        <div class="subtitle">macOS Automation Suite & Live Progress Stream</div>
      </div>
    </div>
    <button class="quit-btn" onclick="quitApp()" title="Close app">Quit App</button>
  </header>

  <!-- Live Stats -->
  <div class="stats-bar">
    <div class="stat-card">
      <span class="stat-label">Status</span>
      <span class="stat-val" id="statStatus">Ready</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Elapsed Time</span>
      <span class="stat-val" id="statElapsed">00:00:00</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Questions Solved</span>
      <span class="stat-val" id="statQuestions">0</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Target Lessons</span>
      <span class="stat-val" id="statTarget">40</span>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <div class="card-title">Credentials & Settings</div>
      <span id="saveStatus" class="save-status">Auto-saved ✓</span>
    </div>
    <div class="form-grid">
      <label for="groq_key">Groq API Key</label>
      <input type="password" id="groq_key" placeholder="gsk_..." autocomplete="off" oninput="scheduleAutoSave()">

      <label for="username">Achieve3000 Username</label>
      <input type="text" id="username" placeholder="Student username" autocomplete="off" oninput="scheduleAutoSave()">

      <label for="password">Achieve3000 Password</label>
      <input type="password" id="password" placeholder="••••••••" autocomplete="off" oninput="scheduleAutoSave()">

      <label for="lessons">Lesson Iterations</label>
      <input type="number" id="lessons" value="40" min="1" max="9999" oninput="scheduleAutoSave(); updateTarget()">
      <div class="field-desc">Configures how many lessons to complete before stopping.</div>

      <label>Headless Mode</label>
      <div class="toggle-wrap">
        <label class="switch">
          <input type="checkbox" id="headless" onchange="scheduleAutoSave()">
          <span class="slider"></span>
        </label>
        <span style="font-size: 12px; color: var(--text-muted);">Run Chromium in background without opening browser window</span>
      </div>
    </div>
  </div>

  <div class="actions">
    <button id="startBtn" class="action-btn btn-start" onclick="startAutomation()">▶  Start Automation</button>
    <button id="stopBtn" class="action-btn btn-stop" onclick="stopAutomation()" disabled>■  Stop</button>
    <div class="status-text">
      <span id="badge" class="status-badge"></span>
      <span id="statusLabel">Ready</span>
    </div>
  </div>

  <div class="card" style="padding: 12px;">
    <div class="terminal-wrap">
      <div class="terminal-header">
        <span>Live Output</span>
        <div class="term-controls">
          <label style="display:flex; align-items:center; gap:5px; font-size:11px; color:#64748b; cursor:pointer;">
            <input type="checkbox" id="autoScroll" checked style="accent-color:var(--accent)"> Auto-scroll
          </label>
          <span class="term-action" onclick="copyLogs()">Copy Logs</span>
          <span class="term-action" onclick="clearTerminal()">Clear</span>
        </div>
      </div>
      <div id="terminal"></div>
    </div>
  </div>
</div>

<script>
  let isRunning = false;
  let logOffset = 0;
  let startTime = null;
  let timerInterval = null;
  let autoSaveTimeout = null;

  async function loadSettings() {
    try {
      const res = await fetch('/api/settings');
      const data = await res.json();
      if (data.groq_api_key) document.getElementById('groq_key').value = data.groq_api_key;
      if (data.username) document.getElementById('username').value = data.username;
      if (data.password) document.getElementById('password').value = data.password;
      if (data.lessons) document.getElementById('lessons').value = data.lessons;
      document.getElementById('headless').checked = !!data.headless;
      updateTarget();
      setSaveStatus("Loaded ✓", "#34d399");
    } catch(e) {
      console.error(e);
      setSaveStatus("Offline", "#fb7185");
    }
  }

  function setSaveStatus(text, color) {
    const el = document.getElementById('saveStatus');
    if (el) {
      el.textContent = text;
      el.style.color = color;
    }
  }

  function scheduleAutoSave() {
    setSaveStatus("Saving...", "#38bdf8");
    if (autoSaveTimeout) clearTimeout(autoSaveTimeout);
    autoSaveTimeout = setTimeout(persistSettingsToServer, 400);
  }

  async function persistSettingsToServer() {
    const config = getFormConfig();
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      const data = await res.json();
      if (data.ok) {
        setSaveStatus("Saved ✓", "#34d399");
      } else {
        setSaveStatus("Save error", "#fb7185");
      }
    } catch(e) {
      setSaveStatus("Save error", "#fb7185");
    }
  }

  function updateTarget() {
    document.getElementById('statTarget').textContent = document.getElementById('lessons').value || 40;
  }

  function getFormConfig() {
    return {
      groq_api_key: document.getElementById('groq_key').value.trim(),
      username: document.getElementById('username').value.trim(),
      password: document.getElementById('password').value,
      lessons: parseInt(document.getElementById('lessons').value, 10) || 40,
      headless: document.getElementById('headless').checked
    };
  }

  async function startAutomation() {
    const config = getFormConfig();
    if (!config.groq_api_key) {
      alert("Please enter your Groq API key.");
      return;
    }
    if (!config.username || !config.password) {
      alert("Please enter your Achieve3000 credentials.");
      return;
    }

    // Persist immediately on start
    persistSettingsToServer();

    document.getElementById('startBtn').disabled = true;
    document.getElementById('stopBtn').disabled = false;
    logOffset = 0;
    document.getElementById('terminal').innerHTML = '';
    startTime = Date.now();
    startTimer();

    try {
      const res = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      const data = await res.json();
      if (!data.ok) {
        alert("Failed to start: " + data.message);
        document.getElementById('startBtn').disabled = false;
        document.getElementById('stopBtn').disabled = true;
        stopTimer();
      }
    } catch (e) {
      alert("Request error: " + e);
      document.getElementById('startBtn').disabled = false;
      document.getElementById('stopBtn').disabled = true;
      stopTimer();
    }
  }

  async function stopAutomation() {
    document.getElementById('stopBtn').disabled = true;
    try {
      await fetch('/api/stop', { method: 'POST' });
    } catch(e) {
      console.error(e);
    }
  }

  function formatLogLine(text) {
    const span = document.createElement('span');
    span.className = 'log-line';
    if (text.includes('[Error]') || text.includes('failed') || text.includes('Traceback')) {
      span.className += ' log-err';
    } else if (text.includes('selected option:') || text.includes('[MCQ]')) {
      span.className += ' log-mcq';
    } else if (text.includes('complete') || text.includes('Finished') || text.includes('Groq ready')) {
      span.className += ' log-ok';
    } else if (text.includes('[TELEMETRY]') || text.includes('INFO')) {
      span.className += ' log-dim';
    }
    span.textContent = text;
    return span;
  }

  function clearTerminal() {
    document.getElementById('terminal').innerHTML = '';
  }

  function copyLogs() {
    const text = document.getElementById('terminal').innerText;
    navigator.clipboard.writeText(text).then(() => {
      alert("Logs copied to clipboard!");
    });
  }

  async function quitApp() {
    if (confirm("Quit Achieve3000 Runner?")) {
      await persistSettingsToServer();
      await fetch('/api/quit', { method: 'POST' });
      window.close();
    }
  }

  function startTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
      if (!startTime) return;
      const diff = Math.floor((Date.now() - startTime) / 1000);
      const h = String(Math.floor(diff / 3600)).padStart(2, '0');
      const m = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
      const s = String(diff % 60).padStart(2, '0');
      document.getElementById('statElapsed').textContent = `${h}:${m}:${s}`;
    }, 1000);
  }

  function stopTimer() {
    if (timerInterval) clearInterval(timerInterval);
  }

  async function pollStatus() {
    try {
      const res = await fetch('/api/poll?offset=' + logOffset);
      const data = await res.json();

      isRunning = data.running;
      document.getElementById('statusLabel').textContent = data.status;
      document.getElementById('statStatus').textContent = data.status;
      document.getElementById('badge').className = isRunning ? 'status-badge active' : 'status-badge';
      document.getElementById('startBtn').disabled = isRunning;
      document.getElementById('stopBtn').disabled = !isRunning;
      document.getElementById('statQuestions').textContent = data.questions || 0;

      if (isRunning && !timerInterval) {
        if (data.start_time) startTime = data.start_time * 1000;
        startTimer();
      } else if (!isRunning && timerInterval) {
        stopTimer();
      }

      if (data.new_logs && data.new_logs.length > 0) {
        const term = document.getElementById('terminal');
        const frag = document.createDocumentFragment();
        for (const log of data.new_logs) {
          frag.appendChild(formatLogLine(log));
        }
        term.appendChild(frag);
        if (document.getElementById('autoScroll').checked) {
          term.scrollTop = term.scrollHeight;
        }
        logOffset = data.next_offset;
      }
    } catch (e) {
      // transient connection error
    }
    setTimeout(pollStatus, 400);
  }

  window.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    pollStatus();
  });

  window.addEventListener('beforeunload', () => {
    navigator.sendBeacon('/api/settings', JSON.stringify(getFormConfig()));
  });
</script>
</body>
</html>
"""


class LauncherHTTPHandler(BaseHTTPRequestHandler):
    def address_string(self):
        # Crucial for macOS: prevent socket.getfqdn from doing reverse DNS lookup which causes 10-30s hangs
        return self.client_address[0]

    def log_message(self, format, *args):
        pass  # Suppress console HTTP access logs

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif parsed.path == "/icon.png":
            if ICON_PNG.exists():
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(ICON_PNG.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()
        elif parsed.path == "/api/settings":
            data = manager.load_settings()
            self.send_json(data)
        elif parsed.path == "/api/poll":
            params = parse_qs(parsed.query)
            offset = int(params.get("offset", [0])[0])
            with manager.lock:
                total = len(manager.log_history)
                new_logs = manager.log_history[offset:]
                is_running = (manager.process is not None and manager.process.poll() is None)
                status = manager.status
                start_time = manager.start_time
                questions = manager.questions_answered
            self.send_json({
                "running": is_running,
                "status": status,
                "start_time": start_time,
                "questions": questions,
                "new_logs": new_logs,
                "next_offset": total
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if parsed.path == "/api/settings":
            ok = manager.save_settings(payload)
            self.send_json({"ok": ok, "message": "Settings saved"})
        elif parsed.path == "/api/start":
            ok, msg = manager.start(payload)
            self.send_json({"ok": ok, "message": msg})
        elif parsed.path == "/api/stop":
            ok, msg = manager.stop()
            self.send_json({"ok": ok, "message": msg})
        elif parsed.path == "/api/quit":
            manager.stop()
            self.send_json({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0))).start()
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def open_mac_window(url):
    """Open in standalone App Mode via Chrome/Edge/Brave/Arc if available, else default browser."""
    candidate_browsers = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        Path("/Applications/Arc.app/Contents/MacOS/Arc"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"),
    ]

    for browser in candidate_browsers:
        if browser.exists():
            subprocess.Popen([
                str(browser),
                f"--app={url}",
                "--window-size=820,780",
                "--window-position=200,80"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

    # Fallback to default macOS browser
    subprocess.Popen(["open", url])


def main():
    port = find_free_port()
    server = ThreadingHTTPServer(('127.0.0.1', port), LauncherHTTPHandler)
    url = f"http://127.0.0.1:{port}"

    print(f"==================================================")
    print(f" Achieve3000 Mac Launcher running at: {url}")
    print(f"==================================================")

    # Open UI window in a separate thread
    threading.Thread(target=lambda: (time.sleep(0.35), open_mac_window(url)), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down launcher...")
    finally:
        manager.stop()
        server.server_close()


if __name__ == "__main__":
    main()
