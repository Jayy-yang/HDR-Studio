# Build the Windows app folder and create a per-user Start Menu shortcut.
# Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv Python: $Python"
}

$Assets = (Resolve-Path (Join-Path $Root "assets")).Path
$Icon = (Resolve-Path (Join-Path $Root "assets\logo.ico")).Path
$Dist = Join-Path $Root "dist_app"
$Build = Join-Path $Root "build_app"

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..."
    & $Python -m pip install --disable-pip-version-check pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install PyInstaller."
    }
}

if (Test-Path -LiteralPath $Dist) { Remove-Item -LiteralPath $Dist -Recurse -Force }
if (Test-Path -LiteralPath $Build) { Remove-Item -LiteralPath $Build -Recurse -Force }

Write-Host "Building HDR Studio..."
& $Python -m PyInstaller `
    --noconfirm --clean --onedir --windowed `
    --name "HDR Studio" `
    --icon "$Icon" `
    --add-data "$Assets;assets" `
    --distpath "$Dist" `
    --workpath "$Build" `
    --specpath "$Build" `
    --log-level WARN `
    (Join-Path $Root "app.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$BuiltApp = Join-Path $Dist "HDR Studio"
$Target = Join-Path $Root "HDR Studio"
if (-not (Test-Path -LiteralPath $Target)) {
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
}
if (Test-Path -LiteralPath (Join-Path $Target "_internal")) {
    Remove-Item -LiteralPath (Join-Path $Target "_internal") -Recurse -Force
}
$TargetExe = Join-Path $Target "HDR Studio.exe"
if (Test-Path -LiteralPath $TargetExe) {
    Remove-Item -LiteralPath $TargetExe -Force
}
Copy-Item -Path (Join-Path $BuiltApp "*") -Destination $Target -Recurse -Force

# The installed app is deliberately kept inside the project folder.  Some
# Windows policies block execution from %LOCALAPPDATA%\Programs, while this
# folder is already the user's working copy.
$TargetExe = Join-Path $Target "HDR Studio.exe"
$Marker = Join-Path $Target "hdrstudio_self_test.txt"
if (Test-Path -LiteralPath $Marker) { Remove-Item -LiteralPath $Marker -Force }
# Use Python's subprocess rather than Start-Process: PowerShell's GUI-process
# wait path can block indefinitely for a windowed executable in some hosts.
$env:HDRSTUDIO_PROBE_EXE = $TargetExe
& $Python -c "import os, subprocess, sys; p = subprocess.run([os.environ['HDRSTUDIO_PROBE_EXE'], '--self-test'], timeout=60); sys.exit(p.returncode)"
$probeExit = $LASTEXITCODE
Remove-Item Env:\HDRSTUDIO_PROBE_EXE -ErrorAction SilentlyContinue
if ($probeExit -ne 0 -or -not (Test-Path -LiteralPath $Marker)) {
    throw "The packaged app failed its self-test (exit $probeExit)."
}
Remove-Item -LiteralPath $Marker -Force

$Programs = [Environment]::GetFolderPath("Programs")
$ShortcutPath = Join-Path $Programs "HDR Studio.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetExe
$Shortcut.WorkingDirectory = $Target
$Shortcut.IconLocation = "$TargetExe,0"
$Shortcut.Description = "HDR Studio - Multi-exposure"
$Shortcut.Save()

Remove-Item -LiteralPath $Dist -Recurse -Force
Remove-Item -LiteralPath $Build -Recurse -Force

Write-Host ""
Write-Host "App:      $TargetExe"
Write-Host "Shortcut: $ShortcutPath"
Write-Host "Done."
