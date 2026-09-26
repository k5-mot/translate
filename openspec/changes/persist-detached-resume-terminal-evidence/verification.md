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

## Apply追記: 監視例外時の早すぎるcleanup（2026-09-26）

Task 2.5の部分実装。基点`7b4164b`の作業Treeで、`run_public_run_detached()`が`finally`から一時rootを削除し、watchdogが例外を返した際にchildの生存確認より先にrequest／markerを失うことを再現した。既存の`run_detached()`が終端結果を返してからcleanupする順序へ修正した。新しいModule、Dependency、再試行、子の自動再起動、Model requestは追加していない。

### 再現と回帰検証

- `test_monitor_failure_preserves_live_child_workspace`: 実際の標準`Popen`で外部通信しない待機childを起動し、監視境界へ`OSError`／`RuntimeError`／`KeyboardInterrupt`を注入した。修正前は3件すべて、childが生存中なのにmarkerが消えるassertで失敗した（3 failed, 41 deselected, 2.06秒）。修正後は元例外の同一性、child生存、marker／request保持、公開Resume不可を確認した。Testの最後には、そのTestが起動したchildだけを停止・waitして回収した。
- `test_public_detached_runner_uses_existing_lifecycle_once`: watchdogをmockしたwrapper境界で`completed`／`failed`／`unexpected-exit`／`timeout`の4終端結果を渡し、従来どおり結果を返してtemp rootを削除することを確認した。4種類すべての実process終了を今回新規に再現したという証拠ではない。
- `uv run pytest -q tests/test_terminal_evidence.py`: **47 passed, 12.13秒**。既存の実Pandoc convert child検証も含む。
- `uv run pytest -q`: **817 passed, 1 skipped, 50.20秒**。既存の未コミット変更を含む作業Treeの結果であり、本修正だけを切り出したclean Treeの結果ではない。
- Ruff全体、format全体（373 File）、ty、strict OpenSpec validation、`git diff --check`は成功した。

検証対象SHA-256: `translate/common/terminal_evidence.py`は`bce8d8abc38f60251987f81715e6b98de1cfd43b276d770d9a3a890af5b46fe2`、`tests/test_terminal_evidence.py`は`207be4aae1b7eb2533c847ef4a767fea5d735113d20b6545e941f8b313c7589f`。前者には別作業の`FailureKind`拡張が含まれるが、本修正のCommit対象からは除外する。

### 限界と未完了条件

- 今回は実child＋監視例外の注入であり、親のOS hard kill後の再回収は未実装・未検証である。PID保存前の監視例外、PID再利用を含む所有確認、回収者間の競合も解決済みとはしない。
- `cleanup_detached_temp()`自体のmarker検査は、Runの所有権やchild停止を保証しない。任意の残存rootを安全に削除できるようになったとは扱わない。
- Task 2.5と最終品質Gate 5.1は未完了を維持し、Change全体は**14/21**。旧Run、正本Checkpoint、入力PDF、既存成果物は変更せず、実LLM／Embeddingや正本Resumeも起動していない。
- 最新修正を含む実PDF Translation → Microsoft Word PDF → Comparison Review、目視受入、仕様同期／archive／mainへのマージは未完了である。
