param(
    [Parameter(Mandatory)][string[]]$ContainerNames,
    [Parameter(Mandatory)][string]$OutputPath,
    [Parameter(Mandatory)][string]$CompletionPath,
    [int]$MaximumSeconds = 4000
)
$ErrorActionPreference = 'Stop'
$elapsed = [Diagnostics.Stopwatch]::StartNew()
while ($elapsed.Elapsed.TotalSeconds -lt $MaximumSeconds -and -not (Test-Path -LiteralPath $CompletionPath)) {
    $samples = @(docker stats --no-stream --format '{{json .}}' @ContainerNames | ForEach-Object { $_ | ConvertFrom-Json })
    if ($LASTEXITCODE -ne 0) { throw 'docker stats failed' }
    @{ at = [DateTime]::UtcNow.ToString('o'); elapsed_seconds = $elapsed.Elapsed.TotalSeconds; containers = $samples } |
        ConvertTo-Json -Depth 4 -Compress | Add-Content -LiteralPath $OutputPath -Encoding utf8
    Start-Sleep -Seconds 5
}
