param(
    [ValidateSet("gitee", "github", "all")]
    [string]$Source = "all"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = if ($env:STELLASORA_BUILD_PYTHON) {
    $env:STELLASORA_BUILD_PYTHON
} else {
    Join-Path $root ".venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Build Python not found: $python"
}

& $python -c "import PIL, PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Build Python must provide Pillow and PyInstaller."
}

& $python -m PyInstaller --noconfirm --clean StellaSoraUpdater.spec
if ($LASTEXITCODE -ne 0) { throw "Updater build failed." }

$targets = if ($Source -eq "all") { @("gitee", "github") } else { @($Source) }
foreach ($target in $targets) {
    $launcher = "launcher_$target.py"
    $output = Join-Path $root "release\$target"
    $work = Join-Path $root "build\$target"
    $spec = Join-Path $root "build\StellaSoraGachaTool-$target.spec"
    $assets = Join-Path $root "assets"
    New-Item -ItemType Directory -Path $output -Force | Out-Null

    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name StellaSoraGachaTool `
        --icon (Join-Path $assets "app_icon.ico") `
        --add-data "$assets;assets" `
        --distpath $output `
        --workpath $work `
        --specpath (Split-Path -Parent $spec) `
        $launcher
    if ($LASTEXITCODE -ne 0) { throw "Application build failed for $target." }

    Copy-Item -LiteralPath "dist\StellaSoraUpdater.exe" -Destination "$output\StellaSoraGachaTool\StellaSoraUpdater.exe" -Force
}
