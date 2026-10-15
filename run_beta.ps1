param(
    [ValidateSet('orbit','sky','journal')][string]$Style,
    [switch]$Local
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$betaPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $betaPython)) {
    throw '请先在项目根目录运行：python -m venv .venv，然后 .\.venv\Scripts\python.exe -m pip install -e .'
}
Push-Location $projectRoot
try {
    $betaArgs = @('-m','stellasora_toolkit.gui','--output',(Join-Path $projectRoot 'exports'))
    if ($Style) { $betaArgs += @('--beta',$Style) }
    if (-not $Local) { $betaArgs += '--demo' }
    & $betaPython @betaArgs
    exit $LASTEXITCODE
} finally { Pop-Location }
