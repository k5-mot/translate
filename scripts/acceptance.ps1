[CmdletBinding()]
param(
    [ValidateSet("cli", "ui", "all")]
    [string]$Mode = "all",
    [string[]]$PdfPaths = @(
        "inputs/sample.pdf",
        "inputs/sample3.pdf",
        "inputs/sample2.pdf"
    ),
    [switch]$IncludeLarge,
    [ValidateSet("llm", "libretranslate")]
    [string]$Backend = "llm",
    [switch]$AutoRemediate,
    [ValidateRange(0, 3)]
    [int]$MaxRepairAttempts = 1
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repository = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$remediateScript = Join-Path $PSScriptRoot "codex-remediate.ps1"
$diagnosticsRoot = Join-Path $repository ".diagnostics"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
Set-Location -LiteralPath $repository

function Get-SafeLabel {
    param([string]$Value)

    return ($Value -replace "[^A-Za-z0-9._-]", "-")
}

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Value,
        [string]$EmptyJson = "[]"
    )

    $json = if ($null -eq $Value) {
        $EmptyJson
    }
    elseif ($Value -is [System.Array] -and $Value.Count -eq 0) {
        $EmptyJson
    }
    else {
        $Value | ConvertTo-Json -Depth 12
    }
    $json | Set-Content -LiteralPath $Path -Encoding utf8
}

function New-DiagnosticsBundle {
    param(
        [string]$Label,
        [string]$Target,
        [string[]]$Arguments,
        [string[]]$InputPaths
    )

    $safeLabel = Get-SafeLabel -Value $Label
    $base = Join-Path $diagnosticsRoot "$timestamp-$safeLabel"
    $path = $base
    $suffix = 1
    while (Test-Path -LiteralPath $path) {
        $path = "$base-$suffix"
        $suffix++
    }
    New-Item -ItemType Directory -Path $path -Force | Out-Null
    $command = if ($Target -eq "cli") {
        "uv run translate-ja $($Arguments -join ' ')"
    }
    else {
        "uv run pytest tests/e2e/test_ui.py -q"
    }
    $command | Set-Content -LiteralPath (Join-Path $path "command.txt") -Encoding utf8
    return (Resolve-Path -LiteralPath $path).Path
}

function Get-GitSnapshot {
    param([string]$Path)

    @(
        "## status"
        (& git -C $repository status --short --branch 2>&1)
        ""
        "## recent commits"
        (& git -C $repository log --oneline --decorate -10 2>&1)
        ""
        "## diff stat"
        (& git -C $repository diff --stat 2>&1)
    ) | Set-Content -LiteralPath (Join-Path $Path "git.txt") -Encoding utf8
}

function Get-EnvironmentSnapshot {
    param([string]$Path)

    $values = @(
        "powershell=$($PSVersionTable.PSVersion)"
        "os=$([Environment]::OSVersion.VersionString)"
        "uv=$((& uv --version 2>&1) -join ' ')"
        "python=$((& uv run python --version 2>&1) -join ' ')"
    )
    if (Get-Command pandoc -ErrorAction SilentlyContinue) {
        $values += "pandoc=$((& pandoc --version 2>&1 | Select-Object -First 1) -join ' ')"
    }
    $envPath = Join-Path $repository ".env"
    if (Test-Path -LiteralPath $envPath) {
        $values += ""
        $values += "## .env keys (values omitted)"
        $values += Get-Content -LiteralPath $envPath | ForEach-Object {
            if ($_ -match '^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)$') {
                $state = if ([string]::IsNullOrWhiteSpace($Matches[2].Trim('"'))) {
                    "empty"
                }
                else {
                    "set"
                }
                "$($Matches[1])=$state"
            }
        }
    }
    $values | Set-Content -LiteralPath (Join-Path $Path "environment.txt") -Encoding utf8
}

