param(
    [Parameter(Mandatory)][string]$RunId,
    [switch]$Full
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runRoot = Join-Path $repo ".tools/model-comparison/$RunId"
$manifest = Get-Content -Raw -LiteralPath (Join-Path $runRoot 'manifest.json') | ConvertFrom-Json
$summary = @()
foreach ($arm in @('solo','multi')) {
    $record = $manifest.arms | Where-Object name -eq $arm
    $path = [string]$record.path
    $output = Join-Path $runRoot $arm
    $run = Get-Content -Raw -LiteralPath (Join-Path $output 'run.json') | ConvertFrom-Json
    $eventFiles = @(Get-ChildItem -LiteralPath (Join-Path $output 'steps') -Recurse -Filter 'events.jsonl' | Select-Object -ExpandProperty FullName)
    if (-not $eventFiles.Count) { throw "No event logs found for arm: $arm" }
    $usage = & node (Join-Path $PSScriptRoot 'summarize-events.mjs') @eventFiles | ConvertFrom-Json
    $workingDiffCheck = & git -C $path diff --check 2>&1
    $workingDiffExit = $LASTEXITCODE
    $committedDiffCheck = & git -C $path diff --check "$($manifest.base_commit)...HEAD" 2>&1
    $committedDiffExit = $LASTEXITCODE
    $diffExit = if ($workingDiffExit -ne 0 -or $committedDiffExit -ne 0) { 1 } else { 0 }
    $stat = (& git -C $path diff --shortstat $manifest.base_commit).Trim()
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
    $summary += [pscustomobject]@{
        arm = $arm; elapsed_seconds = $run.elapsed_seconds; codex_exit = $run.exit_code
        input_tokens = $usage.input_tokens; cached_input_tokens = $usage.cached_input_tokens
        output_tokens = $usage.output_tokens; reasoning_tokens = $usage.reasoning_tokens
        process_count = $usage.process_count; luna_runs_completed = $run.luna_runs_completed
        changed_files = $files.Count; diff_stat = $stat; diff_check = $diffExit
        validation_exit = $validationExit; validation_seconds = $validationSeconds
    }
    if ($diffExit -ne 0) {
        @($workingDiffCheck) + @($committedDiffCheck) | Set-Content -LiteralPath (Join-Path $output 'diff-check.txt')
    }
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runRoot 'summary.json') -Encoding utf8
$summary | Format-Table -AutoSize
