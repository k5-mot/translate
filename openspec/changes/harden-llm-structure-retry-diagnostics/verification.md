<!-- markdownlint-disable MD013 MD041 -->

## 検証環境

- 実施日: 2026-09-21
- OS: Windows
- Python: 3.12.9
- Branch: `feature/harden-llm-structure-retry-diagnostics`
- Change: `harden-llm-structure-retry-diagnostics`

## 実装検証

### Focused Test

Command:

```text
uv run pytest tests/test_adapter_retry.py tests/test_structure_diagnostics.py tests/test_translation_workflow.py tests/test_failure_contract.py -q
```

結果: exit code 0、22 passed。

検証した境界:

- LLM invokeの通信Error／`TypeError`、response content正規化の`TypeError`、構造化parse Errorは既存attempt・backoff・deadline内で有限retryする。
- HTTP 400、Model／Client構築およびprompt構築の`TypeError`は一回で停止する。
- Visionの有限失敗後だけTextへ逐次fallbackし、最終失敗はpage、`page/<n>`、stageおよびcause typeだけを公開する。
- 失敗したSTRUCTURE directoryはpublishされず、旧Failure JSONとReference Registration診断は互換に読める。
- stageは固定allowlist、cause typeはPython identifierへ限定し、任意値を永続化しない。

### 全品質Gate

