[CmdletBinding()]
param([switch]$SelfCheck)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$samples = @('sample3', 'sample2', 'sample5', 'sample4')
$statePath = Join-Path $root '.tmp/real_acceptance_state.json'
$state = if (Test-Path -LiteralPath $statePath) {
    Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json -AsHashtable
} else { @{} }
$currentStage = 'startup'

function Save-State {
    # 同じディレクトリ内で置換し、途中終了による破損を避ける。
    $temporary = "$statePath.tmp"
    $state | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $statePath -Force
}

function Get-Record {
    param([string]$Stem, [string]$Id, [string]$Name)
    $path = Join-Path $root "outputs/$Stem/$Id/$Name.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)
}

function Wait-Record {
    param([string]$Stem, [string]$Id, [string]$RecordName)
    $path = Join-Path $root "outputs/$Stem/$Id/$RecordName.json"
    $deadline = (Get-Date).AddHours(48)
    while ((Get-Date) -lt $deadline) {
        $record = Get-Record $Stem $Id $RecordName
        if ($record) {
            if ($record.status -eq 'succeeded') {
                if ($RecordName -in @('translation', 'upgrade')) {
                    & uv run python scripts/audit_document.py (Join-Path $root "outputs/$Stem/$Id") $RecordName
                    if ($LASTEXITCODE -ne 0) { throw "AUDIT FAIL $Stem $RecordName $Id" }
                }
                Write-Output "PASS $currentStage $Id"
                return
            }
            if ($record.status -in @('failed', 'cancelled')) {
                throw "FAIL $Stem $RecordName $Id status=$($record.status) error=$($record.error | ConvertTo-Json -Compress) record=$path"
            }
        }
        Start-Sleep -Seconds 15
    }
    throw "TIMEOUT $Stem $RecordName $Id record=$path"
}

function Invoke-Logged {
    param([string[]]$Command)
    $log = Join-Path $root '.tmp/real_acceptance_command.log'
    $output = & $Command[0] $Command[1..($Command.Count - 1)] 2>&1 |
        Tee-Object -FilePath $log |
        ForEach-Object { Write-Host $_; $_ }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed (exit=$exitCode): $($Command -join ' ') log=$log tail=$((@($output) | Select-Object -Last 5) -join ' | ')"
    }
    return @($output)
}

function Run-Ui {
    param([string]$Operation, [string[]]$Files, [string]$Key)
    if ($state.ContainsKey($Key)) {
        $id = $state[$Key]
        $stem = $Key.Split('/')[0]
        $recordStem = if ($Operation -eq 'review') { 'document.ja' } else { $stem }
        $recordName = if ($Operation -eq 'register') { 'registration' } elseif ($Operation -eq 'translate') { 'translation' } else { $Operation }
        $record = Get-Record $recordStem $id $recordName
        if ($record -and $record.status -in @('failed', 'cancelled')) {
            [void](Invoke-Logged @('uv', 'run', 'python', 'scripts/real_ui_step.py', $Operation, '--resume', $id))
        }
        return $id
    }
    $output = Invoke-Logged (@('uv', 'run', 'python', 'scripts/real_ui_step.py', $Operation) + $Files)
    $line = @($output | Where-Object { $_ -match '^processing_id=' }) | Select-Object -Last 1
    if (-not $line) { throw "UI $Operation did not return an ID: $output" }
    $id = $line -replace '^processing_id=', ''
    $state[$Key] = $id
    Save-State
    return $id
}

