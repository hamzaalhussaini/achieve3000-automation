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

## Build macOS app

Run the macOS build on a Mac. The generated DMG includes the drag-to-Applications layout:

```bash
bash build_macos.sh
bash package_macos_dmg.sh
```

## Publish Windows and macOS releases

Push a version tag from the repository. GitHub Actions builds both launchers and attaches them to the release:

```powershell
git add .
git commit -m "Prepare cross-platform release"
git push origin master
git tag v1.0.15
git push origin v1.0.15
```

The release contains `Achieve3000Setup-v*.exe` and `Achieve3000-macOS.dmg`.

### macOS Installation & Gatekeeper Note

Because the app is open-source and not signed with an expensive Apple Developer ID certificate, macOS Gatekeeper may show:
`"Achieve3000Launcher is damaged and can't be opened. You should move it to the Trash."`

To install cleanly:
1. Open the `.dmg` and drag **Achieve3000Launcher** to **Applications**.
2. If macOS reports the app as damaged, run `Fix Damaged App.command` from the DMG after installation. If Gatekeeper blocks the helper, Control-click the helper and choose **Open**. It removes only `com.apple.quarantine` from the installed app, then opens it.
3. If launch is still blocked, Control-click `Achieve3000Launcher.app` in Applications and select **Open**.

The app is not Developer ID signed or notarized. The helper does not bypass administrator controls or disable certificate checks; it removes the download quarantine flag for this app only. Some managed Macs may prohibit this action through device policy.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ACHIEVE3000_USERNAME` | — | Achieve3000 username |
| `ACHIEVE3000_PASSWORD` | — | Achieve3000 password |
| `GROQ_API_KEY` | — | Groq API key |
| `HEADLESS` | `false` | Hide the browser when `true` |
| `ITERATIONS` | `40` | Number of lesson iterations |
| `REBUILD_EVERY` | `5` | Rebuild the browser context after this many iterations |
