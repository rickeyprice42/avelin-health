# Run from PowerShell to create/update the desktop launcher.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$localDir = Join-Path $projectRoot '.local'
$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python -or $python -like '*WindowsApps*') {
    $python = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (-not $node) {
    $candidates = @(
        "$env:ProgramFiles\nodejs\node.exe",
        "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    )
    $node = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $python -or -not $node) { throw 'Python 3.12 and Node.js 24 are required.' }
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe was not found beside python.exe.' }
New-Item -ItemType Directory -Force -Path $localDir | Out-Null
@{ python = $python; node = $node } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $localDir 'launcher.json') -Encoding UTF8
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Avelin Health - Local.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$arguments = '"' + (Join-Path $PSScriptRoot 'launch_local.py') + '"'
if ((Test-Path -LiteralPath $shortcutPath) -and
    ($shortcut.TargetPath -ne $pythonw -or $shortcut.Arguments -ne $arguments)) {
    throw "An unrelated shortcut already exists: $shortcutPath"
}
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'Start Avelin Health locally, open the browser and view logs.'
$icon = Get-ChildItem -LiteralPath $projectRoot -Filter '*.ico' -File | Select-Object -First 1
if ($icon) { $shortcut.IconLocation = $icon.FullName + ',0' }
$shortcut.Save()
Write-Output "Created: $shortcutPath"
Write-Output "Python: $python"
Write-Output "Node: $node"