function Run-Cli {
    param([string]$Operation, [string[]]$Arguments, [string]$Key)
    if ($state.ContainsKey($Key)) {
        $id = $state[$Key]
        $stem = $Key.Split('/')[0]
        $recordStem = if ($Operation -eq 'register') { "acceptance-$stem" } elseif ($Operation -eq 'review') { 'document.ja' } else { $stem }
        $recordName = if ($Operation -eq 'register') { 'registration' } elseif ($Operation -eq 'translate') { 'translation' } else { $Operation }
        $record = Get-Record $recordStem $id $recordName
        if ($record -and $record.status -in @('failed', 'cancelled', 'processing')) {
            [void](Invoke-Logged (@('uv', 'run', 'translate-ja', $Operation) + $Arguments + @('--resume', $id)))
        }
        return $id
    }
    $output = Invoke-Logged (@('uv', 'run', 'translate-ja', $Operation) + $Arguments)
    $line = @($output | Where-Object { $_ -match "^${Operation}_id: " }) | Select-Object -Last 1
    if (-not $line) {
        $label = if ($Operation -eq 'translate') { 'translation' } elseif ($Operation -eq 'register') { 'registration' } else { $Operation }
        $line = @($output | Where-Object { $_ -match "^${label}_id: " }) | Select-Object -Last 1
    }
    if (-not $line) { throw "CLI $Operation did not return an ID: $output" }
    $id = $line -replace '^\w+_id: ', ''
    $state[$Key] = $id
    Save-State
    return $id
}

function Convert-Docx {
    param([string]$Stem, [string]$Id)
    $docx = Join-Path $root "outputs/$Stem/$Id/publisher/docx/document.ja.docx"
    $pdf = Join-Path (Split-Path -Parent $docx) 'document.ja.pdf'
    if (Test-Path -LiteralPath $pdf -PathType Leaf) { return $pdf }
    $word = $null
    $document = $null
    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $document = $word.Documents.Open($docx, $false, $true)
        $document.ExportAsFixedFormat($pdf, 17)
    }
    finally {
        if ($document) {
            $document.Close($false)
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) | Out-Null
        }
        if ($word) {
            $word.Quit()
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) | Out-Null
        }
    }
    if (-not (Test-Path -LiteralPath $pdf -PathType Leaf)) { throw "Word did not create $pdf" }
    return $pdf
}

function Ensure-UiServer {
    try {
        Invoke-WebRequest 'http://127.0.0.1:8502' -Method Head -TimeoutSec 3 | Out-Null
        return
    }
    catch { }
    $log = Join-Path $root '.tmp/real_acceptance_streamlit.log'
    Start-Process -FilePath 'uv' -ArgumentList @('run', 'streamlit', 'run', './main.py', '--server.port', '8502', '--server.address', '127.0.0.1', '--server.headless', 'true') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log | Out-Null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        try {
            Invoke-WebRequest 'http://127.0.0.1:8502' -Method Head -TimeoutSec 3 | Out-Null
            return
        }
        catch { }
    }
    throw 'Streamlit did not start on 127.0.0.1:8502'
}

function Invoke-Validation {
foreach ($stem in $samples) {
    if ($state["$stem/done"]) { continue }
    $source = (Resolve-Path "inputs/$stem.pdf").Path
    $sourceV2 = (Resolve-Path ".tmp/versions/$stem.pdf").Path
    Write-Output "START $stem"
    $script:currentStage = "$stem/ui/register"
    $uiRegistration = Run-Ui 'register' @($source) "$stem/ui/register"
    Wait-Record $stem $uiRegistration 'registration'
    $script:currentStage = "$stem/cli/register"
    $cliRegistration = Run-Cli 'register' @($source, '--source-id', "acceptance-$stem") "$stem/cli/register"
    Wait-Record "acceptance-$stem" $cliRegistration 'registration'
    $script:currentStage = "$stem/ui/translate"
    $uiTranslation = Run-Ui 'translate' @($source) "$stem/ui/translate"
    Wait-Record $stem $uiTranslation 'translation'
    $script:currentStage = "$stem/cli/translate"
    $cliTranslation = Run-Cli 'translate' @($source, '--backend', 'llm') "$stem/cli/translate"
    Wait-Record $stem $cliTranslation 'translation'
    $uiPdf = Convert-Docx $stem $uiTranslation
    $cliPdf = Convert-Docx $stem $cliTranslation

    $script:currentStage = "$stem/ui/review"
    $uiReview = Run-Ui 'review' @($source, $uiPdf) "$stem/ui/review"
    Wait-Record 'document.ja' $uiReview 'review'
    $script:currentStage = "$stem/cli/review"
    $cliReview = Run-Cli 'review' @($source, $cliPdf) "$stem/cli/review"
    Wait-Record 'document.ja' $cliReview 'review'

    $script:currentStage = "$stem/ui/upgrade"
    $uiUpgrade = Run-Ui 'upgrade' @($source, $sourceV2, $uiPdf) "$stem/ui/upgrade"
    Wait-Record $stem $uiUpgrade 'upgrade'
    $script:currentStage = "$stem/cli/upgrade"
    $cliUpgrade = Run-Cli 'upgrade' @($source, $sourceV2, $cliPdf, '--backend', 'llm') "$stem/cli/upgrade"
    Wait-Record $stem $cliUpgrade 'upgrade'
    Write-Output "DONE $stem"
    $state["$stem/done"] = $true
    Save-State
}
}

