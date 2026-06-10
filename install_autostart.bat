@echo off
title NirmiqEcho — Autostart Installer
:: Creates a Startup-folder shortcut so Echo launches silently at login.

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%~dp0start_silent.vbs"

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$sc = $ws.CreateShortcut('%STARTUP%\NirmiqEcho.lnk'); " ^
  "$sc.TargetPath = 'wscript.exe'; " ^
  "$sc.Arguments = '\"%TARGET%\"'; " ^
  "$sc.WorkingDirectory = '%~dp0'; " ^
  "$sc.Description = 'NirmiqEcho voice assistant'; " ^
  "$sc.Save()"

if exist "%STARTUP%\NirmiqEcho.lnk" (
    echo [OK] NirmiqEcho will now start automatically when you log in.
    echo      To remove: delete "%STARTUP%\NirmiqEcho.lnk"
) else (
    echo [ERROR] Could not create the startup shortcut.
)
pause
