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
    }
    $astra = $catalog | Where-Object slug -eq 'gpt-6-astra'
    $luna = $catalog | Where-Object slug -eq 'gpt-6-luna'
    if ('high' -notin $astra.supported_reasoning_levels.effort) { throw 'GPT-6 Astra does not expose high reasoning.' }
    if ('max' -notin $luna.supported_reasoning_levels.effort) { throw 'GPT-6 Luna does not expose max reasoning.' }
    [pscustomobject]@{ codex = $version; login = ($login -join ' '); astra = 'high'; luna = 'max'; orchestration = 'Astra coordinator plus six Luna implementers' } |
        ConvertTo-Json
} finally { Pop-Location }
