$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
docker compose -p brainnet-local --env-file (Join-Path $repo '.env.local') -f (Join-Path $PSScriptRoot 'local-app.compose.yml') stop
if ($LASTEXITCODE -ne 0) { throw 'Local stop failed' }
