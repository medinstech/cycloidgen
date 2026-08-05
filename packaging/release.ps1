<#
.SYNOPSIS
    Build the Windows bundle and the installer, in that order.

.DESCRIPTION
    Two steps that have to happen in sequence and are easy to get wrong:
    PyInstaller writes dist\cycloidgen, and makensis packages whatever is
    sitting there.  Running makensis against a stale dist produces an installer
    for the previous version, with the *new* version number on it, and nothing
    complains.  So this script always rebuilds, and refuses to package a bundle
    whose executable does not report the version it is about to stamp on the
    installer.

.EXAMPLE
    .\packaging\release.ps1
    .\packaging\release.ps1 -FastPack -SkipTests
    .\packaging\release.ps1 -SignCmd 'signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /a'
#>
[CmdletBinding()]
param(
    # zlib instead of LZMA: about four times faster to pack, a much larger
    # installer.  Internal test builds only - never for something distributed.
    [switch]$FastPack,
    [switch]$SkipTests,
    # Passed through to makensis, which signs both the installer and the
    # uninstaller stub.  Empty means unsigned.
    [string]$SignCmd = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

try {
    $python = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }

    $version = (& $python -c "import cycloidgen; print(cycloidgen.__version__)").Trim()
    if (-not $version) { throw 'could not read the version from cycloidgen/__init__.py' }
    Write-Host "cycloidgen $version" -ForegroundColor Cyan

    if (-not $SkipTests) {
        Write-Host '--- tests' -ForegroundColor Cyan
        $env:QT_QPA_PLATFORM = 'offscreen'
        $env:MPLBACKEND = 'Agg'
        & $python -m ruff check .
        if ($LASTEXITCODE -ne 0) { throw 'ruff failed' }
        & $python -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'tests failed' }
        Remove-Item Env:\QT_QPA_PLATFORM, Env:\MPLBACKEND
    }

    Write-Host '--- bundle' -ForegroundColor Cyan
    # Always from scratch.  A partial rebuild over a bundle from a different
    # version is the failure this whole script exists to prevent.
    if (Test-Path 'dist\cycloidgen') { Remove-Item -Recurse -Force 'dist\cycloidgen' }
    & $python -m PyInstaller cycloidgen.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

    $exe = 'dist\cycloidgen\cycloidgen.exe'
    if (-not (Test-Path $exe)) { throw "PyInstaller produced no $exe" }
    $reported = (& $exe --version).Trim()
    if ($reported -notmatch [regex]::Escape($version)) {
        throw "the bundle reports '$reported' but this release is $version"
    }
    Write-Host "  bundle reports: $reported"

    Write-Host '--- installer' -ForegroundColor Cyan
    $makensis = Get-Command makensis -ErrorAction SilentlyContinue
    if (-not $makensis) {
        $candidate = "${env:ProgramFiles(x86)}\NSIS\makensis.exe"
        if (Test-Path $candidate) { $makensis = $candidate }
        else { throw 'makensis not found. Install NSIS 3.x, or: winget install NSIS.NSIS' }
    }

    New-Item -ItemType Directory -Force -Path 'releases' | Out-Null
    # The script is UTF-8 and its Turkish strings depend on makensis
    # knowing that.  Without it makensis assumes the system ANSI codepage
    # and the welcome page reads "hoÅŸ geldiniz".  The file also carries
    # a BOM, which covers a hand-run; this covers a BOM that some tool has
    # helpfully removed.
    $args = @('/INPUTCHARSET', 'UTF8')
    if ($FastPack) { $args += '/DFASTPACK' }
    if ($SignCmd)  { $args += "/DSIGNCMD=$SignCmd" }
    $args += 'packaging\cycloidgen.nsi'
    & $makensis @args
    if ($LASTEXITCODE -ne 0) { throw 'makensis failed' }

    $setup = "releases\cycloidgen_v${version}_Setup.exe"
    if (-not (Test-Path $setup)) { throw "makensis produced no $setup" }
    $mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host ''
    Write-Host "$setup  ($mb MB)" -ForegroundColor Green
    if (-not $SignCmd) {
        Write-Host 'Unsigned: this will show a SmartScreen warning on first run.' -ForegroundColor Yellow
    }
}
finally {
    Pop-Location
}