function Get-InputSnapshot {
    param(
        [string]$Path,
        [string[]]$InputPaths
    )

    $items = foreach ($inputPath in @($InputPaths)) {
        if (-not $inputPath -or -not (Test-Path -LiteralPath $inputPath -PathType Leaf)) {
            continue
        }
        $resolved = (Resolve-Path -LiteralPath $inputPath).Path
        $file = Get-Item -LiteralPath $resolved
        [ordered]@{
            path = [IO.Path]::GetRelativePath($repository, $resolved)
            size_bytes = $file.Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolved).Hash.ToLowerInvariant()
            modified_at = $file.LastWriteTimeUtc.ToString("o")
        }
    }
    Write-JsonFile -Path (Join-Path $Path "inputs.json") -Value @($items)
}

function Get-RecordSnapshot {
    param([string]$Path)

    $recordNames = @("translation.json", "review.json", "registration.json", "upgrade.json")
    $items = foreach ($recordPath in @(Get-ChildItem (Join-Path $repository "outputs") -Recurse -File -ErrorAction SilentlyContinue)) {
        if ($recordPath.Name -notin $recordNames) {
            continue
        }
        try {
            $record = Get-Content -LiteralPath $recordPath.FullName -Raw | ConvertFrom-Json
            $tasks = if ($record.PSObject.Properties.Name -contains "tasks") {
                @($record.tasks | ForEach-Object {
                    [ordered]@{
                        task = $_.task
                        status = $_.status
                        error = $_.error
                    }
                })
            }
            else {
                @()
            }
            [ordered]@{
                path = [IO.Path]::GetRelativePath($repository, $recordPath.FullName)
                status = $record.status
                updated_at = $record.updated_at
                error = $record.error
                tasks = $tasks
            }
        }
        catch {
            [ordered]@{
                path = [IO.Path]::GetRelativePath($repository, $recordPath.FullName)
                parse_error = $_.Exception.Message
            }
        }
    }
    Write-JsonFile -Path (Join-Path $Path "processing-records.json") -Value @($items)
}

function Get-LlmSnapshot {
    param([string]$Path)

    $calls = foreach ($callPath in @(Get-ChildItem (Join-Path $repository "outputs") -Recurse -File -Filter "call.json" -ErrorAction SilentlyContinue)) {
        try {
            $call = Get-Content -LiteralPath $callPath.FullName -Raw | ConvertFrom-Json
            [ordered]@{
                path = [IO.Path]::GetRelativePath($repository, $callPath.FullName)
                call_id = $call.call_id
                task = $call.task
                status = $call.status
                attempts = $call.attempts
                target_count = @($call.target_ids).Count
                child_call_ids = @($call.child_call_ids)
                input_tokens = $call.input_tokens
                output_tokens = $call.output_tokens
                updated_at = $call.updated_at
                error = $call.error
            }
        }
        catch {
            [ordered]@{
                path = [IO.Path]::GetRelativePath($repository, $callPath.FullName)
                status = "parse_error"
                error = $_.Exception.Message
            }
        }
    }
    $summary = @($calls | Group-Object task, status | ForEach-Object {
        [ordered]@{
            task_status = $_.Name
            count = $_.Count
        }
    })
    Write-JsonFile -Path (Join-Path $Path "llm-calls.json") -Value ([ordered]@{
            summary = $summary
            incomplete_or_failed = @($calls | Where-Object {
                    $_.status -notin @("succeeded", "split")
                })
        }) -EmptyJson "{}"
}

function Get-TaskDiagnostics {
    param([string]$Path)

    $destinationRoot = Join-Path $Path "task-diagnostics"
    foreach ($source in @(Get-ChildItem (Join-Path $repository "outputs") -Recurse -File -Filter "task-*.json" -ErrorAction SilentlyContinue)) {
        $relative = [IO.Path]::GetRelativePath((Join-Path $repository "outputs"), $source.FullName)
        $destination = Join-Path $destinationRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source.FullName -Destination $destination -Force
    }
}

function Complete-Diagnostics {
    param(
        [string]$Path,
        [string]$Target,
        [int]$ExitCode,
        [string[]]$InputPaths
    )

    @(
        "generated_at=$((Get-Date).ToUniversalTime().ToString('o'))"
        "target=$Target"
        "exit_code=$ExitCode"
        "repository=$repository"
    ) | Set-Content -LiteralPath (Join-Path $Path "summary.txt") -Encoding utf8
    Get-GitSnapshot -Path $Path
    Get-EnvironmentSnapshot -Path $Path
    Get-InputSnapshot -Path $Path -InputPaths $InputPaths
    Get-RecordSnapshot -Path $Path
    Get-LlmSnapshot -Path $Path
    Get-TaskDiagnostics -Path $Path
    $archive = "$Path.zip"
    Compress-Archive -Path (Join-Path $Path "*") -DestinationPath $archive -Force
    Write-Host "diagnostics: $archive"
    return $archive
}