| Command | Exit code | 結果 |
|---|---:|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run ruff format --check .` | 0 | 133 files already formatted |
| `uv run ty check` | 0 | All checks passed |
| `uv run pytest` | 0 | 159 passed、1 skipped、13.84 s |
| `npx --yes @fission-ai/openspec validate harden-llm-structure-retry-diagnostics --strict` | 0 | Change valid、spec deltaは宣言どおりskip |

既知skipは`tests/test_cli_process.py`のPOSIX PTY契約1件であり、Windowsは同Fileの非対話process Testで検証済み。`uv run pytest tests/test_cli_process.py -q -rs`はexit code 0、1 passed、1 skippedだった。

## Security・Dependency・並行性

- 対象Runの既存`failure.json`と`run.log`の2 Fileを、Credential代入、Bearer token、data image、prompt代入およびraw応答代入patternでscanし、一致0件。
- Focused Testはsentinelをraw例外へ注入し、Error文字列、`failure.json`、`run.log`および公開Errorへの漏えい0件を確認した。
- `pyproject.toml`と`uv.lock`のDependency差分は0件。
- 追加Python差分に`max_concurrency > 1`、Thread／Process pool、`asyncio.gather`またはtask生成は0件。既存Workflowの`max_concurrency=1`を維持した。
- `git diff --check`はexit code 0。

## 同一Run Resume

### Read-only preflight

- Run ID: `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`。
- Run status／last task: `failed`／`STRUCTURE`。既存Failureは`TypeError`で、修正前のためpage、target、stageおよびcause typeは未記録。
- 入力: `inputs/sample.pdf`とRun内copyはいずれも65,475,787 bytes、SHA-256 `0185cd9631266fad92ffcede31a447e51cffa94ee572308310a490dc78a74182`。
- 保存fingerprint／現在fingerprint: いずれも`4b41528d1e8b2af06b8154aeaf111f12f525e36d95888d5d2d7ba20bed366265`。
- Qdrant: Collection `translate-acceptance-sample-pdf`が存在し、read-only exact countは1079 Point。Qdrant状態はfingerprintへ含めない。
- 外部export先: `C:\Users\merry\Desktop\translate-acceptance-output\complete-sample-pdf-acceptance-verification`、Resume前File 0件。
- Model: structure／translation／review／fixは`google/gemma4:12b`、Embeddingは`Qwen/Qwen3-Embedding:0.6B`。
- Retry／request timeout／Task deadline: 3回／300秒／21,600秒。
- 他のPython／uv／Streamlit公開Workflow process: 0件。

### Resume前Artifact snapshot

Aggregate SHA-256は、相対pathのUTF-8 bytesと各File SHA-256のbinary digestをpath順に連結してSHA-256計算した。先行Evidenceの値とfile数・mtimeを含め全件一致した。

| Task | Files | Aggregate SHA-256 | Latest mtime ns | Preflight |
|---|---:|---|---:|---|
| SPLIT | 38 | `2db52034084c99fc63cd2a3d2d2514f371bb37ec542421fcafbc19d2adc80e1e` | 1789948072235713100 | PASS |
| DOCLING | 205 | `c39b8d233658f26c3bf581754c7255a764a34546070085867454a649c5219be2` | 1789951183732394400 | PASS |
| MERGE | 62 | `60192b3840523e4f27b692e90114a86b0ee19da611ea9dfd5c99743c7a991c78` | 1789951184308538200 | PASS |
| POSITION | 3 | `4d820099e55ab44e01729bcce974321586dc858bfdfea2014f96015bcf88ab43` | 1789951185234256100 | PASS |
| NORMALIZE | 3 | `87f3762295609d66acbdbd60b6e59471643921b0d570c5a7cc4a3744ead82283` | 1789951185841967600 | PASS |
| LOAD | 2 | `4a9e266b627d5597e33b66d72af7afa194e1737686aae96d6466b36b44c7bb90` | 1789951185992041900 | PASS |

### Resume実行

- Sanitized command: `QDRANT_COLLECTION=translate-acceptance-sample-pdf uv run python cli.py translate inputs/sample.pdf --backend llm --output-dir C:\Users\merry\Desktop\translate-acceptance-output\complete-sample-pdf-acceptance-verification --resume 01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`。
- CLIは`run_id=01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5 mode=resume`を表示し、別Runを作成しなかった。
- Result: exit code 1、total 138.665秒。Run statusは`failed`、last taskは`STRUCTURE`。
- Failure: page 3、target `page/3`、stage `text-invoke`、cause type `TypeError`、error type `StructurePageError`。
- Retry: 現在設定と実行Code上の有限attemptは3回。CLI／Run logは最終診断だけを記録し、attempt別logは出力しない。
- Atomicity: Run内output 0件、外部export 0件、公開`structure/` 0件、`.structure.*` temporary 0件。
- Process: CLI終了後の公開Workflow processは0件。
- Resume可能性: 同じ入力・設定で`prepare_run`が`resume_compatible=True`、同じrun ID、status `failed`を返した。

### Resume後Artifact snapshot

| Task | Files | Aggregate SHA-256 | Latest mtime ns | Resume前後 |
|---|---:|---|---:|---|
| SPLIT | 38 | `2db52034084c99fc63cd2a3d2d2514f371bb37ec542421fcafbc19d2adc80e1e` | 1789948072235713100 | PASS、不変 |
| DOCLING | 205 | `c39b8d233658f26c3bf581754c7255a764a34546070085867454a649c5219be2` | 1789951183732394400 | PASS、不変 |
| MERGE | 62 | `60192b3840523e4f27b692e90114a86b0ee19da611ea9dfd5c99743c7a991c78` | 1789951184308538200 | PASS、不変 |
| POSITION | 3 | `4d820099e55ab44e01729bcce974321586dc858bfdfea2014f96015bcf88ab43` | 1789951185234256100 | PASS、不変 |
| NORMALIZE | 3 | `87f3762295609d66acbdbd60b6e59471643921b0d570c5a7cc4a3744ead82283` | 1789951185841967600 | PASS、不変 |
| LOAD | 2 | `4a9e266b627d5597e33b66d72af7afa194e1737686aae96d6466b36b44c7bb90` | 1789951185992041900 | PASS、不変 |

### Apply停止判定

実Runは有限retryとVision→Text fallback後にもpage 3のText invokeで`TypeError`となった。Changeの設計に従い、追加原因を推測して修正またはprobeせず停止する。Task 5.3と5.4は未完了のままとし、Run、成功済みArtifact、外部export先およびQdrant Collectionを削除しない。
