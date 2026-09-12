param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Set-Location -LiteralPath $repo
$root = Join-Path $PSScriptRoot 'results/performance-fix-2026-09-12'
$soakRoot = Join-Path $root 'soak'
$compose = Join-Path $repo 'deploy/local-validation.compose.yml'
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$docker = (Get-Command docker -ErrorAction Stop).Source
if ($CheckOnly) { Write-Output 'Docker/PowerShell paths resolved. No services started.'; exit 0 }
$lock = [IO.File]::Open((Join-Path $root 'runner.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
if ((Test-Path -LiteralPath (Join-Path $soakRoot 'completed')) -or
    (Test-Path -LiteralPath (Join-Path $soakRoot 'soak.json'))) {
    $lock.Dispose()
    throw 'A previous run exists. Archive its soak folder before starting a new run.'
}
New-Item -ItemType Directory -Path $soakRoot -Force | Out-Null
$completion = Join-Path $soakRoot 'completed'
$sampler = $null
$soakProcess = $null
$configuration = @{target_seconds=3600;websocket_clients=100;operations_per_second=5;
    raw_error_budget=0;database='brainnet_soak';background='Standalone runner, no parallel load or build';
    implementation_commit='2adbcc16d32e26e2b5f08bfe13ecea16c0f05994';
    backend_image='sha256:e7bc2472804ed0a3bab8db7ebc1fb0a3771a6648e6292c39852ed1170ce8890e';
    spring_image='sha256:6a9b27feb84e2cfd21559fe4c95436819bd50e0db20d3647a71912947ecc9731';
    started_at_utc=[DateTime]::UtcNow.ToString('o')}
$configuration | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $soakRoot 'config.json') -Encoding utf8
try {
    'STARTING: preparing the dedicated validation database and runtimes.' | Set-Content -LiteralPath (Join-Path $root 'STATUS.txt') -Encoding utf8
    foreach ($imageName in @('brainnet-validation-backend','brainnet-validation-spring')) {
        $actualImage = docker image inspect $imageName --format '{{.Id}}'
        $expectedImage = if ($imageName -like '*backend') { $configuration.backend_image } else { $configuration.spring_image }
        if ($LASTEXITCODE -ne 0 -or $actualImage -ne $expectedImage) { throw "Image changed: $imageName" }
    }
    docker compose -p brainnet-validation -f $compose up -d --wait --wait-timeout 90 db provider tools
    if ($LASTEXITCODE) { throw 'Infrastructure startup failed' }
    docker compose -p brainnet-validation -f $compose exec -T db createdb -U brainnet_test brainnet_soak
    if ($LASTEXITCODE) { throw 'Dedicated database creation failed' }
    docker compose -p brainnet-validation -f $compose --profile soak up -d soak-fastapi soak-spring
    if ($LASTEXITCODE) { throw 'Runtime startup failed' }
    Start-Sleep -Seconds 15

    $samplerArgs = @('-NoProfile','-NonInteractive','-File', (Join-Path $PSScriptRoot 'sample-resources.ps1'),
        '-ContainerNames','brainnet-validation-soak-fastapi-1,brainnet-validation-soak-spring-1,brainnet-validation-tools-1,brainnet-validation-provider-1,brainnet-validation-db-1',
        '-OutputPath',(Join-Path $soakRoot 'resources.jsonl'),'-CompletionPath',$completion,'-MaximumSeconds','4200')
    $sampler = Start-Process -FilePath $pwsh -ArgumentList $samplerArgs -WindowStyle Hidden -PassThru -WorkingDirectory $repo -RedirectStandardOutput (Join-Path $root 'sampler.stdout.log') -RedirectStandardError (Join-Path $root 'sampler.stderr.log')
    $soakArgs = @('compose','-p','brainnet-validation','-f',$compose,'exec','-T',
        '-e','POSTGRES_URL=postgresql://brainnet_test:brainnet_test@db:5432/brainnet_soak',
        '-e','DATABASE_URL=postgresql+asyncpg://brainnet_test:brainnet_test@db:5432/brainnet_soak',
        '-e','FASTAPI_BASE_URL=http://soak-fastapi:8000','-e','SPRING_BASE_URL=http://soak-spring:8080',
        '-e','SOAK_SECONDS=3600','-e','RESULTS_DIR=experiments/runtime-nodes/results/performance-fix-2026-09-12/soak',
        'tools','python','experiments/runtime-nodes/soak.py')
    $soakProcess = Start-Process -FilePath $docker -ArgumentList $soakArgs -WindowStyle Hidden -PassThru -WorkingDirectory $repo -RedirectStandardOutput (Join-Path $soakRoot 'execution.log') -RedirectStandardError (Join-Path $soakRoot 'execution.stderr.log')
    $null = $soakProcess.Handle
    $deadline = [Diagnostics.Stopwatch]::StartNew()
    while (-not $soakProcess.HasExited) {
        if ($deadline.Elapsed.TotalSeconds -gt 4200) { throw 'Soak exceeded the 70-minute process deadline' }
        if ($sampler.HasExited -and -not (Test-Path -LiteralPath $completion)) { throw 'Resource sampler ended early; see sampler.stderr.log' }
        try {
            $p = Get-Content -LiteralPath (Join-Path $soakRoot 'soak-progress.json') -Raw | ConvertFrom-Json
            @('RUNNING',"Measured minutes: $([math]::Round($p.elapsed_seconds/60,1)) / 60",
                "Completed operations: $($p.completed)","Errors so far: $($p.errors)",
                "Checked UTC: $([DateTime]::UtcNow.ToString('o'))",'Completion: aggregate, save report, clean up validation containers.') |
                Set-Content -LiteralPath (Join-Path $root 'STATUS.txt') -Encoding utf8
        } catch { } # The first sample or a file replacement may still be pending.
        Start-Sleep -Seconds 15
    }
    $soakProcess.WaitForExit()
    if ($soakProcess.ExitCode -ne 0) { throw "Soak process exited $($soakProcess.ExitCode); see soak/execution.stderr.log" }
} catch {
    $_.Exception.Message | Set-Content -LiteralPath (Join-Path $root 'runner-error.txt') -Encoding utf8
} finally {
    New-Item -ItemType File -Path $completion -Force | Out-Null
    if ($null -ne $sampler -and -not $sampler.HasExited) {
        if (-not $sampler.WaitForExit(15000)) { $sampler.Kill(); $sampler.WaitForExit() }
    }
    try { & (Join-Path $PSScriptRoot 'finish-validation.ps1') -MaximumWaitSeconds 1 }
    finally {
        if ($null -ne $soakProcess -and -not $soakProcess.HasExited) { $soakProcess.Kill(); $soakProcess.WaitForExit() }
        $lock.Dispose()
    }
}
$finalState = Get-Content -LiteralPath (Join-Path $root 'completion.json') -Raw | ConvertFrom-Json
if ($finalState.state -ne 'PASSED') { exit 1 }
