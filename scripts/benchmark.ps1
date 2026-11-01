[CmdletBinding()]
param([string]$BuildDirectory = "build/host-debug")

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
& (Join-Path $PSScriptRoot "build-host.ps1") -Configuration Release -BuildDirectory $BuildDirectory
$executable = Join-Path (Join-Path $repository $BuildDirectory) "Release/amun-bench.exe"
& $executable
if ($LASTEXITCODE -ne 0) { throw "Benchmark failed" }

