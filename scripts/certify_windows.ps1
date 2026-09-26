param(
    [string]$Prefix = "$env:TEMP\slug-certify-windows",
    [string]$InstallCC = 'clang-cl',
    [string]$FullCC = 'clang',
    [string]$Report = ''
)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Report) { $Report = Join-Path $Root 'build\WINDOWS_CERTIFICATION.json' }

python tools/release_metadata.py
if ($LASTEXITCODE -ne 0) { throw 'release metadata verification failed' }
python tests/run_v1_install_command_shape.py
if ($LASTEXITCODE -ne 0) { throw 'install command-shape verification failed' }

if (-not (Get-Command $InstallCC -ErrorAction SilentlyContinue)) { throw "missing install compiler: $InstallCC" }
if (-not (Get-Command $FullCC -ErrorAction SilentlyContinue)) { throw "missing full-gate compiler: $FullCC" }
if (Test-Path $Prefix) { Remove-Item -Recurse -Force $Prefix }
python tools/build_install_tree.py --prefix $Prefix --cc $InstallCC
if ($LASTEXITCODE -ne 0) { throw 'Windows install build failed' }
$Slug=Join-Path $Prefix 'bin\slug.exe'

# Prove the exact canonical seed self-hosts under the MSVC-style driver too.
& "$Root\bootstrap\verify_bootstrap.ps1" -CC $InstallCC
if ($LASTEXITCODE -ne 0) { throw 'Windows clang-cl/MSVC-style bootstrap convergence failed' }

# The full conformance/hardening gate uses the LLVM/GNU-style driver so ASan/UBSan
# and the existing differential build harness can use their normal flags.
$OldCC=$env:CC
try {
    $env:CC=$FullCC
    python tools/run_release_gate.py --slug $Slug --prefix $Prefix
    if ($LASTEXITCODE -ne 0) { throw 'Windows full release gate failed' }
} finally {
    $env:CC=$OldCC
}
$ReportDir=Split-Path -Parent $Report
if ($ReportDir) { New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null }
$InstallCCVersion = ((& $InstallCC --version 2>&1) | Out-String).Trim()
$FullCCVersion = ((& $FullCC --version 2>&1) | Out-String).Trim()
$Manifest = Join-Path $Root 'SOURCE_SHA256SUMS.txt'
$Record = [ordered]@{
    schema = 1
    status = 'PASS'
    certified_at_utc = [DateTime]::UtcNow.ToString('o')
    compiler_version = (Get-Content -Raw (Join-Path $Root 'VERSION')).Trim()
    language_version = (Get-Content -Raw (Join-Path $Root 'LANGUAGE_VERSION')).Trim()
    os = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
    architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    install_compiler = $InstallCC
    install_compiler_version = $InstallCCVersion
    full_gate_compiler = $FullCC
    full_gate_compiler_version = $FullCCVersion
    canonical_seed_sha256 = (Get-FileHash -Algorithm SHA256 (Join-Path $Root 'bootstrap\slug_seed.c')).Hash.ToLowerInvariant()
    source_manifest_sha256 = $(if (Test-Path $Manifest) { (Get-FileHash -Algorithm SHA256 $Manifest).Hash.ToLowerInvariant() } else { $null })
}
$Record | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $Report
Write-Host "Windows certification record: $Report"
Write-Host 'WINDOWS CERTIFICATION PASS' 
