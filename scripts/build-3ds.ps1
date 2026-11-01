[CmdletBinding()]
param(
    [string]$DependenciesDirectory = "build/3ds-deps",
    [ValidateRange(1, 64)][int]$Jobs = 4
)

$ErrorActionPreference = "Stop"
if (-not $env:DEVKITARM) {
    throw "DEVKITARM is not set; use the pinned devkitPro environment documented in docs/3ds-toolchain.md"
}

$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dependencies = [System.IO.Path]::GetFullPath((Join-Path $repository $DependenciesDirectory))
cmake "-DAMUN_DEPS_DIR=$dependencies" -P (Join-Path $repository "cmake/3ds/fetch_pinned_dependencies.cmake")
if ($LASTEXITCODE -ne 0) { throw "Pinned dependency fetch/patch failed" }
cmake "-DAMUN_DEPS_DIR=$dependencies" "-DAMUN_BUILD_JOBS=$Jobs" -P (Join-Path $repository "cmake/3ds/build_pinned_dependencies.cmake")
if ($LASTEXITCODE -ne 0) { throw "Pinned dependency build failed" }
& make -C (Join-Path $repository "3ds") "AMUN_DEPS_DIR=$dependencies" -j $Jobs
if ($LASTEXITCODE -ne 0) { throw "3DS cross-build failed" }
$plugin = Join-Path $repository "3ds/AMUN.3gx"
cmake "-DAMUN_3GX=$plugin" -P (Join-Path $repository "cmake/3ds/verify_3gx.cmake")
if ($LASTEXITCODE -ne 0) { throw "3GX validation failed" }
Write-Host "Cross-compiled: $plugin"
Write-Host "Hardware tested: no (run docs/hardware-test.md)"
