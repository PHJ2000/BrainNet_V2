param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateSet('random','solo-first','multi-first')][string]$Order = 'random',
    [ValidateRange(5, 240)][int]$TimeoutMinutes = 60
)
$ErrorActionPreference = 'Stop'
$sequence = switch ($Order) {
    'solo-first' { @('solo','multi') }
    'multi-first' { @('multi','solo') }
    default { if ((Get-Random -Minimum 0 -Maximum 2) -eq 0) { @('solo','multi') } else { @('multi','solo') } }
}
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runRoot = Join-Path $repo ".tools/model-comparison/$RunId"
$sequence | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'execution-order.json') -Encoding utf8
foreach ($arm in $sequence) {
    Write-Output "Starting $arm"
    & (Join-Path $PSScriptRoot 'run-arm.ps1') -RunId $RunId -Arm $arm -TimeoutMinutes $TimeoutMinutes
}
