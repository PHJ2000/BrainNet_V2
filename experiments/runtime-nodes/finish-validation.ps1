param(
    [int]$MaximumWaitSeconds = 3300,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Set-Location -LiteralPath $repo
$resultRoot = Join-Path $PSScriptRoot 'results/performance-fix-2026-09-12'
$soakRoot = Join-Path $resultRoot 'soak'
$statusPath = Join-Path $resultRoot 'STATUS.txt'
$completionPath = Join-Path $soakRoot 'completed'
$compose = Join-Path $repo 'deploy/local-validation.compose.yml'
$reportPath = Join-Path $repo 'docs/PERFORMANCE_FIX_2026-09-12.md'
$names = @('brainnet-validation-soak-fastapi-1', 'brainnet-validation-soak-spring-1',
    'brainnet-validation-tools-1', 'brainnet-validation-provider-1', 'brainnet-validation-db-1')
foreach ($required in @($compose, $reportPath, (Join-Path $soakRoot 'config.json'),
    (Join-Path $PSScriptRoot 'summarize_fix.py'))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing input: $required" }
}
if ($MaximumWaitSeconds -lt 1) { throw 'MaximumWaitSeconds must be positive' }
if ($CheckOnly) { Write-Output 'Configuration and input paths verified; no mutation performed.'; exit 0 }

# A held file prevents a second finisher from cleaning up the same run.
$lock = [IO.File]::Open((Join-Path $resultRoot 'finisher.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$clock = [Diagnostics.Stopwatch]::StartNew()
$passed = $false
$failure = $null
$cleanupSucceeded = $false
$summary = $null
try {
    while (-not (Test-Path -LiteralPath $completionPath)) {
        if ($clock.Elapsed.TotalSeconds -gt $MaximumWaitSeconds) { throw 'Soak completion deadline exceeded' }
        try {
            $progress = Get-Content -LiteralPath (Join-Path $soakRoot 'soak-progress.json') -Raw | ConvertFrom-Json
        } catch {
            # The producer replaces this tiny file once a minute; retry a partial read.
            Start-Sleep -Seconds 2
            continue
        }
        @("RUNNING", "Checked UTC: $([DateTime]::UtcNow.ToString('o'))",
            "Measured minutes: $([math]::Round($progress.elapsed_seconds / 60, 1)) / 60",
            "Completed operations: $($progress.completed)", "Errors so far: $($progress.errors)",
            'On completion: aggregate results, update report, remove validation containers and volumes.') |
            Set-Content -LiteralPath $statusPath -Encoding utf8
        if (-not (Test-Path -LiteralPath $completionPath)) { Start-Sleep -Seconds 15 }
    }
    Start-Sleep -Seconds 8 # Let the resource sampler close its output before aggregation.
    if (Test-Path -LiteralPath (Join-Path $resultRoot 'runner-error.txt')) {
        throw (Get-Content -LiteralPath (Join-Path $resultRoot 'runner-error.txt') -Raw)
    }
    $health = foreach ($name in $names) {
        $raw = docker inspect $name
        if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $name" }
        $item = ($raw | ConvertFrom-Json)[0]
        [pscustomobject]@{name=$name; id=$item.Id; running=$item.State.Running;
            oom_killed=$item.State.OOMKilled; restart_count=$item.RestartCount}
    }
    $health | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $soakRoot 'runtime-health.json') -Encoding utf8
    docker compose -p brainnet-validation -f $compose exec -T tools python experiments/runtime-nodes/summarize_fix.py --require-complete *> (Join-Path $resultRoot 'aggregation.log')
    $aggregateExit = $LASTEXITCODE
    $summary = Get-Content -LiteralPath (Join-Path $resultRoot 'summary.json') -Raw | ConvertFrom-Json
    $passed = $aggregateExit -eq 0 -and $summary.all_gates_passed
    if (-not $passed) { throw 'Performance or strict-hour gates failed; see summary.json and soak/soak.json' }
} catch {
    $failure = $_.Exception.Message
} finally {
    try {
        docker compose -p brainnet-validation -f $compose --profile soak logs --no-color --tail 400 soak-fastapi soak-spring provider db *> (Join-Path $resultRoot 'runtime-final.log')
        New-Item -ItemType File -Path $completionPath -Force | Out-Null
        docker compose -p brainnet-validation -f $compose --profile soak down --volumes --timeout 15 *> (Join-Path $resultRoot 'cleanup.log')
        if ($LASTEXITCODE -ne 0) { throw 'Validation compose cleanup failed' }
        $remaining = @(docker ps -aq --filter label=com.docker.compose.project=brainnet-validation)
        if ($LASTEXITCODE -ne 0 -or $remaining.Count) { throw 'Validation containers remain after cleanup' }
        $cleanupSucceeded = $true
    } catch {
        $failure = @($failure, $_.Exception.Message) | Where-Object { $_ } | Join-String -Separator '; '
    }
    $state = if ($passed -and $cleanupSucceeded) { 'PASSED' } else { 'FAILED' }
    $detail = if ($passed) {
        $soak = $summary.strict_hour_soak
        "엄격한 연속 검증을 $($soak.duration_seconds)초 실행했다. 논리 작업 $($soak.completed_operations)개, WebSocket $($soak.websocket_clients)개, 전달 이벤트 $($soak.delivered_events)건을 대조했고 오류 0건, 접속자별 이벤트 누락 0건, 남은 노드 3개, 미발행 이벤트 0건이었다. 작업 p95는 $([math]::Round($soak.operation_p95_ms, 2))ms다. 재시도로 오류를 숨기지 않았으며 검증 중 컨테이너 OOM·재시작이 없었다. 이전 1시간 검증의 순간적인 실패 원인을 이번 결과만으로 특정하지는 않는다."
    } else {
        "자동 연속 검증 또는 후처리가 실패했다. 통과로 표시하지 않는다. 원인: $failure. 원본 JSON과 runtime-final.log를 확인한다."
    }
    try {
        $report = Get-Content -LiteralPath $reportPath -Raw
        $intro = if ($passed) { '**수정, 기능 검증, 60초 반복 부하 및 엄격한 1시간 연속 검증을 완료했다.** 이전 실패 기록은 삭제하지 않는다.' }
            else { '**수정과 기능 검증은 완료했다. 자동 연속 검증 결과는 아래 실패 기록을 참고한다.** 이전 실패 기록은 삭제하지 않는다.' }
        $report = $report.Replace('**수정과 기능 검증은 완료했다. 60초 반복 부하 및 1시간 연속 검증 결과는 측정 종료 후 확정한다.** 이전 실패 기록은 삭제하지 않는다.', $intro)
        $report = $report.Replace('엄격한 1시간 연속 검증은 진행 중이다.', $detail)
        Set-Content -LiteralPath $reportPath -Value $report -Encoding utf8 -NoNewline
    } catch { $state = 'FAILED'; $failure = "$failure; Report write failed: $($_.Exception.Message)" }
    @($state, "Finished UTC: $([DateTime]::UtcNow.ToString('o'))", "All verification gates passed: $passed",
        "Validation containers removed: $cleanupSucceeded", "Report: $reportPath", "Details: $detail", "Error: $failure") |
        Set-Content -LiteralPath $statusPath -Encoding utf8
    @{state=$state; gates_passed=$passed; cleanup_succeeded=$cleanupSucceeded; error=$failure;
        finished_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $resultRoot 'completion.json') -Encoding utf8
    $lock.Dispose()
}
if ($state -ne 'PASSED') { exit 1 }
