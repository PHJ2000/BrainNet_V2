param([long[]]$ProjectIds = @(), [switch]$AllRest)
$ErrorActionPreference = 'Stop'
if ($ProjectIds | Where-Object { $_ -le 0 }) { throw 'Project ids must be positive integers' }
$mapPath = Join-Path $PSScriptRoot 'routing/canary.map'
$original = [IO.File]::ReadAllText($mapPath)
$configuration = "# Generated project allowlist; empty means FastAPI rollback.`n"
if ($AllRest) {
    $configuration += '"~^.*:/projects/[0-9]+/(ws|invite)/?$" fastapi;' + "`n"
    $configuration += '"~^.*:/projects/join/?$" fastapi;' + "`n"
    $configuration += '"~^.*:/(auth|users|projects)(/|$)" spring;' + "`n"
} elseif ($ProjectIds.Count) {
    $ids = ($ProjectIds | Sort-Object -Unique) -join '|'
    $configuration += '"~^.*:/projects/(' + $ids + ')/nodes(/|$)" spring;' + "`n"
}
[IO.File]::WriteAllText($mapPath, $configuration, [Text.UTF8Encoding]::new($false))
$composePath = Join-Path $PSScriptRoot 'local-validation.compose.yml'
try {
    docker compose -f $composePath exec -T proxy nginx -t -c /etc/nginx/brainnet/nginx.conf
    if ($LASTEXITCODE -ne 0) { throw 'Proxy rejected the new routing configuration' }
    docker compose -f $composePath exec -T proxy nginx -s reload -c /etc/nginx/brainnet/nginx.conf
    if ($LASTEXITCODE -ne 0) { throw 'Proxy reload failed' }
} catch {
    [IO.File]::WriteAllText($mapPath, $original, [Text.UTF8Encoding]::new($false))
    throw
}
Write-Output ('Spring REST all: ' + $AllRest + '; node projects: ' + ($ProjectIds -join ', '))
