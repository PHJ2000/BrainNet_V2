param(
    [Parameter(Mandatory)][string[]]$ContainerNames,
    [Parameter(Mandatory)][string]$OutputPath,
    [Parameter(Mandatory)][string]$CompletionPath,
    [int]$MaximumSeconds = 4000
)
$ErrorActionPreference = 'Stop'
$deadline = [DateTime]::UtcNow.AddSeconds($MaximumSeconds)
while ([DateTime]::UtcNow -lt $deadline -and -not (Test-Path -LiteralPath $CompletionPath)) {
    $samples = @(docker stats --no-stream --format '{{json .}}' @ContainerNames | ForEach-Object { $_ | ConvertFrom-Json })
    if ($LASTEXITCODE -ne 0) { throw 'docker stats failed' }
    @{ at = [DateTime]::UtcNow.ToString('o'); containers = $samples } |
        ConvertTo-Json -Depth 4 -Compress | Add-Content -LiteralPath $OutputPath -Encoding utf8
    Start-Sleep -Seconds 5
}