New-Item -ItemType Directory -Path (Split-Path -Parent $statePath) -Force | Out-Null
if ($SelfCheck) {
    foreach ($stem in $samples) {
        foreach ($operation in @('register', 'translate', 'review', 'upgrade')) {
            foreach ($mode in @('ui', 'cli')) { Write-Output "$stem/$mode/$operation" }
        }
        foreach ($path in @("inputs/$stem.pdf", ".tmp/versions/$stem.pdf")) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing input: $path" }
        }
    }
    exit 0
}
$lock = [IO.File]::Open((Join-Path $root '.tmp/real_acceptance.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
Ensure-UiServer
try {
    Invoke-Validation
}
catch {
    if ($_.Exception -is [System.Management.Automation.PipelineStoppedException]) {
        exit 130
    }
    $failure = [ordered]@{
        stage = $currentStage
        error = $_.Exception.Message
        branch = (& git branch --show-current).Trim()
        head = (& git rev-parse HEAD).Trim()
        occurred_at = (Get-Date).ToUniversalTime().ToString('o')
    }
    $failurePath = Join-Path $root '.tmp/real_acceptance_failure.json'
    $failure | ConvertTo-Json | Set-Content -LiteralPath $failurePath -Encoding utf8
    $repair = Join-Path $PSScriptRoot 'repair_real_acceptance.ps1'
    $shell = (Get-Process -Id $PID).Path
    Start-Process -FilePath $shell -ArgumentList @('-NoProfile', '-File', $repair, '-FailureFile', $failurePath) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root '.tmp/real_acceptance_repair.log') -RedirectStandardError (Join-Path $root '.tmp/real_acceptance_repair.err.log') | Out-Null
    Write-Error "Validation failed at $currentStage; Codex repair started. $($_.Exception.Message)"
    exit 1
}

Write-Output 'ALL_REAL_ACCEPTANCE_PASSED'

if (-not $state['merged']) {
    $branch = (& git branch --show-current).Trim()
    if ($branch -ne 'feature/real-pdf-acceptance-20261009') { throw "Unexpected branch: $branch" }
    if (@(git status --porcelain).Count -gt 0) { throw 'Working tree is not clean' }
    & git pull --rebase origin main
    if ($LASTEXITCODE -ne 0) { throw 'Rebase on main failed' }
    & git push origin $branch
    if ($LASTEXITCODE -ne 0) { throw 'Feature push failed' }
    & gh pr checks 5 --watch
    if ($LASTEXITCODE -ne 0) { throw 'PR CI failed' }
    & gh pr ready 5
    if ($LASTEXITCODE -ne 0) { throw 'Could not mark PR ready' }
    & gh pr merge 5 --merge
    if ($LASTEXITCODE -ne 0) { throw 'PR merge failed' }
    & git switch main
    if ($LASTEXITCODE -ne 0) { throw 'Could not switch to main' }
    & git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not update local main' }
    & git push origin main
    if ($LASTEXITCODE -ne 0) { throw 'Main push failed' }
    $state['merged'] = $true
    Save-State
}
Write-Output 'ALL_REAL_ACCEPTANCE_PASSED_AND_MERGED'
