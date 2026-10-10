[CmdletBinding()]
param([Parameter(Mandatory)][string]$FailureFile)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$failure = Get-Content -LiteralPath $FailureFile -Raw | ConvertFrom-Json
$logRoot = Join-Path $root '.tmp'
$attemptPath = Join-Path $logRoot 'real_acceptance_repair_attempts.json'
$attempts = if (Test-Path -LiteralPath $attemptPath) {
    Get-Content -LiteralPath $attemptPath -Raw | ConvertFrom-Json -AsHashtable
} else { @{} }
$stage = [string]$failure.stage
$attempts[$stage] = [int]$attempts[$stage] + 1
$attempts | ConvertTo-Json | Set-Content -LiteralPath $attemptPath -Encoding utf8
# shortcut: 1工程3回を超える自動修正は停止し、原因調査後に再開する。
if ($attempts[$stage] -gt 3) { throw "Repair limit reached for $stage" }
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
& codex exec --json --approve-for-me --ephemeral --cd $root --output-last-message $messagePath $prompt 1> $eventsPath 2> $progressPath
if ($LASTEXITCODE -ne 0) { throw "Codex exited with $LASTEXITCODE; see $progressPath" }
if ((& git rev-parse HEAD).Trim() -eq $headBefore) { throw "Codex did not commit a repair; see $messagePath" }
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

$shell = (Get-Process -Id $PID).Path
$runner = Join-Path $PSScriptRoot 'real_acceptance.ps1'
Start-Process -FilePath $shell -ArgumentList @('-NoProfile', '-File', $runner) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'real_acceptance_background.log') -RedirectStandardError (Join-Path $logRoot 'real_acceptance_background.err.log') | Out-Null
Write-Output "Codex committed repair and restarted acceptance for $stage"