function Invoke-CommandWithDiagnostics {
    param(
        [string]$Label,
        [ValidateSet("cli", "ui")]
        [string]$Target,
        [string[]]$Arguments,
        [string[]]$InputPaths
    )

    $bundle = New-DiagnosticsBundle -Label $Label -Target $Target -Arguments $Arguments -InputPaths $InputPaths
    $consolePath = Join-Path $bundle "console.log"
    if ($Target -eq "cli") {
        & uv run translate-ja @Arguments 2>&1 |
            Tee-Object -LiteralPath $consolePath |
            Out-Host
    }
    else {
        & uv run pytest tests/e2e/test_ui.py -q 2>&1 |
            Tee-Object -LiteralPath $consolePath |
            Out-Host
    }
    $exitCode = $LASTEXITCODE
    $console = if (Test-Path -LiteralPath $consolePath) {
        Get-Content -LiteralPath $consolePath -Raw
    }
    else {
        ""
    }
    $archive = Complete-Diagnostics -Path $bundle -Target $Target -ExitCode $exitCode -InputPaths $InputPaths
    return [ordered]@{
        exit_code = $exitCode
        bundle = $bundle
        archive = $archive
        console = $console
        command = if ($Target -eq "cli") {
            "uv run translate-ja $($Arguments -join ' ')"
        }
        else {
            "uv run pytest tests/e2e/test_ui.py -q"
        }
    }
}

function Get-ProcessingId {
    param(
        [string]$Console,
        [string]$Prefix
    )

    $pattern = "(?m)^\s*$([Regex]::Escape($Prefix))_id:\s*(?<id>\S+)\s*$"
    $match = [Regex]::Match($Console, $pattern)
    if (-not $match.Success) {
        throw "Could not find ${Prefix}_id in CLI output."
    }
    return $match.Groups["id"].Value
}

function Get-OutputPath {
    param(
        [string]$Console,
        [string]$Name
    )

    $match = [Regex]::Match($Console, "(?m)^\s*$([Regex]::Escape($Name)):\s*(?<path>.+?)\s*$")
    if (-not $match.Success) {
        throw "Could not find $Name in CLI output."
    }
    $path = $match.Groups["path"].Value.Trim()
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "CLI output path does not exist: $path"
    }
    return (Resolve-Path -LiteralPath $path).Path
}

function Find-RecordPath {
    param(
        [string]$ProcessingId,
        [string]$RecordName
    )

    $outputs = Join-Path $repository "outputs"
    $matches = @(Get-ChildItem -LiteralPath $outputs -Recurse -File -Filter $RecordName -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq $ProcessingId })
    if ($matches.Count -eq 1) {
        return $matches[0].FullName
    }
    if ($matches.Count -gt 1) {
        throw "Multiple records found for $ProcessingId ($RecordName)."
    }
    return $null
}

function Wait-ForSucceededRecord {
    param(
        [string]$ProcessingId,
        [string]$RecordName
    )

    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $recordPath = Find-RecordPath -ProcessingId $ProcessingId -RecordName $RecordName
        if ($recordPath) {
            try {
                $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
                if ($record.status -eq "succeeded") {
                    return $recordPath
                }
                if ($record.status -in @("failed", "cancelled")) {
                    throw "$RecordName status is '$($record.status)': $recordPath"
                }
            }
            catch {
                if ($attempt -ge 39) {
                    throw
                }
            }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Record $RecordName for $ProcessingId was not found or did not succeed."
}

function New-Handoff {
    param(
        [string]$Label,
        [string]$Command,
        [string]$Console,
        [string]$Bundle,
        [string[]]$InputPaths
    )

    $inputs = foreach ($inputPath in @($InputPaths)) {
        if (-not $inputPath -or -not (Test-Path -LiteralPath $inputPath -PathType Leaf)) {
            continue
        }
        $resolved = (Resolve-Path -LiteralPath $inputPath).Path
        [ordered]@{
            path = [IO.Path]::GetRelativePath($repository, $resolved)
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolved).Hash.ToLowerInvariant()
        }
    }
    $handoff = [ordered]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        label = $Label
        command = $Command
        console = $Console
        diagnostics_bundle = $Bundle
        diagnostics_archive = "$Bundle.zip"
        git_head = (& git -C $repository rev-parse HEAD).Trim()
        git_branch = (& git -C $repository branch --show-current).Trim()
        inputs = @($inputs)
    }
    $path = Join-Path $Bundle "handoff.json"
    $handoff | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $path -Encoding utf8
    return $path
}

