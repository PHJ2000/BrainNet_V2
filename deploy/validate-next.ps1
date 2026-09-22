param([switch]$SkipBuild, [switch]$KeepRunning, [switch]$MeasureLimits, [switch]$RuntimeOnly)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
# Deliberately fixed: tests reset this disposable DB, never brainnet-local.
$composeArgs = @('compose', '-p', 'brainnet-next-validation', '-f', (Join-Path $PSScriptRoot 'local-validation.compose.yml'))
$logDirectory = Join-Path $repo 'deploy/validation-logs'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$log = Join-Path $logDirectory ("brainnet-next-validation-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$npm = if ([Environment]::OSVersion.Platform -eq 'Win32NT') { 'npm.cmd' } else { 'npm' }
$oldToken = $env:JWT_TOKEN
function Compose([string[]]$Arguments) {
    & docker @composeArgs @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Validation command failed: $($Arguments[0])" }
}
function Wait-Ready {
    $deadline = (Get-Date).AddMinutes(4)
    do {
        try {
            $page = Invoke-WebRequest 'http://localhost:18080/login' -TimeoutSec 3
            $events = Invoke-RestMethod 'http://localhost:18080/health/events' -TimeoutSec 3
            if ($page.StatusCode -eq 200 -and $events.ready) { return }
        } catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw 'Validation frontend/API did not become ready in four minutes'
}
function Seed([switch]$Browser) {
    $arguments = @('exec', '-T', 'tools', 'python', 'spring/vertical-slice/contract_seed.py')
    if ($Browser) { $arguments += '--browser' }
    $env:JWT_TOKEN = & docker @composeArgs @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Disposable database seed failed' }
}
function Read-RecoveryState {
    $sql = @'
SELECT json_build_object('operations',(SELECT count(*) FROM node_operation),
'recovery_snapshots',(SELECT count(*) FROM node_operation WHERE "before" <> '{}'::jsonb OR "after" <> '{}'::jsonb),
'imports',(SELECT count(*) FROM project_import),
'operation_fingerprint',(SELECT md5(coalesce(string_agg(row_to_json(o)::text,',' ORDER BY sequence),'')) FROM node_operation o),
'import_fingerprint',(SELECT md5(coalesce(string_agg(row_to_json(i)::text,',' ORDER BY actor_id,request_key),'')) FROM project_import i));
'@
    $state = & docker @composeArgs exec -T db psql -U brainnet_test -d brainnet_test -At -c $sql
    if ($LASTEXITCODE -ne 0) { throw 'Recovery inventory failed' }
    return $state
}
Start-Transcript -LiteralPath $log | Out-Null
Push-Location $repo
try {
    if (-not $SkipBuild) { Compose -Arguments @('build', 'fastapi', 'spring') }
    Compose -Arguments @('up', '-d', '--wait', 'db', 'tools')
    if (-not $RuntimeOnly) {
        # Outbox workers must not race tests that inspect/reset the same test tables.
        Compose -Arguments @('stop', 'fastapi', 'fastapi-secondary', 'spring')
        Compose -Arguments @('exec', '-T', '-w', '/workspace/backend', 'tools', 'alembic', 'upgrade', 'head')
        Compose -Arguments @('exec', '-T', '-w', '/workspace/backend', 'tools', 'alembic', 'check')
        Compose -Arguments @('exec', '-T', '-e', 'RUN_POSTGRES_CONCURRENCY_TESTS=1', 'tools',
            'python', '-m', 'pytest', '-q', 'backend/tests')
    } else { Write-Output 'Backend tests skipped: resuming the runtime/browser checks only.' }
    Push-Location (Join-Path $repo 'frontend')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules/.bin/playwright')) {
            & $npm ci
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies could not be installed' }
        }
        & node node_modules/@playwright/test/cli.js install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed' }
        & $npm test
        if ($LASTEXITCODE -ne 0) { throw 'Frontend unit tests failed' }
        & $npm run lint
        if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed' }
    } finally { Pop-Location }
    Compose -Arguments @('up', '-d', '--force-recreate', 'fastapi', 'fastapi-secondary', 'provider', 'spring', 'frontend', 'proxy')
    Wait-Ready
    Seed
    Compose -Arguments @('exec', '-T', '-e', 'JWT_TOKEN', '-e', 'CONTRACT_PROVIDER_CONFIGURED=1', 'tools',
        'python', 'spring/vertical-slice/contract_probe.py')
    Compose -Arguments @('exec', '-T', '-e', 'JWT_TOKEN', 'tools', 'python', 'spring/vertical-slice/event_probe.py')
    Compose -Arguments @('exec', '-T', 'tools', 'python', 'backend/scripts/check_session_security.py')
    Seed -Browser
    if ($MeasureLimits) {
        Compose -Arguments @('exec', '-T', 'tools', 'python', 'backend/scripts/check_backup_limits.py')
    }
    Push-Location (Join-Path $repo 'frontend')
    try {
        & $npm run test:e2e
        if ($LASTEXITCODE -ne 0) { throw 'Browser tests failed' }
        $beforeRestart = Read-RecoveryState
        if (($beforeRestart | ConvertFrom-Json).recovery_snapshots -lt 1) { throw 'No recovery fixture to verify' }
        Compose -Arguments @('up', '-d', '--force-recreate', '--wait', 'db')
        Compose -Arguments @('up', '-d', '--force-recreate', 'fastapi', 'fastapi-secondary')
        Compose -Arguments @('restart', 'proxy')
        Wait-Ready
        $afterRestart = Read-RecoveryState
        if ($beforeRestart -ne $afterRestart) { throw 'History or import receipts changed across container recreation' }
        $afterRestart | Set-Content -LiteralPath 'test-results/persistent-history.json' -Encoding utf8
        & node scripts/check-backup-restart.mjs
        if ($LASTEXITCODE -ne 0) { throw 'Persistence and fresh login check failed' }
    } finally { Pop-Location }
    Write-Output 'Next version validation passed. Browser evidence: frontend/test-results/'
} catch {
    $diagnostic = & docker @composeArgs logs --no-color --tail 35 fastapi frontend 2>&1
    $diagnostic | ForEach-Object { "$_" -replace '(?i)(token=)[^&\s"'']+', '$1<redacted>' }
    throw
} finally {
    $env:JWT_TOKEN = $oldToken
    if (-not $KeepRunning) { Compose -Arguments @('down') }
    Pop-Location
    Stop-Transcript | Out-Null
    Write-Output "Validation log: $log"
}
