[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FailureBundle,
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repository = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$bundle = (Resolve-Path -LiteralPath $FailureBundle).Path
$diagnosticsRoot = (Resolve-Path -LiteralPath (Join-Path $repository ".diagnostics")).Path

if (-not $bundle.StartsWith($diagnosticsRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "FailureBundle must be inside .diagnostics."
}

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    Write-Error "Codex CLI is not available."
    exit 2
}

$branch = (& git -C $repository branch --show-current).Trim()
if ([string]::IsNullOrWhiteSpace($branch) -or $branch -eq "main") {
    Write-Error "Codex remediation requires a non-main Git branch."
    exit 2
}

$changes = @(& git -C $repository status --porcelain)

$promptPath = Join-Path $bundle "codex-prompt.txt"
$eventsPath = Join-Path $bundle "codex-events.jsonl"
$progressPath = Join-Path $bundle "codex-progress.log"
$messagePath = Join-Path $bundle "codex-last-message.txt"
$resultPath = Join-Path $bundle "codex-result.json"

$prompt = @"
You are repairing the repository at $repository after an acceptance-test failure.

Read the diagnostic bundle at $bundle, especially handoff.json, console.log,
processing-records.json, llm-calls.json, and task-diagnostics/. Reproduce the
failure with the smallest relevant command. Identify the root cause and make a
minimal source change. Do not modify inputs/, outputs/, .diagnostics/, .env,
or generated artifacts. Do not delete user data. Do not commit, merge, push,
or change branches.

After the change, run:
  uv run ruff format --check .
  uv run ruff check .
  uv run ty check
  uv run pytest

If the failure is environmental or cannot be fixed safely, leave source files
unchanged and explain why in the final response. Report changed files, root
cause, commands run, and their exit status.
"@
$prompt | Set-Content -LiteralPath $promptPath -Encoding utf8

$codexArguments = @(
    "exec",
    "--json",
    "--approve-for-me",
    "--ephemeral",
    "--cd",
    $repository,
    "--output-last-message",
    $messagePath,
    $prompt
)

& codex @codexArguments 1> $eventsPath 2> $progressPath
$exitCode = $LASTEXITCODE

[ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    exit_code = $exitCode
    branch = $branch
    preexisting_changes = $changes
    prompt = [IO.Path]::GetRelativePath($repository, $promptPath)
    events = [IO.Path]::GetRelativePath($repository, $eventsPath)
    progress = [IO.Path]::GetRelativePath($repository, $progressPath)
    last_message = [IO.Path]::GetRelativePath($repository, $messagePath)
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $resultPath -Encoding utf8

if ($exitCode -ne 0) {
    Write-Error "Codex remediation failed with exit code $exitCode."
}
else {
    Write-Host "codex remediation: $resultPath"
}
exit $exitCode
