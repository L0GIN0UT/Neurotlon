; Extra step for the electron-builder NSIS installer.
;
; The launcher core, the sensor bridge and the games (all under resources\) keep running after
; the window is closed and lock their files, so an update hangs or fails. This macro replaces
; the stock check and stops only what belongs to THIS installation:
;   - every process whose exe lies under <INSTDIR>\resources\ (core, bridge, games);
;   - the main exe <INSTDIR>\<APP_EXECUTABLE_FILENAME> (exact path).
; Same-named programs from other folders are not touched (match by full path). The installer
; itself ($EXEPATH) and the parent of the PowerShell it starts are never stopped, so it does not
; kill itself when it runs from INSTDIR (the uninstaller does).
;
; The install path is passed through environment variables, never pasted into the command text,
; so a path with a quote, a space, a dollar sign or Cyrillic cannot break the script.
;
; Runs before files are copied (installer, INSTDIR is known) and before they are removed
; (uninstaller). Without PowerShell it falls back to closing the main exe by name (nsProcess,
; as the stock macro does); then core, bridge and games may stay running.
!macro customCheckAppRunning
  !insertmacro IS_POWERSHELL_AVAILABLE
  ${if} $IsPowerShellAvailable == 0
    System::Call 'Kernel32::SetEnvironmentVariable(t "NT_INSTDIR", t "$INSTDIR")i'
    System::Call 'Kernel32::SetEnvironmentVariable(t "NT_MAIN_EXE", t "$INSTDIR\${APP_EXECUTABLE_FILENAME}")i'
    System::Call 'Kernel32::SetEnvironmentVariable(t "NT_SELF", t "$EXEPATH")i'
    nsExec::Exec `"$PowerShellPath" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$me = $$PID; $$parent = (Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $$PID)).ParentProcessId; $$root = $$env:NT_INSTDIR.TrimEnd([char]92) + [char]92 + 'resources' + [char]92; Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -and $$_.ProcessId -ne $$me -and $$_.ProcessId -ne $$parent -and $$_.ExecutablePath -ne $$env:NT_SELF -and ($$_.ExecutablePath.StartsWith($$root, [StringComparison]::OrdinalIgnoreCase) -or $$_.ExecutablePath -ieq $$env:NT_MAIN_EXE) } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
    Pop $0
  ${else}
    nsProcess::_KillProcess "${APP_EXECUTABLE_FILENAME}"
    Pop $0
  ${endIf}
  Sleep 1500
!macroend
