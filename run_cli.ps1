$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Get-Command python -ErrorAction SilentlyContinue) {
    $python = (Get-Command python).Source
} elseif (Test-Path -LiteralPath $bundledPython) {
    $python = $bundledPython
} else {
    throw "未找到 Python 3.10+，请先安装 Python 并加入 PATH。"
}

Push-Location $projectRoot
try {
    & $python -m stellasora_toolkit --output (Join-Path $projectRoot "exports") @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

