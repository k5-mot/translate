[CmdletBinding()]
param(
    [ValidateSet("none", "translate-ja", "streamlit")]
    [string]$Target = "none",
    [string[]]$Arguments = @(),
    [string]$Label = "manual"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$safeLabel = $Label -replace "[^A-Za-z0-9._-]", "-"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$diagnosticsRoot = Join-Path $repositoryRoot ".diagnostics"
$bundleRoot = Join-Path $diagnosticsRoot "$timestamp-$safeLabel"
$consoleLog = Join-Path $bundleRoot "console.log"
$commandExitCode = 0

New-Item -ItemType Directory -Path $bundleRoot -Force | Out-Null
Push-Location $repositoryRoot
try {
    if ($Target -ne "none") {
        "uv run $Target $($Arguments -join ' ')" | Set-Content -Encoding utf8 (
            Join-Path $bundleRoot "command.txt"
        )
        & uv run $Target @Arguments *>&1 | Tee-Object -FilePath $consoleLog
        $commandExitCode = $LASTEXITCODE
    }

    @(
        "generated_at=$((Get-Date).ToUniversalTime().ToString('o'))"
        "target=$Target"
        "exit_code=$commandExitCode"
        "repository=$repositoryRoot"
    ) | Set-Content -Encoding utf8 (Join-Path $bundleRoot "summary.txt")

    @(
        "## status"
        (& git status --short --branch 2>&1)
        ""
        "## recent commits"
        (& git log --oneline --decorate -10 2>&1)
        ""
        "## diff stat"
        (& git diff --stat 2>&1)
    ) | Set-Content -Encoding utf8 (Join-Path $bundleRoot "git.txt")

    $environment = @(
        "powershell=$($PSVersionTable.PSVersion)"
        "os=$([System.Environment]::OSVersion.VersionString)"
        "uv=$((& uv --version 2>&1) -join ' ')"
        "python=$((& uv run python --version 2>&1) -join ' ')"
    )
    if (Get-Command pandoc -ErrorAction SilentlyContinue) {
        $environment += "pandoc=$((& pandoc --version 2>&1 | Select-Object -First 1) -join ' ')"
    }
    $envPath = Join-Path $repositoryRoot ".env"
    if (Test-Path $envPath) {
        $environment += ""
        $environment += "## .env keys (values omitted)"
        $environment += Get-Content $envPath | ForEach-Object {
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
    $environment | Set-Content -Encoding utf8 (Join-Path $bundleRoot "environment.txt")

    $inputDirectory = Join-Path $repositoryRoot "inputs"
    $inputs = @(
        Get-ChildItem $inputDirectory -File -ErrorAction SilentlyContinue | ForEach-Object {
            [ordered]@{
                path = [IO.Path]::GetRelativePath($repositoryRoot, $_.FullName)
                size_bytes = $_.Length
                sha256 = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLowerInvariant()
                modified_at = $_.LastWriteTimeUtc.ToString("o")
            }
        }
    )
    $inputs | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (
        Join-Path $bundleRoot "inputs.json"
    )

    $outputsRoot = Join-Path $repositoryRoot "outputs"
    $recordNames = @("translation.json", "review.json", "registration.json", "upgrade.json")
    $records = @(
        Get-ChildItem $outputsRoot -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in $recordNames } |
            ForEach-Object {
                $recordFile = $_
                try {
                    $record = Get-Content $recordFile.FullName -Raw | ConvertFrom-Json
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
                    [pscustomobject][ordered]@{
                        path = [IO.Path]::GetRelativePath(
                            $repositoryRoot,
                            $recordFile.FullName
                        )
                        status = $record.status
                        updated_at = $record.updated_at
                        error = $record.error
                        tasks = $tasks
                    }
                }
                catch {
                    [pscustomobject][ordered]@{
                        path = [IO.Path]::GetRelativePath(
                            $repositoryRoot,
                            $recordFile.FullName
                        )
                        parse_error = $_.Exception.Message
                    }
                }
            }
    )
    $records | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (
        Join-Path $bundleRoot "processing-records.json"
    )

    $calls = @(
        Get-ChildItem $outputsRoot -Recurse -File -Filter "call.json" -ErrorAction SilentlyContinue |
            ForEach-Object {
                $callFile = $_
                try {
                    $call = Get-Content $callFile.FullName -Raw | ConvertFrom-Json
                    [pscustomobject][ordered]@{
                        path = [IO.Path]::GetRelativePath(
                            $repositoryRoot,
                            $callFile.FullName
                        )
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
                    [pscustomobject][ordered]@{
                        path = [IO.Path]::GetRelativePath(
                            $repositoryRoot,
                            $callFile.FullName
                        )
                        status = "parse_error"
                        error = $_.Exception.Message
                    }
                }
            }
    )
    $callSummary = @(
        $calls | Group-Object task, status | ForEach-Object {
            [ordered]@{
                task_status = $_.Name
                count = $_.Count
            }
        }
    )
    [ordered]@{
        summary = $callSummary
        incomplete_or_failed = @(
            $calls | Where-Object { $_.status -notin @("succeeded", "split") }
        )
    } | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (
        Join-Path $bundleRoot "llm-calls.json"
    )

    $taskDiagnostics = Join-Path $bundleRoot "task-diagnostics"
    Get-ChildItem $outputsRoot -Recurse -File -Filter "task-*.json" -ErrorAction SilentlyContinue |
        ForEach-Object {
            $relative = [IO.Path]::GetRelativePath($outputsRoot, $_.FullName)
            $destination = Join-Path $taskDiagnostics $relative
            New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destination
        }
}
finally {
    Pop-Location
}

$archive = "$bundleRoot.zip"
Compress-Archive -Path (Join-Path $bundleRoot "*") -DestinationPath $archive -Force
Write-Host "diagnostics: $archive"
exit $commandExitCode
