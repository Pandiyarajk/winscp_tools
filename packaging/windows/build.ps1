# Build the Windows package: dist\sftp-pilot-<version>-windows-x64.zip
#
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
# Needs Python 3.11+ on PATH (or pass -Python). Everything is built in a private
# virtual environment under build\ and nothing is installed system-wide.
#
# Author: Pandiyaraj Karuppasamy
# Date: Oct-18-2026
param(
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$work = Join-Path $repo "build\windows"
$venv = Join-Path $work "venv"
$dist = Join-Path $work "pyinstaller"
$out  = Join-Path $repo "dist"

if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $work, $out | Out-Null

& $Python -m venv $venv
$py = Join-Path $venv "Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip
# Not editable: PyInstaller must see an installed package with its metadata.
& $py -m pip install --quiet "$repo[keyring]" pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$version = (& $py -c "import sftp_pilot; print(sftp_pilot.__version__)").Trim()
Write-Host "Building SFTP Pilot $version"

& $py -m PyInstaller --noconfirm --clean --distpath $dist --workpath (Join-Path $work "pyi-work") `
    (Join-Path $PSScriptRoot "sftp-pilot.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$folder = Join-Path $dist "sftp-pilot"
foreach ($file in "install.ps1", "uninstall.ps1", "register-task.ps1", "README.txt") {
    Copy-Item (Join-Path $PSScriptRoot $file) $folder
}
Copy-Item (Join-Path $repo "LICENSE") $folder
Copy-Item (Join-Path $repo "DISCLAIMER.md") $folder

$zip = Join-Path $out "sftp-pilot-$version-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $folder "*") -DestinationPath $zip -CompressionLevel Optimal

$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "Built $zip ($size MB)"
Write-Host "SHA256 $hash"