function Invoke-QualityChecks {
    $checks = @(
        @("uv", "run", "ruff", "format", "--check", "."),
        @("uv", "run", "ruff", "check", "."),
        @("uv", "run", "ty", "check"),
        @("uv", "run", "pytest")
    )
    foreach ($check in $checks) {
        Write-Host ("> " + ($check -join " "))
        & $check[0] $check[1..($check.Count - 1)]
        if ($LASTEXITCODE -ne 0) {
            throw "Quality check failed: $($check -join ' ')"
        }
    }
}

function Invoke-CodexRepair {
    param(
        [string]$Label,
        [string]$Command,
        [string]$Console,
        [string]$Bundle,
        [string[]]$InputPaths
    )

    $handoff = New-Handoff -Label $Label -Command $Command -Console $Console -Bundle $Bundle -InputPaths $InputPaths
    if (-not $AutoRemediate) {
        throw "Acceptance failed. Handoff: $handoff"
    }
    & $remediateScript -FailureBundle $Bundle -RepositoryRoot $repository
    if ($LASTEXITCODE -ne 0) {
        throw "Codex remediation failed. Handoff: $handoff"
    }
}

function Invoke-PipelineStep {
    param(
        [string]$Label,
        [string[]]$Arguments,
        [string]$IdPrefix,
        [string]$RecordName,
        [string[]]$InputPaths
    )

    for ($attempt = 0; $attempt -le $MaxRepairAttempts; $attempt++) {
        Write-Host "[$Label] uv run translate-ja $($Arguments -join ' ')"
        $result = Invoke-CommandWithDiagnostics -Label $Label -Target cli -Arguments $Arguments -InputPaths $InputPaths
        $failure = $null
        if ($result.exit_code -eq 0) {
            try {
                $processingId = Get-ProcessingId -Console $result.console -Prefix $IdPrefix
                $recordPath = Wait-ForSucceededRecord -ProcessingId $processingId -RecordName $RecordName
                return [ordered]@{
                    result = $result
                    processing_id = $processingId
                    record = $recordPath
                }
            }
            catch {
                $failure = $_.Exception.Message
            }
        }
        else {
            $failure = "CLI exited with code $($result.exit_code)."
        }
        $handoff = New-Handoff -Label $Label -Command $result.command -Console "$($result.console)`n$failure" -Bundle $result.bundle -InputPaths $InputPaths
        if ($attempt -ge $MaxRepairAttempts) {
            throw "Acceptance failed after $MaxRepairAttempts remediation attempt(s). Handoff: $handoff"
        }
        Invoke-CodexRepair -Label $Label -Command $result.command -Console "$($result.console)`n$failure" -Bundle $result.bundle -InputPaths $InputPaths
        Invoke-QualityChecks
    }
    throw "Unreachable"
}

function Convert-DocxToPdf {
    param([string]$DocxPath)

    $destination = Join-Path (Split-Path -Parent $DocxPath) "document.ja.pdf"
    $word = $null
    $document = $null
    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $document = $word.Documents.Open($DocxPath, $false, $true)
        $document.ExportAsFixedFormat($destination, 17)
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
    if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
        throw "Word did not create PDF: $destination"
    }
    return (Resolve-Path -LiteralPath $destination).Path
}

