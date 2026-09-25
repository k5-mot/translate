<!-- markdownlint-disable MD013 MD041 -->

# Verification Evidence

## Synthetic detached boundary

- `uv run pytest -q tests/test_terminal_evidence.py` passed (11 tests).
- `run_detached()` starts one child with `subprocess.Popen`, redirects stdout/stderr to `DEVNULL`, records child PID and exit code, and writes only the allowlisted `TerminalEvidence` JSON outside the temp root.
- Synthetic child completion produced `status=completed`, `exit_code=0`; a child with no terminal record produced `status=unexpected-exit`; a non-zero child produced `status=failed`; and a deadline produced `status=timeout`, `cause_type=watchdog-timeout` without restart.
- `run_public_run_detached()` executed the existing `execute_public_run()` lifecycle once for a real local Pandoc `convert` Run. The Run completed and the temp root was removed while the external Evidence remained.
- Evidence model and sentinel tests reject arbitrary fields and unsafe names; `allows_public_resume()` is false for missing, running, unknown, or non-zero terminal Evidence.

## Remaining gates

- Historical UUIDv7 Run read-only preflight: `01a0c97c-f5cf-7031-b808-4ad545133925`, input SHA-256 `0185cd9631266fad92ffcede31a447e51cffa94ee572308310a490dc78a74182`, and pre-Gate `checkpoints.sqlite` SHA-256 `0a35f0d6383c1fc46932e838f24c06a7f7fad36bf0014b2cc1c655084e0f19a0`. The metadata reports `status=failed`, `last_task=STRUCTURE`, checkpoint schema v4, and no Qdrant revision in the fingerprint. `tests/test_fingerprint.py`, `tests/test_run_interoperability.py`, and `tests/test_historical_resume.py` passed (25 tests); the source Run was not modified.
- The detached real-model Gate for the historical sample Run is pending; no public Resume is permitted before it reaches `completed` with flushed Evidence.
- Full pytest, Ruff, formatter, ty, strict OpenSpec validation, and final archive evidence are pending.

## 後継の保存方式（2026-09-25）

利用者承認の[overwrite-diagnostic-json-in-place](../overwrite-diagnostic-json-in-place/verification.md)により、本ChangeのEvidence/heartbeat原子的保存設計を直接上書きへ置き換えた。書込み中断時の旧JSON保持は廃止し、破損を成功扱いしない境界、排他、safe項目、process終了確認を維持する。新方式の合成・親子I/O試験は後継記録を参照する。過去の実行証拠や未完了Gateを成功へ書き換えない。汎用Artifact保存と公開Run/Checkpointの原子的保存はこの変更に含めない。
