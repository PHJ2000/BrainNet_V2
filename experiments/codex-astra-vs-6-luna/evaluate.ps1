param(
    [Parameter(Mandatory)][string]$RunId,
    [switch]$Full,
    [Nullable[double]]$SoloQualityScore,
    [Nullable[double]]$MultiQualityScore
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runRoot = Join-Path $repo ".tools/model-comparison/$RunId"
$manifest = Get-Content -Raw -LiteralPath (Join-Path $runRoot 'manifest.json') | ConvertFrom-Json
$pricingPath = Join-Path $runRoot 'api-pricing.json'
if ((Get-FileHash -LiteralPath $pricingPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.pricing_sha256) { throw 'API pricing snapshot hash mismatch.' }
$summary = @()
foreach ($arm in @('solo','multi')) {
    $record = $manifest.arms | Where-Object name -eq $arm
    $path = [string]$record.path
    $output = Join-Path $runRoot $arm
    $run = Get-Content -Raw -LiteralPath (Join-Path $output 'run.json') | ConvertFrom-Json
    $eventFiles = @(Get-ChildItem -LiteralPath (Join-Path $output 'steps') -Recurse -Filter 'events.jsonl' | Select-Object -ExpandProperty FullName)
    if (-not $eventFiles.Count) { throw "No event logs found for arm: $arm" }
    $costJson = & node (Join-Path $PSScriptRoot 'calculate-api-cost.mjs') (Join-Path $output 'run.json') $pricingPath
    if ($LASTEXITCODE -ne 0) { throw "API cost calculation failed for arm: $arm" }
    $costJson | Set-Content -LiteralPath (Join-Path $output 'api-cost.json') -Encoding utf8
    $cost = $costJson | ConvertFrom-Json
    $workingDiffCheck = & git -C $path diff --check 2>&1
    $workingDiffExit = $LASTEXITCODE
    $committedDiffCheck = & git -C $path diff --check "$($manifest.base_commit)...HEAD" 2>&1
    $committedDiffExit = $LASTEXITCODE
    $diffExit = if ($workingDiffExit -ne 0 -or $committedDiffExit -ne 0) { 1 } else { 0 }
    $statOutput = & git -C $path diff --shortstat $manifest.base_commit
    $stat = if ($null -eq $statOutput) { '' } else { ([string]$statOutput).Trim() }
    $files = @(& git -C $path diff --name-only $manifest.base_commit)
    $validationSeconds = $null; $validationExit = $null
    if ($Full) {
        $clock = [Diagnostics.Stopwatch]::StartNew()
        try {
            & (Join-Path $path 'deploy/validate-next.ps1') *> (Join-Path $output 'validation.log')
            $validationExit = 0
        } catch {
            $_ | Out-String | Add-Content -LiteralPath (Join-Path $output 'validation.log')
            $validationExit = 1
        } finally {
            $clock.Stop(); $validationSeconds = [math]::Round($clock.Elapsed.TotalSeconds, 3)
        }
    }
    $qualityScore = if ($arm -eq 'solo') { $SoloQualityScore } else { $MultiQualityScore }
    if ($null -ne $qualityScore -and ($qualityScore -lt 0 -or $qualityScore -gt 100)) { throw "Quality score must be between 0 and 100: $arm" }
    $costPerPoint = if ($null -ne $qualityScore -and $qualityScore -gt 0) { $cost.totals.standard_short_context_usd / $qualityScore } else { $null }
    $astraUsage = $cost.by_model.'gpt-6-astra'
    $lunaUsage = $cost.by_model.'gpt-6-luna'
    $summary += [pscustomobject]@{
        arm = $arm; elapsed_seconds = $run.elapsed_seconds; codex_exit = $run.exit_code
        input_tokens = $cost.totals.input_tokens; cached_input_tokens = $cost.totals.cached_input_tokens
        cache_write_input_tokens = $cost.totals.cache_write_input_tokens
        output_tokens = $cost.totals.output_tokens; reasoning_tokens = $cost.totals.reasoning_tokens
        astra_tokens = if ($astraUsage) { $astraUsage.input_tokens + $astraUsage.output_tokens } else { 0 }
        luna_tokens = if ($lunaUsage) { $lunaUsage.input_tokens + $lunaUsage.output_tokens } else { 0 }
        api_cost_standard_usd = $cost.totals.standard_short_context_usd
        api_cost_long_context_sensitivity_usd = $cost.totals.all_long_context_sensitivity_usd
        astra_api_cost_usd = if ($astraUsage) { $astraUsage.standard_short_context_usd } else { 0 }
        luna_api_cost_usd = if ($lunaUsage) { $lunaUsage.standard_short_context_usd } else { 0 }
        quality_score = $qualityScore; api_cost_per_quality_point_usd = $costPerPoint
        process_count = $eventFiles.Count; astra_turns_completed = $run.astra_turns_completed
        luna_agents = $run.luna_agents; coordinator_accepted = $run.coordinator_accepted
        changed_files = $files.Count; diff_stat = $stat; diff_check = $diffExit
        validation_exit = $validationExit; validation_seconds = $validationSeconds
    }
    if ($diffExit -ne 0) {
        @($workingDiffCheck) + @($committedDiffCheck) | Set-Content -LiteralPath (Join-Path $output 'diff-check.txt')
    }
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runRoot 'summary.json') -Encoding utf8
$summary | Format-Table -AutoSize