function Invoke-CliPdf {
    param([string]$PdfPath)

    $source = (Resolve-Path -LiteralPath $PdfPath).Path
    $stem = [IO.Path]::GetFileNameWithoutExtension($source)
    $sourceId = "acceptance-$stem"
    $register = Invoke-PipelineStep -Label "$stem-register" -Arguments @(
        "register", $source, "--source-id", $sourceId
    ) -IdPrefix "registration" -RecordName "registration.json" -InputPaths @($source)
    $translation = Invoke-PipelineStep -Label "$stem-translate" -Arguments @(
        "translate", $source, "--backend", $Backend
    ) -IdPrefix "translation" -RecordName "translation.json" -InputPaths @($source)
    $docx = Get-OutputPath -Console $translation.result.console -Name "docx"
    $translationPdf = Convert-DocxToPdf -DocxPath $docx
    $review = Invoke-PipelineStep -Label "$stem-review" -Arguments @(
        "review", $source, $translationPdf
    ) -IdPrefix "review" -RecordName "review.json" -InputPaths @($source, $translationPdf)
    $upgrade = Invoke-PipelineStep -Label "$stem-upgrade" -Arguments @(
        "upgrade", $source, $source, $translationPdf, "--backend", $Backend
    ) -IdPrefix "upgrade" -RecordName "upgrade.json" -InputPaths @($source, $source, $translationPdf)
    return [ordered]@{
        pdf = $source
        registration_id = $register.processing_id
        registration_record = $register.record
        translation_id = $translation.processing_id
        translation_record = $translation.record
        docx = $docx
        translation_pdf = $translationPdf
        review_id = $review.processing_id
        review_record = $review.record
        upgrade_id = $upgrade.processing_id
        upgrade_record = $upgrade.record
    }
}

function Invoke-UiSmoke {
    for ($attempt = 0; $attempt -le $MaxRepairAttempts; $attempt++) {
        Write-Host "[ui-e2e] uv run pytest tests/e2e/test_ui.py -q"
        $result = Invoke-CommandWithDiagnostics -Label "ui-e2e" -Target ui -Arguments @() -InputPaths @()
        if ($result.exit_code -eq 0) {
            return $result
        }
        $handoff = New-Handoff -Label "ui-e2e" -Command $result.command -Console $result.console -Bundle $result.bundle -InputPaths @()
        if ($attempt -ge $MaxRepairAttempts) {
            throw "UI validation failed after $MaxRepairAttempts remediation attempt(s). Handoff: $handoff"
        }
        Invoke-CodexRepair -Label "ui-e2e" -Command $result.command -Console $result.console -Bundle $result.bundle -InputPaths @()
        Invoke-QualityChecks
    }
    throw "Unreachable"
}

if (-not (Test-Path -LiteralPath $remediateScript -PathType Leaf)) {
    throw "codex-remediate.ps1 was not found."
}
New-Item -ItemType Directory -Path $diagnosticsRoot -Force | Out-Null

$selected = @($PdfPaths)
if ($IncludeLarge -and $selected -notcontains "inputs/sample1.pdf") {
    $selected += "inputs/sample1.pdf"
}
foreach ($path in $selected) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Input PDF was not found: $path"
    }
}

$results = [System.Collections.Generic.List[object]]::new()
$lightPaths = @($selected | Where-Object {
        [IO.Path]::GetFileName($_) -ne "sample1.pdf"
    })
$largePaths = @($selected | Where-Object {
        [IO.Path]::GetFileName($_) -eq "sample1.pdf"
    })
if ($Mode -eq "cli") {
    foreach ($path in $selected) {
        $results.Add((Invoke-CliPdf -PdfPath $path))
    }
}
elseif ($Mode -eq "ui") {
    [void](Invoke-UiSmoke)
}
else {
    foreach ($path in $lightPaths) {
        $results.Add((Invoke-CliPdf -PdfPath $path))
    }
    [void](Invoke-UiSmoke)
    foreach ($path in $largePaths) {
        $results.Add((Invoke-CliPdf -PdfPath $path))
    }
    if ($largePaths.Count -gt 0) {
        [void](Invoke-UiSmoke)
    }
}

$summaryPath = Join-Path $diagnosticsRoot "$timestamp-acceptance-summary.json"
Write-JsonFile -Path $summaryPath -Value @($results)
Write-Host "acceptance succeeded: $summaryPath"
