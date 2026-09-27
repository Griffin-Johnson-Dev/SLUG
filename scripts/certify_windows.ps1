param(
    [string]$Prefix = "$env:TEMP\slug-certify-windows",
    [string]$InstallCC = 'clang-cl',
    [string]$FullCC = 'clang',
    [string]$Report = ''
)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
Set-Location $Root
$VersionExpected=(Get-Content -Raw (Join-Path $Root 'VERSION')).Trim()
$LanguageExpected=(Get-Content -Raw (Join-Path $Root 'LANGUAGE_VERSION')).Trim()
if (-not $Report) { $Report = Join-Path $Root ("build\WINDOWS_CERTIFICATION_SLUG-$VersionExpected.json") }

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
#
# LLVM on Windows commonly links AddressSanitizer dynamically.  The link can
# succeed while the resulting test executable later exits with STATUS_DLL_NOT_FOUND
# unless compiler-rt's DLL directory is on PATH.  Discover it from the active LLVM
# installation rather than assuming one version-specific layout.
$OriginalPath=$env:PATH
$RuntimeDirs = New-Object System.Collections.Generic.List[string]
try {
    $ClangCommand = Get-Command $FullCC -ErrorAction Stop
    $ClangExe = $ClangCommand.Source
    if (-not $ClangExe) { $ClangExe = $ClangCommand.Path }
    $ClangBin = Split-Path -Parent $ClangExe
    $LlvmRoot = Split-Path -Parent $ClangBin
    $ClangRuntimeDir = ((& $FullCC --print-runtime-dir 2>&1) | Out-String).Trim()
    $ClangResourceDir = ((& $FullCC --print-resource-dir 2>&1) | Out-String).Trim()
    $Roots = @($ClangRuntimeDir, (Join-Path $ClangResourceDir 'lib\windows'), (Join-Path $ClangResourceDir 'lib'), $ClangResourceDir, (Join-Path $LlvmRoot 'bin'), (Join-Path $LlvmRoot 'lib\clang'))
    $Seen = @{}
    foreach ($R in $Roots) {
        if (-not $R -or -not (Test-Path -LiteralPath $R)) { continue }
        try {
            $Dlls = @(Get-ChildItem -LiteralPath $R -Filter 'clang_rt*.dll' -File -ErrorAction SilentlyContinue)
            $Dlls += @(Get-ChildItem -LiteralPath $R -Filter 'clang_rt*.dll' -File -Recurse -ErrorAction SilentlyContinue)
            foreach ($Dll in $Dlls) {
                $Dir = $Dll.DirectoryName
                $Key = $Dir.ToLowerInvariant()
                if (-not $Seen.ContainsKey($Key)) { $Seen[$Key]=$true; $RuntimeDirs.Add($Dir) }
            }
        } catch { }
    }
    if ($RuntimeDirs.Count -gt 0) {
        $env:PATH = (($RuntimeDirs | Sort-Object -Unique) -join [IO.Path]::PathSeparator) + [IO.Path]::PathSeparator + $OriginalPath
        Write-Host 'Compiler-rt runtime directories added to PATH for sanitizer execution:'
        foreach ($Dir in ($RuntimeDirs | Sort-Object -Unique)) { Write-Host "  $Dir" }
    }
} catch {
    Write-Warning "Unable to pre-discover compiler-rt DLL directories: $($_.Exception.Message)"
}

$OldCC=$env:CC
try {
    $env:CC=$FullCC
    python tools/run_release_gate.py --slug $Slug --prefix $Prefix
    if ($LASTEXITCODE -ne 0) { throw 'Windows full release gate failed' }
} finally {
    $env:CC=$OldCC
    $env:PATH=$OriginalPath
}
$ReportDir=Split-Path -Parent $Report
if ($ReportDir) { New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null }
$InstallCCVersion = ((& $InstallCC --version 2>&1) | Out-String).Trim()
$FullCCVersion = ((& $FullCC --version 2>&1) | Out-String).Trim()
$Manifest = Join-Path $Root 'SOURCE_SHA256SUMS.txt'
$OsDescription=$null
try {
    $OsInfo=Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    if ($OsInfo -and $OsInfo.Caption) { $OsDescription=$OsInfo.Caption }
} catch { }
if (-not $OsDescription) { $OsDescription=[Environment]::OSVersion.VersionString }
$Architecture=$env:PROCESSOR_ARCHITEW6432
if (-not $Architecture) { $Architecture=$env:PROCESSOR_ARCHITECTURE }
if (-not $Architecture) { $Architecture='unknown' }

$Record = [ordered]@{
    schema = 2
    status = 'PASS'
    certified_at_utc = [DateTime]::UtcNow.ToString('o')
    compiler_version = $VersionExpected
    language_version = $LanguageExpected
    os = $OsDescription
    architecture = $Architecture
    powershell_version = $PSVersionTable.PSVersion.ToString()
    install_compiler = $InstallCC
    install_compiler_version = $InstallCCVersion
    full_gate_compiler = $FullCC
    full_gate_compiler_version = $FullCCVersion
    canonical_seed_sha256 = (Get-FileHash -Algorithm SHA256 (Join-Path $Root 'bootstrap\slug_seed.c')).Hash.ToLowerInvariant()
    source_manifest_sha256 = $(if (Test-Path $Manifest) { (Get-FileHash -Algorithm SHA256 $Manifest).Hash.ToLowerInvariant() } else { $null })
    installed_compiler_path = $Slug
    installed_compiler_sha256 = (Get-FileHash -Algorithm SHA256 $Slug).Hash.ToLowerInvariant()
    installed_devkit_sha256 = $(
        $Vsix = Join-Path $Prefix 'share\slug\1.0\tooling\vscode\slug-language.vsix'
        if (Test-Path $Vsix) { (Get-FileHash -Algorithm SHA256 $Vsix).Hash.ToLowerInvariant() } else { $null }
    )
}
$Record | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $Report
Write-Host "Windows certification record: $Report"
Write-Host 'WINDOWS CERTIFICATION PASS' 
