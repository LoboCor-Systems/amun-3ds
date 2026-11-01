[CmdletBinding()]
param(
    [string]$Version = "0.1.0",
    [string]$Output,
    [string]$ThreeGx,
    [string]$Elf,
    [string]$MapFile,
    [switch]$Require3gx,
    [string]$CtrpfLicense,
    [string[]]$Pack = @(),
    [Nullable[long]]$SourceDateEpoch,
    [switch]$NoZip,
    [switch]$Replace
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packageArguments = @("--version", $Version)
if ($Output) { $packageArguments += @("--output", $Output) }
if ($ThreeGx) { $packageArguments += @("--3gx", $ThreeGx) }
if ($Elf) { $packageArguments += @("--elf", $Elf) }
if ($MapFile) { $packageArguments += @("--map-file", $MapFile) }
if ($Require3gx) { $packageArguments += "--require-3gx" }
if ($CtrpfLicense) { $packageArguments += @("--ctrpf-license", $CtrpfLicense) }
foreach ($packEntry in $Pack) { $packageArguments += @("--pack", $packEntry) }
if ($null -ne $SourceDateEpoch) { $packageArguments += @("--source-date-epoch", $SourceDateEpoch.ToString()) }
if ($NoZip) { $packageArguments += "--no-zip" }
if ($Replace) { $packageArguments += "--replace" }
& python (Join-Path $repository "scripts/package-release.py") @packageArguments
if ($LASTEXITCODE -ne 0) { throw "Release packaging failed" }
