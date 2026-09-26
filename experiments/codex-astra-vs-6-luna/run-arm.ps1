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
$normalizedTask = [IO.File]::ReadAllText($taskPath).Replace("`r`n", "`n").Replace("`r", "`n")
$taskBytes = [Text.UTF8Encoding]::new($false).GetBytes($normalizedTask)
$taskHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskBytes)).ToLowerInvariant()
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
        [Parameter(Mandatory)][ValidateSet('high','max')][string]$Reasoning,
        [Parameter(Mandatory)][ValidateSet('read-only','workspace-write')][string]$Sandbox,
        [Parameter(Mandatory)][string]$Prompt,
        [string]$OutputSchema,
        [string]$ResumeThreadId
    )
    if (($deadline - (Get-Date)).TotalMilliseconds -le 0) { throw "Arm timeout reached before step: $Name" }
    $stepOutput = Join-Path $stepsRoot $Name
    New-Item -ItemType Directory -Path $stepOutput -Force | Out-Null
    $reasoningConfig = 'model_reasoning_effort="{0}"' -f $Reasoning
    $args = [Collections.Generic.List[string]]@('-a','never','--disable','multi_agent','exec')
    if ($ResumeThreadId) {
        $args.Add('resume'); $args.Add('--ignore-user-config')
        $args.Add('-m'); $args.Add($Model)
        $args.Add('-c'); $args.Add($reasoningConfig)
        $args.Add('--json'); $args.Add('-o'); $args.Add((Join-Path $stepOutput 'final.txt'))
        if ($OutputSchema) { $args.Add('--output-schema'); $args.Add($OutputSchema) }
        $args.Add($ResumeThreadId); $args.Add('-')
    } else {
        foreach ($arg in @(
            '--ignore-user-config','-C',$worktree,'-m',$Model,'-c',$reasoningConfig,
            '-s',$Sandbox,'--json','-o',(Join-Path $stepOutput 'final.txt')
        )) { $args.Add($arg) }
        if ($OutputSchema) { $args.Add('--output-schema'); $args.Add($OutputSchema) }
        $args.Add('-')
    }
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
    $eventsPath = Join-Path $stepOutput 'events.jsonl'
    [IO.File]::WriteAllText($eventsPath, $stdout, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $stepOutput 'stderr.txt'), $stderr, [Text.UTF8Encoding]::new($false))
    $threadId = $null
    foreach ($line in ($stdout -split "`r?`n")) {
        if (-not $line) { continue }
        try {
            $event = $line | ConvertFrom-Json
            if ($event.type -eq 'thread.started') { $threadId = [string]$event.thread_id }
        } catch { }
    }
    $stepEnded = Get-Date
    $stepMeta = [ordered]@{
        name = $Name; model = $Model; reasoning = $Reasoning; sandbox = $Sandbox
        thread_id = $threadId; resumed_from = if ($ResumeThreadId) { $ResumeThreadId } else { $null }
        started_at = $stepStarted.ToString('o'); ended_at = $stepEnded.ToString('o')
        elapsed_seconds = [math]::Round(($stepEnded - $stepStarted).TotalSeconds, 3)
        timed_out = $timedOut; exit_code = if ($timedOut) { 124 } else { $process.ExitCode }
    }
    $stepMeta | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stepOutput 'step.json') -Encoding utf8
    $completedSteps.Add([pscustomobject]$stepMeta)
    if ($stepMeta.exit_code -ne 0) { throw "Codex step $Name failed with exit code $($stepMeta.exit_code). See $stepOutput" }
    if (-not $threadId) { throw "Codex step $Name did not emit thread.started. See $eventsPath" }
    return [pscustomobject]@{
        final = Get-Content -Raw -LiteralPath (Join-Path $stepOutput 'final.txt')
        thread_id = $threadId
    }
}

function Get-Prompt([string]$Name) {
    Get-Content -Raw -LiteralPath (Join-Path $experimentRoot "prompts/$Name.md")
}

