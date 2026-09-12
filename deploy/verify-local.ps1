# Run against the disposable stack after docker compose up --build -d.
$ErrorActionPreference = 'Stop'
$compose = Join-Path $PSScriptRoot 'local-validation.compose.yml'
function Run-Tool([string[]]$Arguments) {
    docker compose -f $compose exec -T -e JWT_TOKEN=$env:JWT_TOKEN tools @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Validation failed: $Arguments" }
}
function Seed([switch]$Browser) {
    $arguments = @('python', 'spring/vertical-slice/contract_seed.py')
    if ($Browser) { $arguments += '--browser' }
    $env:JWT_TOKEN = docker compose -f $compose exec -T tools @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Disposable database seed failed' }
}
try {
    & (Join-Path $PSScriptRoot 'set-canary.ps1')
    Seed
    Run-Tool -Arguments @('python', 'experiments/runtime-nodes/provider_probe.py')
    Seed
    docker compose -f $compose exec -T -e JWT_TOKEN=$env:JWT_TOKEN -e CONTRACT_PROVIDER_CONFIGURED=1 tools python spring/vertical-slice/contract_probe.py
    if ($LASTEXITCODE -ne 0) { throw 'Differential contract failed' }
    Run-Tool -Arguments @('python', 'spring/vertical-slice/event_probe.py')
    Seed
    Run-Tool -Arguments @('python', 'experiments/runtime-nodes/routing_probe.py', 'baseline')
    & (Join-Path $PSScriptRoot 'set-canary.ps1') -ProjectIds 1
    Run-Tool -Arguments @('python', 'experiments/runtime-nodes/routing_probe.py', 'canary')
    & (Join-Path $PSScriptRoot 'set-canary.ps1')
    Run-Tool -Arguments @('python', 'experiments/runtime-nodes/routing_probe.py', 'rollback')
    docker compose -f $compose exec -T prometheus promtool check rules /etc/prometheus/alerts.yml
    if ($LASTEXITCODE -ne 0) { throw 'Monitoring rule validation failed' }
    Seed -Browser
    Push-Location (Join-Path $PSScriptRoot '../frontend')
    try {
        npm run test:e2e
        if ($LASTEXITCODE -ne 0) { throw 'Browser end-to-end verification failed' }
    } finally { Pop-Location }
} finally {
    & (Join-Path $PSScriptRoot 'set-canary.ps1')
    Remove-Item Env:JWT_TOKEN -ErrorAction SilentlyContinue
}
