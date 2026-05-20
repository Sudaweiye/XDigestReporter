$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir
python -m pip install --upgrade pip
python -m pip install -r .\requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name XDigestReporter .\main.py
Write-Host "`nBuild completed: $scriptDir\dist\XDigestReporter.exe"
