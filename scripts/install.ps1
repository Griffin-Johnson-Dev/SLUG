param(
    [string]$Prefix = "$env:LOCALAPPDATA\Programs\SLUG",
    [string]$CC = "clang-cl"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
python "$Root\tools\build_install_tree.py" --prefix "$Prefix" --cc "$CC"
Write-Host ""
Write-Host "SLUG installed under $Prefix"
Write-Host "Add $Prefix\bin to PATH if necessary."
Write-Host "Verify with: slug --version; slug --language-version"
