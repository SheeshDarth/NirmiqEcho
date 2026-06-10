' NirmiqEcho silent launcher — runs start.bat with no console window.
' Used by autostart; double-click start.bat directly if you want the console.
Dim fso, shell, scriptDir
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir
shell.Run Chr(34) & scriptDir & "\start.bat" & Chr(34), 0, False
