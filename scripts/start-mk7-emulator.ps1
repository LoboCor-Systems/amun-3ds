# Opens the already installed US research game; does not modify the real SD card.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$amunWorkspace = Split-Path -Parent $PSScriptRoot
$amunPortableRoot = [System.IO.Path]::GetFullPath((Join-Path $amunWorkspace 'build/emulators/azahar-2126.1.1/azahar-windows-msys2-2126.1.1'))
$amunExecutable = Join-Path $amunPortableRoot 'azahar.exe'
$amunInstalledGame = Join-Path $amunPortableRoot 'user/sdmc/Nintendo 3DS/00000000000000000000000000000000/00000000000000000000000000000000/title/00040000/00030800/content/00000000.app'

if (-not (Test-Path -LiteralPath $amunExecutable -PathType Leaf) -or
    -not (Test-Path -LiteralPath $amunInstalledGame -PathType Leaf)) {
    throw 'The portable emulator or installed US game is missing. See docs/MK7-EMULATOR-TESTING.md.'
}

$amunExisting = Get-Process -Name azahar -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $amunExecutable }
if ($amunExisting) {
    Write-Output ('The research emulator is already running (PID {0}).' -f ($amunExisting.Id -join ', '))
    return
}

# This launcher intentionally opens the interactive game window, not a helper.
$amunLaunched = Start-Process -FilePath $amunExecutable `
    -ArgumentList ('"' + $amunInstalledGame + '"') `
    -WorkingDirectory $amunPortableRoot -WindowStyle Normal -PassThru
Write-Output ('Opened Mario Kart 7 US research instance (PID {0}).' -f $amunLaunched.Id)
