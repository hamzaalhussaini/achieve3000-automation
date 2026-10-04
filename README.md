# Achieve3000 automation

Playwright automation for Achieve3000 2-step and 5-step lessons, with Groq-backed question answering and a Windows launcher.

## Setup

Install Python dependencies and Chromium:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Create a local `.env` from `.env.example` and add your own credentials:

```powershell
Copy-Item .env.example .env
```

Never commit `.env`, API keys, passwords, or launcher settings.

## Run directly

```powershell
python achieve3000_automation.py
```

## Run with the launcher

```powershell
python launcher.py
```

The launcher saves the username, password, Groq API key, and browser preference locally. The lesson count defaults to 40 and is not saved.

## Build the Windows app

```powershell
powershell -ExecutionPolicy Bypass -File .\build_launcher.ps1
```

The packaged launcher is created under `dist\Achieve3000Launcher\`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ACHIEVE3000_USERNAME` | — | Achieve3000 username |
| `ACHIEVE3000_PASSWORD` | — | Achieve3000 password |
| `GROQ_API_KEY` | — | Groq API key |
| `HEADLESS` | `false` | Hide the browser when `true` |
| `ITERATIONS` | `40` | Number of lesson iterations |
| `REBUILD_EVERY` | `5` | Rebuild the browser context after this many iterations |
