Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Get the directory where this VBS script is located
strScriptPath = objFSO.GetParentFolderName(WScript.ScriptFullName)
strPS1File = strScriptPath & "\ATS_TrayLauncher.ps1"

' Run the PowerShell script hidden (WindowStyle 0)
psCommand = "powershell.exe -ExecutionPolicy Bypass -File """ & strPS1File & """"
objShell.Run psCommand, 0, False
