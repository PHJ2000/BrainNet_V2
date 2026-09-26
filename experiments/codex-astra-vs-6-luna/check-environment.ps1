$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Push-Location $repo
try {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw 'Codex CLI is not installed.' }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is not installed.' }
    $version = & codex --version
    if ($LASTEXITCODE -ne 0) { throw 'Codex CLI version check failed.' }
    $login = & codex login status 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Codex CLI is not logged in.' }
    $catalog = (& codex debug models | ConvertFrom-Json).models
    foreach ($slug in @('gpt-6-astra', 'gpt-6-luna')) {
        $model = $catalog | Where-Object slug -eq $slug
        if (-not $model) { throw "Model unavailable: $slug" }
        if ('max' -notin $model.supported_reasoning_levels.effort) { throw "Model does not expose max reasoning: $slug" }
    }
    [pscustomobject]@{ codex = $version; login = ($login -join ' '); astra = 'max'; luna = 'max'; orchestration = 'six pinned CLI sessions' } |
        ConvertTo-Json
} finally { Pop-Location }
