[CmdletBinding()]
param([string]$BuildDirectory = "build/host-debug")

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

foreach ($tool in @("cmake", "python")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Required host tool is missing from PATH: $tool"
    }
}

$pythonVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pythonVersion -lt [version]"3.11") {
    throw "AMUN requires Python 3.11 or newer; found $pythonVersion"
}

$target = Join-Path $repository $BuildDirectory
cmake -S $repository -B $target -G "Visual Studio 17 2022" -A x64
if ($LASTEXITCODE -ne 0) { throw "CMake configuration failed" }
Write-Host "Configured AMUN host build at $target"

