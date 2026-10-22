[CmdletBinding()]
param(
    [switch]$SelfCheck,
    [ValidateSet('sample', 'sample5', 'sample4', 'sample3', 'sample2', 'sample1')]
    [string]$StartAt = 'sample'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$samples = @('sample', 'sample5', 'sample4', 'sample3', 'sample2', 'sample1')
$validationStartIndex = [Array]::IndexOf($samples, $StartAt)
$validationSamples = @($samples | Select-Object -Skip $validationStartIndex)
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$statePath = Join-Path $root ".tmp/acceptance/$runId/state.json"
$state = @{ head = (& git rev-parse HEAD).Trim(); status = 'processing' }
$currentStage = 'startup'

function Save-State {
    param([hashtable]$Snapshot, [string]$Path)
    Set-Content -LiteralPath $Path -Value (ConvertTo-Json -InputObject $Snapshot -Depth 3) -Encoding utf8
}

function Get-Record {
    param([string]$Stem, [string]$Id, [string]$Name)
    $path = Join-Path $root "outputs/$Stem/$Id/state-$Name.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)
}

function Wait-Record {
    param([string]$Stem, [string]$Id, [string]$RecordName)
    $path = Join-Path $root "outputs/$Stem/$Id/state-$RecordName.json"
    while ($true) {
        $record = Get-Record $Stem $Id $RecordName
        if ($record) {
            if ($record.status -eq 'succeeded') {
                if ($RecordName -eq 'translation') {
                    & uv run python scripts/audit_document.py (Join-Path $root "outputs/$Stem/$Id")
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
}

function Invoke-Logged {
    param([string[]]$Command)
    $log = Join-Path (Split-Path -Parent $statePath) 'command.log'
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
    $output = Invoke-Logged (@('uv', 'run', 'python', 'scripts/real_ui_step.py', $Operation) + $Files)
    $line = @($output | Where-Object { $_ -match '^processing_id=' }) | Select-Object -Last 1
    if (-not $line) { throw "UI $Operation did not return an ID: $output" }
    $id = $line -replace '^processing_id=', ''
    $state[$Key] = $id
    Save-State -Snapshot $state -Path $statePath
    return $id
}

function Convert-Docx {
    param([string]$Stem, [string]$Id)
    $docx = Join-Path $root "outputs/$Stem/$Id/tasks/54-ooxml/document.ja.docx"
    $officeDocx = Join-Path (Split-Path -Parent $docx) 'document.ja-office.docx'
    $pdf = Join-Path (Split-Path -Parent $docx) 'document.ja-office.pdf'
    if (Test-Path -LiteralPath $pdf -PathType Leaf) { return $pdf }
    Invoke-Logged @('uv', 'run', 'python', 'scripts/prepare_office_docx.py', $docx, $officeDocx) | Out-Null
    $word = $null
    $document = $null
    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0
        $word.Options.UpdateFieldsAtPrint = $false
        $word.Options.UpdateLinksAtOpen = $false
        $document = $word.Documents.Open($officeDocx, $false, $true)
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
        Invoke-WebRequest 'http://127.0.0.1:8502' -UseBasicParsing -TimeoutSec 3 | Out-Null
        return
    }
    catch { }
    $log = Join-Path $root '.tmp/real_acceptance_streamlit.log'
    Start-Process -FilePath 'uv' -ArgumentList @('run', 'streamlit', 'run', './main.py', '--server.port', '8502', '--server.address', '127.0.0.1', '--server.headless', 'true') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log | Out-Null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        try {
            Invoke-WebRequest 'http://127.0.0.1:8502' -UseBasicParsing -TimeoutSec 3 | Out-Null
            return
        }
        catch { }
    }
    throw 'Streamlit did not start on 127.0.0.1:8502'
}

New-Item -ItemType Directory -Path (Split-Path -Parent $statePath) -Force | Out-Null
if ($SelfCheck) {
    foreach ($stem in $validationSamples) {
        if (-not (Test-Path -LiteralPath "inputs/$stem.pdf" -PathType Leaf)) { throw "Missing inputs/$stem.pdf" }
        foreach ($operation in @('register', 'translate', 'review', 'upgrade')) { Write-Output "$stem/$operation" }
    }
    exit 0
}
if (@(git status --porcelain).Count -gt 0) { throw 'Commit implementation changes before acceptance.' }
Save-State -Snapshot $state -Path $statePath
try {
    Ensure-UiServer
    & uv run python -c 'from scripts.real_ui_step import prepare_versions; prepare_versions()'
    if ($LASTEXITCODE -ne 0) { throw 'Upgrade fixture preparation failed' }
    # 各PDFの全工程を順番に実行し、修正後は新規IDで先頭からやり直す。
    foreach ($stem in $validationSamples) {
        $source = (Resolve-Path -LiteralPath "inputs/$stem.pdf").Path
        $sourceV2 = (Resolve-Path -LiteralPath ".tmp/versions/$stem.pdf").Path
        foreach ($operation in @('register', 'translate', 'review', 'upgrade')) {
            $script:currentStage = "$stem/$operation"
            $files = switch ($operation) {
                'register' { @($source) }
                'translate' { @($source) }
                'review' { @($source, $japanesePdf) }
                'upgrade' { @($source, $sourceV2, $japanesePdf) }
            }
            $identifier = Run-Ui $operation $files "$stem/$operation"
            $recordStem = if ($operation -eq 'review') { 'document.ja-office' } else { $stem }
            $recordName = switch ($operation) { 'register' { 'registration' }; 'translate' { 'translation' }; default { $operation } }
            Wait-Record $recordStem $identifier $recordName
            $image = Join-Path (Split-Path -Parent $statePath) "$stem-$operation.png"
            & uv run python scripts/real_ui_step.py $operation --inspect $identifier --screenshot $image
            if ($LASTEXITCODE -ne 0) { throw "UI result verification failed: $currentStage" }
            if ($operation -eq 'translate') { $japanesePdf = Convert-Docx $stem $identifier }
        }
        $state["$stem/done"] = $true
        Save-State -Snapshot $state -Path $statePath
    }
    $state['status'] = 'succeeded'
    Save-State -Snapshot $state -Path $statePath
    Write-Output "ALL_REAL_ACCEPTANCE_PASSED $statePath"
} catch {
    $state['status'] = 'failed'
    $state['stage'] = $currentStage
    $state['error'] = $_.Exception.Message
    Save-State -Snapshot $state -Path $statePath
    throw
}
