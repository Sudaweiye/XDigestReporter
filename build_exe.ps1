$ErrorActionPreference = "Stop"
Set-Location "E:\XDigestReporter"
python -m pip install --upgrade pip
python -m pip install -r .\requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name XDigestReporter .\main.py
Write-Host "\nBuild completed: E:\XDigestReporter\dist\XDigestReporter.exe"
