$ErrorActionPreference = 'Stop'
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Install the project environment first. See START-HERE.md.' }
& $pythonExe (Join-Path $PSScriptRoot 'server.py')
