param([switch]$NoBuild)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$envPath = Join-Path $repo '.env.local'
if (-not (Test-Path -LiteralPath $envPath)) {
    function New-LocalSecret {
        $bytes = [byte[]]::new(32)
        [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
        [Convert]::ToHexString($bytes).ToLowerInvariant()
    }
    @("JWT_SECRET=$(New-LocalSecret)", "BRAINNET_LOCAL_DB_PASSWORD=$(New-LocalSecret)") |
        Set-Content -LiteralPath $envPath -Encoding utf8
}
$composeArgs = @('compose', '-p', 'brainnet-local', '--env-file', $envPath,
    '-f', (Join-Path $PSScriptRoot 'local-app.compose.yml'), 'up', '-d', '--wait', '--wait-timeout', '180')
if (-not $NoBuild) { $composeArgs += '--build' }
docker @composeArgs
if ($LASTEXITCODE -ne 0) { throw 'Local startup failed. Check Docker and whether ports 3000/18000 are available.' }
Write-Output 'BrainNet: http://localhost:3000'
Write-Output 'API docs: http://localhost:18000/docs'
Write-Output 'Local data is retained in brainnet-local_local-db. This profile has no AI API key.'
