@echo off
setlocal
cd /d "%~dp0"
set "EXE=%CD%\dist\XDigestReporter.exe"
if not exist "%EXE%" goto missing
start "" "%EXE%"
exit /b 0

:missing
echo File not found: %EXE%
echo Run build_exe.ps1 first.
pause
exit /b 1