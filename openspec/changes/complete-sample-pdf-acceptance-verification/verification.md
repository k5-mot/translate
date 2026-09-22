<!-- markdownlint-disable MD013 MD033 MD041 -->

## Verification Context

- Change: `complete-sample-pdf-acceptance-verification`
- Branch: `feature/complete-sample-pdf-acceptance-verification`
- Project revision at resume: `2e9f6aaef75a057113e01bd317f982b2cb5e201d`
- Resume preflight: `2026-09-21T00:10:58.1219056Z`
- Environment: Windows NT `10.0.26200.0`, Python `3.12.9`, uv `0.12.16`, Pandoc `3.11`
- External export directory: `C:\Users\merry\Desktop\translate-acceptance-output\complete-sample-pdf-acceptance-verification`
- Qdrant Collection: `translate-acceptance-sample-pdf`
- Qdrant source ID: `acceptance-sample-pdf`

## Predecessor Evidence

| Check | Result | Evidence |
|---|---|---|
| Fixed input identity | PASS | `inputs/sample.pdf`、65,475,787 bytes、358 pages、SHA-256 `0185CD9631266FAD92FFCEDE31A447E51CFFA94EE572308310A490DC78A74182` |
| Register Run | PASS | `01a0bf06-60d8-7446-a63c-7f22e8ee698a`、UUIDv7、status `completed` |
| Dedicated Collection | PASS | 1079 Point、対象source 1079件、別source 0件、重複Chunk key 0件、revision 1種類、revision欠落0件 |
| Translation fingerprint | PASS | 保存値・現在値とも`4b41528d1e8b2af06b8154aeaf111f12f525e36d95888d5d2d7ba20bed366265` |
| Qdrant fingerprint exclusion | PASS | canonical Translation fingerprintにQdrant設定・状態を含まない |
| Export isolation | PASS | 外部export先はRepositoryからの相対pathが`..\translate-acceptance-output\complete-sample-pdf-acceptance-verification`で、開始時File 0件 |

## Translation

### Run and Resume

- Sanitized initial command: `uv run python cli.py translate inputs/sample.pdf --backend llm --output-dir outputs`
- Sanitized resume command: `QDRANT_COLLECTION=translate-acceptance-sample-pdf uv run python cli.py translate inputs/sample.pdf --backend llm --output-dir C:\Users\merry\Desktop\translate-acceptance-output\complete-sample-pdf-acceptance-verification --resume 01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`
- Run ID: `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`（UUIDv7）
- Models: structure／translation／review／fix `google/gemma4:12b`、Embedding `Qwen/Qwen3-Embedding:0.6B`
- Retry／timeout／deadline: 3回／300秒／21,600秒
- Workflow concurrency: Translation graph `max_concurrency=1`。別の公開Workflow process 0件をResume直前に確認する。
- Initial execution: `2026-09-20T23:47:51.627068Z`開始。Task `DOCLING`のpart 25処理後、利用者がprocessを停止した。
- Interruption Evidence: `failure.json`はTask `DOCLING`、Error `KeyboardInterrupt`、対象page／group／targetなし、`2026-09-21T00:09:14.429742Z`。公開成果物0件。
- Pre-resume completed SPLIT snapshot: 38 Files、aggregate SHA-256 `2db52034084c99fc63cd2a3d2d2514f371bb37ec542421fcafbc19d2adc80e1e`、latest mtime ns `1789948072235713100`。
- Explicit Resume: 互換fingerprintを確認し、別Workflow process 0件の状態で同じrun IDを再開した。DOCLING 36分割、UNPACK、MERGE、POSITION、NORMALIZEおよびLOADまで逐次完了した。
- Resume timing: DOCLING `1683.718 s`、Resume process total `1697.897 s`。CLI進捗は`[7/17] LOAD`まで到達した。
- Resume result: STRUCTUREで`TypeError`となりexit code 1。Run status `failed`、last task `STRUCTURE`、warning `TypeError`、Run size 247,437,661 bytes、正本／外部公開成果物0件。
- Retry observation: STRUCTURE失敗までにCLIまたはRun Evidenceへretry記録はなかった。本文を使用しない構造化text probeは障害後に1回でPASSし、`9.298 s`で完了した。
- Failure diagnostic: `failure.json`はTask `STRUCTURE`とredact済み原因`TypeError`を保持するが、page、group、target IDおよびstageは全て`null`である。

