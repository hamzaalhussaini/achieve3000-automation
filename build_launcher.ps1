$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

$browser_dir = Join-Path (Get-Location) "playwright-browsers"
$env:PLAYWRIGHT_BROWSERS_PATH = $browser_dir
python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Playwright Chromium installation failed." }
if (-not (Test-Path $browser_dir)) { throw "Playwright browser directory was not created." }

if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }

python -m PyInstaller --noconfirm --clean --onefile --icon achieve3000.ico --name achieve3000_automation achieve3000_automation.py
python -m PyInstaller --noconfirm --clean --onedir --noconsole --icon achieve3000.ico --name Achieve3000Launcher launcher.py

Copy-Item dist\achieve3000_automation.exe dist\Achieve3000Launcher\achieve3000_automation.exe
Copy-Item -Recurse $browser_dir dist\Achieve3000Launcher\playwright-browsers
if (Test-Path .env) { Copy-Item .env dist\Achieve3000Launcher\.env }

Write-Host "Created: dist\Achieve3000Launcher\Achieve3000Launcher.exe"
