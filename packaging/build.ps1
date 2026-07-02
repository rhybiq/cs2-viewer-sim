# Builds the CS2 Viewer Sim desktop .exe with PyInstaller, bundling ffmpeg.
#
# Usage (from repo root):
#   pip install pyinstaller
#   powershell -File packaging/build.ps1
#
# Optionally set $env:FFMPEG_EXE_PATH first if ffmpeg.exe isn't where this
# script expects (see $ffmpegCandidates below).

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not $env:FFMPEG_EXE_PATH) {
    $ffmpegCandidates = Get-ChildItem `
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*" `
        -Recurse -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue
    if ($ffmpegCandidates) {
        $env:FFMPEG_EXE_PATH = $ffmpegCandidates[0].FullName
        Write-Host "Using ffmpeg: $($env:FFMPEG_EXE_PATH)"
    } else {
        Write-Warning "No ffmpeg.exe found automatically -- loudness metric will fail in the built app unless FFMPEG_EXE_PATH is set."
    }
}

Push-Location $repoRoot
try {
    pyinstaller packaging/app.spec --noconfirm --distpath dist --workpath build
} finally {
    Pop-Location
}

Write-Host "`nBuilt: $repoRoot\dist\CS2ViewerSim.exe"
