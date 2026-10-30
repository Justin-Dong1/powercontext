$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "未找到 .venv。请先按 README「安装」一节创建虚拟环境并安装依赖。" -ForegroundColor Yellow
    exit 1
}
Set-Location $root
& $python (Join-Path $root "scripts\run.py") @args
