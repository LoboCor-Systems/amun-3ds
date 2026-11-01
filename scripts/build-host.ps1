[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")][string]$Configuration = "Debug",
    [string]$BuildDirectory = "build/host-debug"
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$target = Join-Path $repository $BuildDirectory
if (-not (Test-Path -LiteralPath (Join-Path $target "CMakeCache.txt"))) {
    & (Join-Path $PSScriptRoot "bootstrap-host.ps1") -BuildDirectory $BuildDirectory
}
cmake --build $target --config $Configuration --parallel
if ($LASTEXITCODE -ne 0) { throw "Host build failed" }

