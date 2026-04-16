$exe = Join-Path $PSScriptRoot "dist\XDigestReporter.exe"
if (Test-Path $exe) {
  Start-Process -FilePath $exe
} else {
  Write-Host "File not found: $exe"
  Write-Host "Run build_exe.ps1 first."
}