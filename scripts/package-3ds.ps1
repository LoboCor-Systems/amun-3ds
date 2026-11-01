[CmdletBinding()]
param(
    [string]$Version = "0.1.0",
    [string]$Output,
    [string[]]$Pack = @(),
    [Nullable[long]]$SourceDateEpoch,
    [switch]$NoZip,
    [switch]$Replace
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$arguments = @{
    Version = $Version
    ThreeGx = (Join-Path $repository "3ds/AMUN.3gx")
    Elf = (Join-Path $repository "3ds/AMUN.elf")
    MapFile = (Join-Path $repository "3ds/AMUN.map")
    Require3gx = $true
    Pack = $Pack
    NoZip = $NoZip
    Replace = $Replace
}
if ($Output) { $arguments.Output = $Output }
if ($null -ne $SourceDateEpoch) { $arguments.SourceDateEpoch = $SourceDateEpoch }
& (Join-Path $PSScriptRoot "package-release.ps1") @arguments
