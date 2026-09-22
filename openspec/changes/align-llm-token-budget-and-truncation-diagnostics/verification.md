<!-- markdownlint-disable MD013 MD041 -->

## Verification Status

- Date: 2026-09-22
- Progress: 15/17 tasks complete
- State: task 5.2 passed; task 5.3 blocked by new Run STRUCTURE failure
- Model／Embedding concurrency: 1

## Automated Evidence

- `ruff check .`: pass
- `ruff format --check .`: pass, 138 files
- `ty check`: pass
- Focused pytest: 46 passed
- Full pytest: 169 passed, 1 skipped
- `openspec validate align-llm-token-budget-and-truncation-diagnostics --strict`: pass
- Dependency diff for `pyproject.toml` and `uv.lock`: 0 files
- Credential value matches in text Run／Change artifacts: 0
- Endpoint value matches in text Run／Change artifacts: 0
- Synthetic secret／prompt／document-body sentinel matches in text Run／Change artifacts: 0

## Old Run Compatibility Evidence

- Run ID: `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`
- Source SHA-256 matches `inputs/sample.pdf`: yes
- Resume result: rejected before execution
- Differences: `tokens.context` saved 16,384／current 30,208; `tokens.output` saved 4,096／current 16,384
- Tree SHA-256 before: `7fb86d0232d5cc47096fe9a261eae4b64906e41611552d40d221a873ba4e581b`
- Tree SHA-256 after: `7fb86d0232d5cc47096fe9a261eae4b64906e41611552d40d221a873ba4e581b`
- Old Run mutation: none

## Page 3 Sequential Probes

### 2026-09-21: server context 8,192

- Requests: 1
- Input tokens: 1,328
- Output tokens: 6,864
- Total tokens: 8,192
- Requested application context: 30,208
- Requested maximum output: 16,384
- Finish reason: `length`
- Schema-valid response: no
- Wall time: 182.721 seconds
- Raw prompt、document body、reasoning content、raw response、Credential、endpointおよびimage binaryをEvidenceへ保存していない

### 2026-09-22: server context 30,000

- Requests: 1、retryなし、同時実行数1
- `llama-server.exe`起動option: `--ctx-size 30000`（OpenSpec／application contextの30,208より208少ない）
- Requested application context: 30,208
- Requested maximum output: 16,384
- Result: `OpenAITimeoutError`
- Wall time: 300.068 seconds（設定済みrequest timeout 300秒）
- Finish reason、token usage、response本文およびschema成否: timeoutのため取得不可
- Raw prompt、document body、reasoning content、raw response、Credential、endpointおよびimage binaryをEvidenceへ保存していない

### 2026-09-22: request timeout 900 seconds

- Requests: 1、retryなし、同時実行数1
- LM Studio管理情報の`contextLength`: 30,208
- 推論processの`--ctx-size`: 30,000（application contextより208少ない）
- Requested application context: 30,208
- Requested maximum output: 16,384
- Input tokens: 1,328
- Output tokens: 8,414
- Total tokens: 9,742（推論process context以内）
- Finish reason: `stop`
- Response body: 非空、282文字
- Schema-valid response: yes、patch 1件
- Wall time: 243.265 seconds
- Raw prompt、document body、reasoning content、raw response、Credential、endpointおよびimage binaryをEvidenceへ保存していない

## New Translation Run

- Run ID: `01a0c97c-f5cf-7031-b808-4ad545133925`（UUIDv7）
- Input: `inputs/sample.pdf`、Run入力copyのSHA-256一致
- Model／Embedding concurrency: 1
- Request timeout: 900 seconds（この実行processの環境設定。製品既定300秒は変更していない）
- Total wall time: 2,099.347 seconds
- Completed checkpoints: SPLIT、DOCLING、UNPACK、MERGE、POSITION、NORMALIZE、LOAD
- DOCLING wall time: 1,705.733 seconds
- STRUCTURE page 2: 一時監査成果物を生成
- STRUCTURE page 3: 画像付きrequest後、text fallbackの`text-invoke`で`TypeError`となり停止
- Run status: `failed`、checkpoint 9件、write 51件
- Failure record: task=`STRUCTURE`、page=3、target=`page/3`、stage=`text-invoke`、cause=`TypeError`。finish reasonとtoken usageは取得されていない
- Atomic Artifact: 失敗したSTRUCTUREの公開directoryなし。一時directoryもcleanup済み
- Run output／外部export: なし
- Raw prompt、document body、reasoning content、raw response、Credential、endpointおよびimage binaryをEvidenceへ保存していない

## Lifecycle and Handoff

旧Runの最終file更新は2026-09-21 10:10:51のままであり、今回の実行では書換え・削除していない。新Runの入力copy、完了済みTask Artifact、Failure、checkpointおよびmetadataは保持されている。失敗したSTRUCTUREの途中成果物は公開されず、`--output-dir`先も作成されていない。移行時は既存token fingerprintに従って旧Runを拒否し、rollback時も新旧Runを変換・削除しない。運用とSupportでは新Runの安全なFailure診断を使用し、保守作業は新たなOpenSpec Changeで原因を特定する。廃止は利用者による明示削除まで行わない。

## Blocker

page 3相当の単発テキストprobeは成功したが、実Workflowの画像付きrequestとtext fallbackの経路で`TypeError`が記録された。現行Failureは安全な例外型だけを保持し、元の例外内容やvision側の失敗理由を保持しないため、根本原因は特定できない。timeout不足またはtoken枯渇と断定するEvidenceもない。task 5.3のTranslation完了とtask 6.2の受入Changeへの成果物引き渡しは未完了とし、同Runを自動Resumeしない。Word-to-PDF変換と目視受入は本Changeの範囲外である。
