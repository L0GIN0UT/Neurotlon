; Extra step for the electron-builder NSIS installer.
;
; The stock check only closes the main exe, while the launcher core, the sensor bridge and the
; games (all under resources\) keep running and lock their files, so an update hangs or fails.
; This macro replaces the stock check and stops every process whose executable lies inside the
; install folder. Same-named programs from other folders are not touched (match by full path).
;
; The macro runs before files are copied (installer, INSTDIR already known) and before they are
; removed (uninstaller). Uninstall*.exe is skipped: the uninstaller may run from INSTDIR itself.
!macro customCheckAppRunning
  nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$d = '$INSTDIR\'; Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -and $$_.ExecutablePath.StartsWith($$d, [StringComparison]::OrdinalIgnoreCase) -and $$_.Name -notlike 'Uninstall*' } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
  Pop $0
  Sleep 1500
!macroend
