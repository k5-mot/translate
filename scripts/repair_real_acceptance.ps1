[CmdletBinding()]
param([Parameter(Mandatory)][string]$FailureFile)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$failure = Get-Content -LiteralPath $FailureFile -Raw | ConvertFrom-Json
$logRoot = Join-Path $root '.tmp'
$stage = [string]$failure.stage
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw 'Codex CLI is unavailable' }
$branch = (& git branch --show-current).Trim()
if ($branch -ne 'feature/real-pdf-acceptance-20261009') { throw "Unexpected branch: $branch" }
if (@(git status --porcelain).Count -gt 0) { throw 'Working tree is not clean' }
$headBefore = (& git rev-parse HEAD).Trim()

$prompt = @"
You are repairing a real-PDF acceptance failure in $root.
Reply to the user in Japanese. Follow AGENTS.md, CONTRIBUTING.md, CODING_RULES.md.
Failure report: $FailureFile
Stage: $stage
Error: $($failure.error)
CLI log: .tmp/real_acceptance_command.log
State: .tmp/real_acceptance_state.json
Inspect the relevant processing record, LLM call logs and source code. Find and fix
the root cause with the smallest complete change. Preserve user-written comments,
especially payload examples. Do not edit .env, inputs/, outputs/, or generated data.
Run the relevant focused check plus:
  uv run ruff check .
  uv run ruff format --check .
  uv run ty check
  uv run pytest -q
Commit your change on this feature branch. Use a Japanese Conventional Commit
message with reason and change, human Git author, and the trailer AI-assisted: yes.
Do not merge or push. The supervising script will rerun the failed real-PDF stage.
If the issue is environmental or cannot be fixed safely, explain it and leave the
working tree unchanged.
"@
$promptPath = Join-Path $logRoot 'real_acceptance_codex_prompt.txt'
$prompt | Set-Content -LiteralPath $promptPath -Encoding utf8
$eventsPath = Join-Path $logRoot 'real_acceptance_codex_events.jsonl'
$progressPath = Join-Path $logRoot 'real_acceptance_codex_progress.log'
$messagePath = Join-Path $logRoot 'real_acceptance_codex_message.txt'
Write-Output "Codex修正開始: $stage (進捗: $progressPath)"
& codex exec --json --sandbox danger-full-access --config approval_policy=never --ephemeral --cd $root --output-last-message $messagePath $prompt 1> $eventsPath 2> $progressPath
if ($LASTEXITCODE -ne 0) { throw "Codex exited with $LASTEXITCODE; see $progressPath" }
$unchanged = (& git rev-parse HEAD).Trim() -eq $headBefore
if ($unchanged -and $failure.error -notmatch 'LLMConnectionError|EmbeddingError') {
    $diagnosis = (Get-Content -LiteralPath $messagePath -Raw).Trim()
    throw "Codex found no safe code repair for $stage. Diagnosis: $diagnosis"
}
if (@(git status --porcelain).Count -gt 0) { throw 'Codex left uncommitted changes' }

foreach ($check in @(
    @('ruff', 'check', '.'),
    @('ruff', 'format', '--check', '.'),
    @('ty', 'check'),
    @('pytest', '-q')
)) {
    & uv run @check
    if ($LASTEXITCODE -ne 0) { throw "Quality check failed: $($check -join ' ')" }
}

Write-Output "Codex review completed for $stage"
