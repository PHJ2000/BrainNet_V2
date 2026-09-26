param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][ValidateSet('solo','multi')][string]$Arm,
    [ValidateRange(5, 240)][int]$TimeoutMinutes = 60
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runRoot = Join-Path $repo ".tools/model-comparison/$RunId"
$manifestPath = Join-Path $runRoot 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Missing manifest: $manifestPath" }
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$record = $manifest.arms | Where-Object name -eq $Arm
if (-not $record) { throw "Arm not found in manifest: $Arm" }
$worktree = [string]$record.path
if ((& git -C $worktree rev-parse HEAD).Trim() -ne $manifest.base_commit) { throw "$Arm did not start at the recorded base commit." }
if (& git -C $worktree status --porcelain) { throw "$Arm worktree is not clean before execution." }
$experimentRoot = Join-Path $worktree 'experiments/codex-astra-vs-6-luna'
$taskPath = Join-Path $experimentRoot 'TASK.md'
$taskHash = (Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($taskHash -ne $manifest.task_sha256) { throw 'TASK.md no longer matches the prepared manifest.' }

$output = Join-Path $runRoot $Arm
$stepsRoot = Join-Path $output 'steps'
New-Item -ItemType Directory -Path $stepsRoot -Force | Out-Null
$task = Get-Content -Raw -LiteralPath $taskPath
$started = Get-Date
$deadline = $started.AddMinutes($TimeoutMinutes)
$completedSteps = [Collections.Generic.List[object]]::new()

function Invoke-CodexStep {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Model,
        [Parameter(Mandatory)][ValidateSet('read-only','workspace-write')][string]$Sandbox,
        [Parameter(Mandatory)][string]$Prompt
    )
    $remainingMs = [int64][math]::Floor(($deadline - (Get-Date)).TotalMilliseconds)
    if ($remainingMs -le 0) { throw "Arm timeout reached before step: $Name" }
    $stepOutput = Join-Path $stepsRoot $Name
    New-Item -ItemType Directory -Path $stepOutput -Force | Out-Null
    $args = [Collections.Generic.List[string]]@(
        '-a','never','--disable','multi_agent','exec','--ignore-user-config',
        '-C',$worktree,'-m',$Model,'-c','model_reasoning_effort="max"',
        '-s',$Sandbox,'--json','-o',(Join-Path $stepOutput 'final.txt'),'-'
    )
    $info = [Diagnostics.ProcessStartInfo]::new()
    $codexShim = (Get-Command codex.cmd -ErrorAction Stop).Source
    $codexDirectory = Split-Path $codexShim -Parent
    $bundledNode = Join-Path $codexDirectory 'node.exe'
    $info.FileName = if (Test-Path -LiteralPath $bundledNode) { $bundledNode } else { (Get-Command node.exe -ErrorAction Stop).Source }
    $info.WorkingDirectory = $worktree
    $info.UseShellExecute = $false
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    [void]$info.ArgumentList.Add((Join-Path $codexDirectory 'node_modules/@openai/codex/bin/codex.js'))
    foreach ($arg in $args) { [void]$info.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::new(); $process.StartInfo = $info
    $stepStarted = Get-Date
    if (-not $process.Start()) { throw "Could not start Codex step: $Name" }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.Write($Prompt); $process.StandardInput.Close()
    $completed = $false
    while (-not $completed -and (Get-Date) -lt $deadline) {
        $waitMs = [int][math]::Min(30000, [math]::Max(1, ($deadline - (Get-Date)).TotalMilliseconds))
        $completed = $process.WaitForExit($waitMs)
    }
    $timedOut = -not $completed
    if ($timedOut) { $process.Kill($true); $process.WaitForExit() }
    $stdout = $stdoutTask.GetAwaiter().GetResult(); $stderr = $stderrTask.GetAwaiter().GetResult()
    [IO.File]::WriteAllText((Join-Path $stepOutput 'events.jsonl'), $stdout, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $stepOutput 'stderr.txt'), $stderr, [Text.UTF8Encoding]::new($false))
    $stepEnded = Get-Date
    $stepMeta = [ordered]@{
        name = $Name; model = $Model; reasoning = 'max'; sandbox = $Sandbox
        started_at = $stepStarted.ToString('o'); ended_at = $stepEnded.ToString('o')
        elapsed_seconds = [math]::Round(($stepEnded - $stepStarted).TotalSeconds, 3)
        timed_out = $timedOut; exit_code = if ($timedOut) { 124 } else { $process.ExitCode }
    }
    $stepMeta | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stepOutput 'step.json') -Encoding utf8
    $completedSteps.Add([pscustomobject]$stepMeta)
    if ($stepMeta.exit_code -ne 0) { throw "Codex step $Name failed with exit code $($stepMeta.exit_code). See $stepOutput" }
    return Get-Content -Raw -LiteralPath (Join-Path $stepOutput 'final.txt')
}

