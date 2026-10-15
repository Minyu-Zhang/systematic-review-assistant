param(
    [Parameter(Mandatory = $true)]
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envDir = Join-Path $projectRoot '.venv-review'
$envPython = Join-Path $envDir 'Scripts/python.exe'

if (Test-Path -LiteralPath $envDir) {
    & $envPython -c 'import sys; print(sys.version)'
    if ($LASTEXITCODE -ne 0) {
        throw 'Existing .venv-review is broken. Choose a working interpreter and preserve/rename that environment before retrying.'
    }
} else {
    & $Python -m venv $envDir --without-pip
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create project environment.' }
}

# The supplied Python must have pip. This also works with the bundled runtime,
# whose venv does not include ensurepip. No activation is necessary.
& $Python -m pip --disable-pip-version-check --python $envPython install -r (Join-Path $projectRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install the pinned dependencies.' }
Write-Output "Ready: $envPython"
