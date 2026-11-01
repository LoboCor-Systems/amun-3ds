[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")][string]$Configuration = "Debug",
    [string]$BuildDirectory = "build/host-debug"
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
& (Join-Path $PSScriptRoot "build-host.ps1") -Configuration $Configuration -BuildDirectory $BuildDirectory

$target = Join-Path $repository $BuildDirectory
ctest --test-dir $target -C $Configuration --output-on-failure
if ($LASTEXITCODE -ne 0) { throw "C++ tests failed" }

Push-Location $repository
try {
    python -B -m unittest discover -v
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }
} finally {
    Pop-Location
}

