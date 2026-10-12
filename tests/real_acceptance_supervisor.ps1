Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$source = Get-Content -LiteralPath (Join-Path $root 'scripts/real_acceptance.ps1') -Raw
$repairCall = "& (Join-Path `$PSScriptRoot 'repair_real_acceptance.ps1') -FailureFile `$failurePath"
$insertion = 'New-Item -ItemType Directory -Path (Split-Path -Parent $statePath) -Force | Out-Null'
if (-not $source.Contains($repairCall) -or -not $source.Contains($insertion)) {
    throw 'Acceptance supervisor test cannot find its injection points'
}
$overrides = @'
# 外部サービスを使わず、初回だけ検証失敗を発生させる。
function Ensure-UiServer { }
$script:probeRuns = 0
function Invoke-Validation {
    $script:probeRuns++
    if ($script:probeRuns -eq 1) {
        $script:currentStage = 'probe/ui/register'
        throw 'synthetic validation failure'
    }
    Write-Output 'PROBE_VALIDATED'
}
$state['merged'] = $true
'@
$repairProbe = @'
$probeLock = [IO.File]::Open((Join-Path $root '.tmp/real_acceptance-supervisor-probe.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$probeLock.Dispose()
Write-Output 'PROBE_REPAIRED'
'@
$source = $source.Replace($insertion, "$overrides`n$insertion")
$source = $source.Replace($repairCall, $repairProbe)
$source = $source.Replace('real_acceptance-v2.lock', 'real_acceptance-supervisor-probe.lock')
$source = $source.Replace('real_acceptance_failure.json', 'supervisor_probe_failure.json')
$runner = Join-Path $root '.tmp/real_acceptance_supervisor_probe.ps1'
$singleFailureSource = $source
try {
    Set-Content -LiteralPath $runner -Value $source -Encoding utf8
    $output = @(& $runner 2>&1) | ForEach-Object { "$_" }
    $repairIndex = [array]::IndexOf($output, 'PROBE_REPAIRED')
    $validatedIndex = [array]::IndexOf($output, 'PROBE_VALIDATED')
    if ($repairIndex -lt 0 -or $validatedIndex -le $repairIndex) {
        throw "Acceptance did not resume after repair: $($output -join ' | ')"
    }
    Write-Output 'PASS validation -> repair -> validation (lock released)'
    $source = $source.Replace('if ($script:probeRuns -eq 1)', 'if ($true)')
    Set-Content -LiteralPath $runner -Value $source -Encoding utf8
    try {
        & $runner 2>&1 | Out-Null
        throw 'Acceptance did not enforce the repair limit'
    }
    catch {
        if ($_.Exception.Message -notlike 'Repair limit reached for probe/ui/register*') {
            throw
        }
    }
    Write-Output 'PASS fourth failure stops with a clear reason'

    $source = $singleFailureSource.Replace(
        "throw 'synthetic validation failure'",
        'throw ''FAIL probe translation id status=failed error={"code":"task_failed","message":"Embedding endpointがHTTP 500を返しました。","cause_type":"EmbeddingError","retryable":true} record=probe.json'''
    )
    $source = $source.Replace($repairProbe, "throw 'External failure incorrectly launched Codex'")
    $source = $source.Replace('Start-Sleep -Seconds $delaySeconds', "Write-Output 'PROBE_WAITED'")
    Set-Content -LiteralPath $runner -Value $source -Encoding utf8
    $output = @(& $runner 2>&1) | ForEach-Object { "$_" }
    if ($output -notcontains 'PROBE_WAITED' -or $output -notcontains 'PROBE_VALIDATED') {
        throw "Transient embedding failure did not retry validation: $($output -join ' | ')"
    }
    Write-Output 'PASS transient embedding failure retries without Codex'
    $source = $source.Replace('if ($script:probeRuns -eq 1)', 'if ($true)')
    Set-Content -LiteralPath $runner -Value $source -Encoding utf8
    try {
        & $runner 2>&1 | Out-Null
        throw 'Embedding endpoint retry limit was not enforced'
    }
    catch {
        if ($_.Exception.Message -notlike 'Embedding endpoint did not recover for probe/ui/register*') {
            throw
        }
    }
    Write-Output 'PASS fourth embedding failure stops with endpoint cause'
}
finally {
    Remove-Item -LiteralPath $runner, (Join-Path $root '.tmp/supervisor_probe_failure.json'), (Join-Path $root '.tmp/real_acceptance-supervisor-probe.lock') -ErrorAction SilentlyContinue
}
