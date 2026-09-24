# Окружение Презентатора для Windows: Python-зависимости и браузер для рендера.
#
#   powershell -ExecutionPolicy Bypass -File skills\slides\scripts\setup.ps1
#
# Ставит venv в %USERPROFILE%\.slides-agent\venv (путь меняется переменной
# SLIDES_AGENT_HOME). Повторный запуск безопасен.
$ErrorActionPreference = "Stop"

$HomeDir = if ($env:SLIDES_AGENT_HOME) { $env:SLIDES_AGENT_HOME } else { Join-Path $env:USERPROFILE ".slides-agent" }
$Venv = Join-Path $HomeDir "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$Pkgs = @("python-pptx", "pyyaml", "playwright", "pillow")

New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "[setup] uv найден — создаю окружение через uv"
    if (-not (Test-Path $Py)) { uv venv --python 3.12 $Venv }
    uv pip install --python $Py @Pkgs
} else {
    $Base = $null
    foreach ($cand in @("py -3.12", "py -3.11", "py -3.10", "python")) {
        try {
            $ok = Invoke-Expression "$cand -c `"import sys; print(sys.version_info >= (3, 10))`"" 2>$null
            if ($ok -eq "True") { $Base = $cand; break }
        } catch {}
    }
    if (-not $Base) {
        Write-Error "Нужен Python 3.10+ или uv: winget install --id=astral-sh.uv"
    }
    Write-Host "[setup] создаю окружение: $Base -m venv $Venv"
    if (-not (Test-Path $Py)) { Invoke-Expression "$Base -m venv `"$Venv`"" }
    & $Py -m pip install --upgrade pip | Out-Null
    & $Py -m pip install @Pkgs
}

Write-Host "[setup] ставлю браузер Chromium для рендера слайдов"
& $Py -m playwright install chromium

Write-Host ""
Write-Host "[ok] Готово. Python Презентатора: $Py"