function Get-Prompt([string]$Name) {
    Get-Content -Raw -LiteralPath (Join-Path $experimentRoot "prompts/$Name.md")
}

$failure = $null
try {
    if ($Arm -eq 'solo') {
        $prompt = "$(Get-Prompt 'solo')`n`n<experiment_task>`n$task`n</experiment_task>"
        [void](Invoke-CodexStep -Name 'astra-solo' -Model 'gpt-6-astra' -Sandbox 'workspace-write' -Prompt $prompt)
    } else {
        $reports = [ordered]@{}
        $architectPrompt = "$(Get-Prompt 'luna-architect')`n`n<experiment_task>`n$task`n</experiment_task>"
        $reports.architect = Invoke-CodexStep -Name 'luna-01-architect' -Model 'gpt-6-luna' -Sandbox 'read-only' -Prompt $architectPrompt
        foreach ($role in @('data','backend','frontend')) {
            $rolePrompt = "$(Get-Prompt "luna-$role")`n`n<architect_handoff>`n$($reports.architect)`n</architect_handoff>`n`n<experiment_task>`n$task`n</experiment_task>"
            $reports[$role] = Invoke-CodexStep -Name "luna-0$($reports.Count + 1)-$role" -Model 'gpt-6-luna' -Sandbox 'workspace-write' -Prompt $rolePrompt
        }
        foreach ($role in @('tests','security')) {
            $rolePrompt = "$(Get-Prompt "luna-$role")`n`n<experiment_task>`n$task`n</experiment_task>"
            $sandbox = if ($role -eq 'security') { 'read-only' } else { 'workspace-write' }
            $reports[$role] = Invoke-CodexStep -Name "luna-0$($reports.Count + 1)-$role" -Model 'gpt-6-luna' -Sandbox $sandbox -Prompt $rolePrompt
        }
        $handoffs = ($reports.GetEnumerator() | ForEach-Object { "<specialist name=`"$($_.Key)`">`n$($_.Value)`n</specialist>" }) -join "`n`n"
        $integratorPrompt = "$(Get-Prompt 'multi')`n`n<specialist_handoffs>`n$handoffs`n</specialist_handoffs>`n`n<experiment_task>`n$task`n</experiment_task>"
        [void](Invoke-CodexStep -Name 'astra-integrator' -Model 'gpt-6-astra' -Sandbox 'workspace-write' -Prompt $integratorPrompt)
    }
} catch {
    $failure = $_
} finally {
    $ended = Get-Date
    $lunaCompleted = @($completedSteps | Where-Object { $_.model -eq 'gpt-6-luna' -and $_.exit_code -eq 0 }).Count
    $meta = [ordered]@{
        arm = $Arm; started_at = $started.ToString('o'); ended_at = $ended.ToString('o')
        elapsed_seconds = [math]::Round(($ended - $started).TotalSeconds, 3)
        timeout_minutes = $TimeoutMinutes; failed = [bool]$failure
        exit_code = if ($failure) { 1 } else { 0 }
        start_commit = $manifest.base_commit; end_commit = (& git -C $worktree rev-parse HEAD).Trim()
        dirty = [bool](& git -C $worktree status --porcelain)
        luna_runs_completed = $lunaCompleted; steps = @($completedSteps)
    }
    $meta | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'run.json') -Encoding utf8
}
if ($failure) { throw $failure }
if ($Arm -eq 'multi' -and $meta.luna_runs_completed -ne 6) { throw "Expected six successful Luna runs, observed $($meta.luna_runs_completed). See $output" }
if ($Arm -eq 'solo' -and $meta.luna_runs_completed -ne 0) { throw "Solo arm unexpectedly ran Luna. See $output" }
$meta | ConvertTo-Json -Depth 5
