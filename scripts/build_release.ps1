# GuildModel release build — run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
#
# Gates on the test suite, then produces distribution artifacts in dist\:
#   1. GuildModel-<version>-win64.zip     portable one-folder build (unzip + run)
#   2. GuildModel-<version>-setup.exe     per-user Inno Setup installer
# The installer step is skipped with a warning if Inno Setup (ISCC.exe) is absent.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"

# 1. Test gate — never ship a build from a red suite
& $py -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Test suite failed - build aborted." }

# 2. Read the version stamp from the package; derive a numeric x.y.z.w for the
#    installer's VersionInfo (strips any pre-release suffix like -rc1).
$version = & $py -c "from guildmodel import __version__; print(__version__)"
$numericBase = ($version -split '-')[0]
$parts = @($numericBase -split '\.')
while ($parts.Count -lt 4) { $parts += '0' }
$numeric = ($parts[0..3]) -join '.'
Write-Host "Building GuildModel $version (VersionInfo $numeric)" -ForegroundColor Cyan

# 3. Refresh the app icon from assets\icon.svg
& $py (Join-Path $repo "scripts\make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }

# 4. Freeze OFF-DRIVE (the GuildSend pattern): Google Drive locks the frozen
#    exe mid-build, so PyInstaller and Inno both work in a LOCAL scratch dir;
#    only the finished artifacts are copied back into the repo's dist\.
$build = Join-Path $env:LOCALAPPDATA "GuildModelBuild"
$buildDist = Join-Path $build "dist"
$buildWork = Join-Path $build "work"
$buildOut  = Join-Path $build "out"
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory -Force $buildDist, $buildWork, $buildOut | Out-Null
New-Item -ItemType Directory -Force (Join-Path $repo "dist") | Out-Null

& $py -m PyInstaller guildmodel.spec --clean --noconfirm --distpath $buildDist --workpath $buildWork
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (one-folder) failed." }

# 5. Zip the one-folder build locally, then copy back to the repo
$zipLocal = Join-Path $build "GuildModel-$version-win64.zip"
Compress-Archive -Path (Join-Path $buildDist "GuildModel") -DestinationPath $zipLocal -Force
$zip = Join-Path $repo "dist\GuildModel-$version-win64.zip"
Copy-Item $zipLocal $zip -Force
Write-Host "  zip:       $zip" -ForegroundColor Green

# 6. Build the per-user installer with Inno Setup (skip if ISCC is missing).
#    /O + MySourceDir redirect BOTH the compiler's work and the finished
#    setup.exe off-drive; the result is copied back like the zip.
$iscc = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if ($iscc) {
    & $iscc "/DMyAppVersion=$version" "/DMyAppVersionNumeric=$numeric" `
        "/DMySourceDir=$(Join-Path $buildDist 'GuildModel')" `
        "/O$buildOut" `
        (Join-Path $repo "installer\GuildModel.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed." }
    $setupLocal = Join-Path $buildOut "GuildModel-$version-setup.exe"
    $setup = Join-Path $repo "dist\GuildModel-$version-setup.exe"
    Copy-Item $setupLocal $setup -Force
    Write-Host "  installer: $setup" -ForegroundColor Green
} else {
    Write-Warning "Inno Setup (ISCC.exe) not found - skipped installer. Install it with: winget install JRSoftware.InnoSetup"
}

Write-Host "Done." -ForegroundColor Green