$failure = $null
$coordinatorAccepted = $null
try {
    if ($Arm -eq 'solo') {
        $prompt = "$(Get-Prompt 'solo')`n`n<experiment_task>`n$task`n</experiment_task>"
        [void](Invoke-CodexStep -Name 'astra-solo' -Model 'gpt-6-astra' -Reasoning 'high' -Sandbox 'workspace-write' -Prompt $prompt)
    } else {
        $planPrompt = "$(Get-Prompt 'coordinator-plan')`n`n<experiment_task>`n$task`n</experiment_task>"
        $planSchema = Join-Path $experimentRoot 'schemas/coordinator-plan.schema.json'
        $coordinator = Invoke-CodexStep -Name 'astra-coordinator-plan' -Model 'gpt-6-astra' -Reasoning 'high' -Sandbox 'read-only' -Prompt $planPrompt -OutputSchema $planSchema
        $plan = $coordinator.final | ConvertFrom-Json
        $assignments = @($plan.assignments | Sort-Object agent_index)
        if ($assignments.Count -ne 6 -or (($assignments.agent_index -join ',') -ne '1,2,3,4,5,6')) {
            throw 'Astra coordinator must return exactly one assignment for each Luna index 1 through 6.'
        }
        $handoffs = [Collections.Generic.List[string]]::new()
        foreach ($assignment in $assignments) {
            $index = [int]$assignment.agent_index
            $assignmentJson = $assignment | ConvertTo-Json -Depth 6
            $workerPrompt = "$(Get-Prompt 'luna-worker')`n`n<coordinator_strategy>`n$($plan.strategy)`n</coordinator_strategy>`n`n<your_assignment>`n$assignmentJson`n</your_assignment>`n`n<experiment_task>`n$task`n</experiment_task>"
            $worker = Invoke-CodexStep -Name ('luna-{0:d2}' -f $index) -Model 'gpt-6-luna' -Reasoning 'max' -Sandbox 'workspace-write' -Prompt $workerPrompt
            $handoffs.Add("<worker index=`"$index`">`n$($worker.final)`n</worker>")
        }
        $reviewPrompt = "$(Get-Prompt 'coordinator-review')`n`n<worker_handoffs>`n$($handoffs -join "`n`n")`n</worker_handoffs>`n`n<experiment_task>`n$task`n</experiment_task>"
        $reviewSchema = Join-Path $experimentRoot 'schemas/coordinator-review.schema.json'
        $review = Invoke-CodexStep -Name 'astra-coordinator-review' -Model 'gpt-6-astra' -Reasoning 'high' -Sandbox 'read-only' -Prompt $reviewPrompt -OutputSchema $reviewSchema -ResumeThreadId $coordinator.thread_id
        $reviewResult = $review.final | ConvertFrom-Json
        $coordinatorAccepted = [bool]$reviewResult.accepted
    }
} catch {
    $failure = $_
} finally {
    $ended = Get-Date
    $lunaSteps = @($completedSteps | Where-Object { $_.model -eq 'gpt-6-luna' -and $_.exit_code -eq 0 })
    $astraSteps = @($completedSteps | Where-Object { $_.model -eq 'gpt-6-astra' -and $_.exit_code -eq 0 })
    $lunaAgentCount = @($lunaSteps.thread_id | Sort-Object -Unique).Count
    $astraAgentCount = @($astraSteps.thread_id | Sort-Object -Unique).Count
    $meta = [ordered]@{
        arm = $Arm; started_at = $started.ToString('o'); ended_at = $ended.ToString('o')
        elapsed_seconds = [math]::Round(($ended - $started).TotalSeconds, 3)
        timeout_minutes = $TimeoutMinutes; failed = [bool]$failure
        exit_code = if ($failure) { 1 } else { 0 }
        start_commit = $manifest.base_commit; end_commit = (& git -C $worktree rev-parse HEAD).Trim()
        dirty = [bool](& git -C $worktree status --porcelain)
        astra_agents = $astraAgentCount; astra_turns_completed = $astraSteps.Count
        luna_agents = $lunaAgentCount; luna_turns_completed = $lunaSteps.Count
        coordinator_accepted = $coordinatorAccepted; steps = @($completedSteps)
    }
    $meta | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'run.json') -Encoding utf8
}
if ($failure) { throw $failure }
if ($Arm -eq 'multi' -and ($meta.astra_agents -ne 1 -or $meta.astra_turns_completed -ne 2)) { throw 'Collaborative arm must use one Astra coordinator for exactly two turns.' }
if ($Arm -eq 'multi' -and ($meta.luna_agents -ne 6 -or $meta.luna_turns_completed -ne 6)) { throw 'Collaborative arm must start exactly six Luna implementation agents.' }
if ($Arm -eq 'solo' -and ($meta.astra_agents -ne 1 -or $meta.luna_agents -ne 0)) { throw 'Solo arm must use one Astra agent and no Luna agents.' }
$meta | ConvertTo-Json -Depth 5
