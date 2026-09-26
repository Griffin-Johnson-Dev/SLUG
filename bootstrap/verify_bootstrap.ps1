param(
    [string]$CC = $(if ($env:CC) { $env:CC } else { 'clang-cl' }),
    [int]$GCInterval = $(if ($env:SLUG_GC_INTERVAL) { [int]$env:SLUG_GC_INTERVAL } else { 262144 })
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$B = Join-Path $Root 'build\bootstrap_verify'
if (Test-Path $B) { Remove-Item -Recurse -Force $B }
New-Item -ItemType Directory -Force -Path $B | Out-Null
$VersionExpected = (Get-Content -Raw VERSION).Trim()
$LangExpected = (Get-Content -Raw LANGUAGE_VERSION).Trim()

function Invoke-Checked([string[]]$Command) {
    $Exe=$Command[0]
    $Args=@($Command | Select-Object -Skip 1)
    & $Exe @Args
    if ($LASTEXITCODE -ne 0) { throw "command failed ($LASTEXITCODE): $($Command -join ' ')" }
}
function Compile-C([string]$Source,[string]$Output) {
    $Base = [IO.Path]::GetFileName($CC).ToLowerInvariant()
    if ($Base -in @('cl','cl.exe','clang-cl','clang-cl.exe')) {
        Invoke-Checked @($CC,'/nologo','/std:c11','/O2',$Source,"/Fe:$Output",'ws2_32.lib','shell32.lib','user32.lib','gdi32.lib','winmm.lib')
    } else {
        Invoke-Checked @($CC,$Source,'-std=c11','-O2','-o',$Output,'-lws2_32','-lshell32','-luser32','-lgdi32','-lwinmm')
    }
}
function Assert-EqualFile([string]$A,[string]$B) {
    $HA=(Get-FileHash -Algorithm SHA256 $A).Hash
    $HB=(Get-FileHash -Algorithm SHA256 $B).Hash
    if ($HA -ne $HB) { throw "fixed-point mismatch: $A != $B" }
}

$SeedC = Join-Path $Root 'bootstrap\slug_seed.c'
$Seed = Join-Path $B 'slug_seed.exe'
$Gen1C = Join-Path $B 'generation1.c'
$Gen1 = Join-Path $B 'slug_generation1.exe'
$Gen2C = Join-Path $B 'generation2.c'

Write-Host '[1/9] compile canonical seed'; Compile-C $SeedC $Seed
Write-Host '[2/9] verify seed identity'
if ((& $Seed --version).Trim() -ne $VersionExpected) { throw 'compiler version mismatch' }
if ((& $Seed --language-version).Trim() -ne $LangExpected) { throw 'language version mismatch' }
$env:SLUG_GC_INTERVAL="$GCInterval"
Write-Host '[3/9] seed checks maintained compiler root'; Invoke-Checked @($Seed,'check','compiler/stage2/app.slg')
Write-Host '[4/9] seed regenerates compiler C'; Invoke-Checked @($Seed,'emit-c','compiler/stage2/app.slg',$Gen1C)
Write-Host '[5/9] generation 1 equals canonical seed'; Assert-EqualFile $SeedC $Gen1C
Write-Host '[6/9] compile generation 1'; Compile-C $Gen1C $Gen1
Write-Host '[7/9] generation 1 checks maintained compiler root'; Invoke-Checked @($Gen1,'check','compiler/stage2/app.slg')
Write-Host '[8/9] generation 1 emits generation 2'; Invoke-Checked @($Gen1,'emit-c','compiler/stage2/app.slg',$Gen2C)
Write-Host '[9/9] generation 2 is byte-identical'; Assert-EqualFile $Gen1C $Gen2C
$Lines=@($SeedC,$Gen1C,$Gen2C) | ForEach-Object { "$(Get-FileHash -Algorithm SHA256 $_ | Select-Object -ExpandProperty Hash)  $_" }
$Lines | Set-Content -Encoding ascii (Join-Path $B 'fixed_point.sha256')
Write-Host 'SLUG BOOTSTRAP PASS'