### Completed Artifact Snapshot after STRUCTURE Failure

| Task | Files | Aggregate SHA-256 | Latest mtime ns | Resume result |
|---|---:|---|---:|---|
| SPLIT | 38 | `2db52034084c99fc63cd2a3d2d2514f371bb37ec542421fcafbc19d2adc80e1e` | 1789948072235713100 | PASS。Resume前後でhash／mtime不変 |
| DOCLING | 205 | `c39b8d233658f26c3bf581754c7255a764a34546070085867454a649c5219be2` | 1789951183732394400 | 次回Resume用baseline |
| MERGE | 62 | `60192b3840523e4f27b692e90114a86b0ee19da611ea9dfd5c99743c7a991c78` | 1789951184308538200 | 次回Resume用baseline |
| POSITION | 3 | `4d820099e55ab44e01729bcce974321586dc858bfdfea2014f96015bcf88ab43` | 1789951185234256100 | 次回Resume用baseline |
| NORMALIZE | 3 | `87f3762295609d66acbdbd60b6e59471643921b0d570c5a7cc4a3744ead82283` | 1789951185841967600 | 次回Resume用baseline |
| LOAD | 2 | `4a9e266b627d5597e33b66d72af7afa194e1737686aae96d6466b36b44c7bb90` | 1789951185992041900 | 次回Resume用baseline |

### Acceptance Status

| Gate | Status | Notes |
|---|---|---|
| Translate execution | FAIL | STRUCTUREで`TypeError`。Runは失敗状態を保持し、公開成果物0件 |
| Resume preservation | PASS | SPLIT Artifactのhash／mtimeはResume前後で不変。DOCLING〜LOADの次回baselineも記録 |
| DOCX integrity | PENDING | size、SHA-256、ZIP entry、CRCを検査する |
| DOCX structure | PENDING | 表紙重複と代表構造をspot checkする |
| Search artifacts | PENDING | Collection、検索日時、引用元、取得記録を検査する |
| User conversion | PENDING | DOCX引渡し後に利用者PDFを受領する |
| Review | PENDING | 利用者変換PDF受領後に実行する |
| Lifecycle／Security／Quality | PENDING | 全受入Operation後に判定する |

## Blocking Findings

1. STRUCTUREの外部LLM呼出しが`TypeError`で停止した。HTTP transport、408、429および5xxだけがAdapterのretry対象であり、今回の`TypeError`には設定済み3回の有限retryが適用されたEvidenceがない。
2. STRUCTURE failureはTask名だけを保持し、対象page、target IDおよびstageが欠落する。失敗したpageとvision／text fallbackのどちらが原因かを公開Evidenceから特定できない。
3. 障害後の短いtext-only構造化probeはPASSしたため、LLM Service全体の継続停止は確認されない。再Resumeだけで成功する可能性はあるが、上記のretry・診断性gapを解消または明示的に受容するまでTask 3.2を完了扱いにしない。

### 2026-09-23 Corrected Run Handoff

- 後続修正を含むRun `01a0c97c-f5cf-7031-b808-4ad545133925`を、context 30,208、parallel 1、fingerprint一致、900秒request timeoutで一度だけ明示Resumeした。
- Result: exit code 1、1,645.108秒。page 2のprivate STRUCTURE checkpointはAtomic確定したが、page 3のtext fallbackが`text-invoke`／`TypeError`で停止した。
- 成功済みSPLIT〜LOAD 313 filesのhash／mtimeは不変。page 3 checkpoint、公開STRUCTURE、Run outputおよび外部DOCX exportは0件。Failure／log／metadataのCredential、endpointおよびraw sentinel漏えいは0件。
- RunはResume可能な`failed`状態で保持し、追加Resumeは行っていない。したがってTask 3.2以降、Word-to-PDF変換、目視比較およびComparison Reviewは引き続き未完了である。

## Disposal Candidates

- Predecessor Register Run: `runs/01a0bf06-60d8-7446-a63c-7f22e8ee698a/`
- Translation Run: `runs/01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5/`
- External export: `C:\Users\merry\Desktop\translate-acceptance-output\complete-sample-pdf-acceptance-verification`
- Qdrant Collection: `translate-acceptance-sample-pdf`

自動削除は行わない。Run、外部exportおよびQdrant Collectionは利用者が対象を確認して明示指示した場合だけ個別に削除する。
