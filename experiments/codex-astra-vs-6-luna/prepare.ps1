param(
    [string]$BaseRef = 'HEAD',
    [string]$RunId = (Get-Date -Format 'yyyyMMdd-HHmmss')
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runRoot = Join-Path $repo ".tools/model-comparison/$RunId"
$worktrees = Join-Path $runRoot 'worktrees'
function Get-NormalizedTextSha256([string]$Path) {
    $normalized = [IO.File]::ReadAllText($Path).Replace("`r`n", "`n").Replace("`r", "`n")
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($normalized)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}
Push-Location $repo
try {
    if (& git status --porcelain) { throw 'Prepare from a clean worktree so both arms receive identical input.' }
    $baseCommit = (& git rev-parse --verify "$BaseRef^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $baseCommit) { throw "Cannot resolve base ref: $BaseRef" }
    if (Test-Path -LiteralPath $runRoot) { throw "Run already exists: $runRoot" }
    New-Item -ItemType Directory -Path $worktrees -Force | Out-Null
    $pricingSource = Join-Path $repo 'experiments/codex-astra-vs-6-luna/api-pricing.json'
    $pricingSnapshot = Join-Path $runRoot 'api-pricing.json'
    Copy-Item -LiteralPath $pricingSource -Destination $pricingSnapshot
    $arms = @(
        @{ name = 'solo'; branch = "experiment/$RunId-astra-solo" },
        @{ name = 'multi'; branch = "experiment/$RunId-astra-6-luna" }
    )
    foreach ($arm in $arms) {
        $path = Join-Path $worktrees $arm.name
        & git worktree add -b $arm.branch $path $baseCommit | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to create worktree: $($arm.name)" }
        $arm.path = $path
    }
    $manifest = [ordered]@{
        schema = 2
        run_id = $RunId
        created_at = (Get-Date).ToString('o')
        base_commit = $baseCommit
        task_sha256 = Get-NormalizedTextSha256 (Join-Path $repo 'experiments/codex-astra-vs-6-luna/TASK.md')
        root_model = 'gpt-6-astra'
        root_reasoning = 'high'
        subagent_model = 'gpt-6-luna'
        subagent_reasoning = 'max'
        subagent_count = 6
        collaboration_contract = 'astra_plans_and_reviews_luna_implements'
        pricing_snapshot = 'api-pricing.json@2026-09-26'
        pricing_sha256 = (Get-FileHash -LiteralPath $pricingSnapshot -Algorithm SHA256).Hash.ToLowerInvariant()
        arms = $arms
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runRoot 'manifest.json') -Encoding utf8
    Write-Output $RunId
} finally { Pop-Location }
