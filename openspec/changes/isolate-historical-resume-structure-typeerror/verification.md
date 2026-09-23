<!-- markdownlint-disable MD013 MD041 -->

## Apply Evidence

### Read-only Historical Baseline

- Run ID／operation／status／last task: `01a0c97c-f5cf-7031-b808-4ad545133925`／`translate`／`failed`／`STRUCTURE`。
- Fingerprint SHA-256: `fdd0ce952338a28d78dc2d99e976c812f8bce23f85e79e250ecc1f54b3cece96`。Input SHA-256: `0185cd9631266fad92ffcede31a447e51cffa94ee572308310a490dc78a74182`。
- Failure: page 3、target `page/3`、stage `text-invoke`、cause `TypeError`。Workflow thread ID: `d13f41e358bd41edc06704338e276b04f317f394c46045dc763124880bfb48e0`。
- LangGraph Database: 9 checkpoints／51 writes、159,744 bytes。SHA-256 `0a35f0d6383c1fc46932e838f24c06a7f7fad36bf0014b2cc1c655084e0f19a0`、mtime ns `1790121479615623400`。
- 最新snapshotのpending nodeは`structure`だけで、完了TaskはSPLIT、DOCLING、UNPACK、MERGE、POSITION、NORMALIZE、LOADの7件だった。
- Stateは15 keysで、scalar pathは`source`、`output_dir`、`workspace_dir`、`document_path`、`merged`、`positioned`、`normalized`、path listは`archives`／`documents`／`parts`各36件だった。Top-level binaryはなく、本文、画像binaryおよびCredential fieldはなかった。
- 完了済みSPLIT～LOADは313 files、relative path UTF-8 bytesとfile bytesをpath順に連結したaggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`。
- Private STRUCTURE checkpointはpage 2の`.complete.json`、`audit.json`、`meta.json`、`page.json`だけである。公開STRUCTURE Artifact、Run outputおよび外部export `outputs/sample-translation`は0件だった。
- Baseline取得前後でDatabase hash／mtime／sizeは一致し、Run metadata、Failure、workflow metadata、成功済みArtifactおよび外部状態へのwriteは0件だった。

### Runtime Baseline

- LM Studioは`google/gemma4:12b`、context 30,208、parallel 1、queued 0／idle。推論processの実`--ctx-size`も30,208だった。
- Loaded modelは対象LLM一件だけで、他のPython、ModelおよびEmbedding処理は0件だった。
- Applicationはcontext 30,208、output 16,384、image 2,048、request timeout 300秒、Task deadline 21,600秒、retry attempts 3。OpenAI SDK retryは製品Codeで0である。
- Credential、endpoint、prompt、本文、raw response、reasoning、tracebackおよび画像binaryは出力またはEvidenceへ保存していない。

### Historical Clone and Offline Matrix

- 正本Databaseをread-only接続から標準SQLite backupでOS一時directoryへ複製し、`PRAGMA integrity_check=ok`、元9 checkpoints／51 writesおよび正本hash／mtime／size不変を確認した。
- Scalar path 7 fieldと`archives`／`documents`／`parts`各36件だけを正本Run rootからtemp Run rootへ写像し、複製Databaseへ実`SqliteSaver.update_state(..., as_node="load")`でfork checkpointを一件追加した。Rebase前後のpending nodeは`structure`だけ、完了Task 7件は重複せず維持された。
- Root外path、未知本文field、binary state、symlink／junction、破損SQLiteおよびcopy failureを拒否するfault Testを追加した。失敗時の部分cloneは0件で、正本へのwriteは0件だった。
- 正本9／51 snapshotを使うRun外診断では、full 353-page Documentとpage 2 private checkpointを複製した。実Translation graph、実ChatOpenAI／OpenAI SDK stackおよびMockTransportを通し、page 2再処理0件、page 3以降のProvider call 351件をすべて逐次処理した。Model build／bind／invoke／responseも各351件、STRUCTURE state update 1件、page 3 checkpointおよび公開STRUCTURE ArtifactがAtomicに生成され、一時directoryは削除された。
- 小さい決定的fixtureではfresh page 3、fresh full Document／page 2 checkpoint、historical clone、logging、`OutputLock`、task status、観測Context、全wrapperおよび`execute_public_run()`を一要因ずつ比較した。Network 0件、Provider call／response／parse／node update／checkpoint commit各1件、最大同時call 1だった。

### Reproduced Cause and Correction

- 修正前はdirect historical cloneが成功し、run loggingを追加した最初のcaseだけがvision後の`text-invoke`／`TypeError`を再現した。Lock、task statusおよび観測Contextを単独実行したcaseは成功した。
- 安全なexception originはbuilt-in `TypeError`、`logging.LogRecord.getMessage()`、`RedactionFilter.filter()`だった。Raw message、args値およびtraceback本文は保存していない。
- `RedactionFilter`が全log argumentを文字列化した後、OpenAI／HTTP clientの数値placeholder `%d`をformatしたことが原因だった。数値argumentを型保持し、文字列Credentialとbinaryだけを事前redactした後、完成messageを再redactする最小修正を行った。
- `tests/test_redaction.py`へ数値HTTP logの回帰を追加し、Credential、data image、binaryおよび例外messageの既存非出力契約を維持した。
- 修正後はclone／rebase／fresh／historical／全wrapper／公開Lifecycleを含む17 testsが成功した。公開LifecycleはSTRUCTURE完了後の意図した境界Errorへ到達し、TypeErrorを生成しなかった。

### Cause-specific Regression

- Historical clone、redaction、Langfuse、LLM Adapter、page checkpoint、STRUCTURE diagnostics、workflow state、Failure、Resume、fingerprint、CLI／Streamlit相互運用、TranslationおよびComparison Reviewのfocused suiteは106 passedだった。
- 観測create／update／end障害はwarning継続、Provider transport／parse／state update／checkpoint commit障害は元Error identity、有限attempt、部分公開0件およびResume可能停止を維持した。Loggingの数値argumentは型保持され、lock、callback、handlerおよびContextVarは各case後にcleanupされた。
- 408／429／5xx／parseの有限retry、恒久4xx即時停止、未知の`TypeError`伝播、page checkpoint v4、Run fingerprint、CLI／Streamlit共有RunおよびQdrant状態非依存に差分はなかった。
- 全Model／Embedding実行契約は`max_concurrency=1`のままで、製品Code差分は`translate/common/logger.py`の型保持redactionだけである。Dependency、Run schema、fingerprint、Model／token設定およびOS固有製品分岐は変更していない。

### Automated Quality and Security Gate

- Clone／rebase、offline matrix、Adapter、STRUCTURE、Translation／Comparison Review、Failure、Resume、Lifecycle、Atomic公開およびfingerprintのfocused suiteは106 passedだった。
- `uv run ruff check .`、`uv run ruff format --check .`（194 files）、`uv run ty check`は成功し、全pytestは224 passed／1 skippedだった。
- `openspec validate isolate-historical-resume-structure-typeerror --strict`は成功し、`skip_specs: true`による既存`run-lifecycle`／`pdf-translation`契約への実装適合が受理された。
- Run metadata、Failure、workflow metadata、run log、historical checkpoint、page 2 checkpointおよびChange Evidenceの13 filesを、実Credential／endpointとraw／本文／画像／traceback sentinel 16件で走査し、漏えい0件だった。専用`translate-historical-*` temp directory残存も0件だった。
- `pyproject.toml`と`uv.lock`の差分は0件である。Data migrationはなく、Rollbackはlogger修正と追加Testだけを戻し、正本Run、外部exportおよびQdrant Collectionを保持する。新規Service／option／永続fieldはないため追加廃止処理はない。

### Sequential Temp-run Preflight

- 自動Gate後、他のPython、ModelおよびEmbedding処理は0件だった。LM Studioは`google/gemma4:12b`、context 30,208、parallel 1、queued 0／idleだった。
- 保存fingerprintと現在fingerprint、入力元／Run input copyと保存SHA-256、Database SHA-256 `0a35f0d6383c1fc46932e838f24c06a7f7fad36bf0014b2cc1c655084e0f19a0`は一致した。Runは`failed`／`STRUCTURE`のままである。
- SPLIT～LOADは313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`でbaselineと一致した。
- Docling `/health`はHTTP 200、Qdrant Collectionは読取り可能でpoints 1,009だった。Qdrant状態はfingerprintまたはResume拒否へ使用していない。
- Temp実機GateはSDK retry 0、Application retry 1、request timeout 900秒、Task deadline 21,600秒、全Model／Embedding同時request最大1とする。

### Sequential Temp-run Attempt

- 正本のread-only snapshotを一時Runへ複製し、path-rebase後の公開Lifecycleを実Modelで一度だけ開始した。STRUCTUREはpage 2のprivate checkpointを再利用し、未完351ページを完了した（所要5236.664秒）。TypeError、STRUCTURE Failureおよび正本書込みは発生しなかった。
- TRANSLATEへ進んだ後、Qdrant検索とLLM chunk処理を逐次実行し、atomic temp directoryへ7件のchunk Artifactが生成された。その後の実行セッションは終了し、finally cleanupにより一時Run rootは削除された。
- 終了時PTYから安全なsummary／Failure recordを回収できず、TRANSLATEの完了・失敗原因、最終Run status、usage、call countおよびwall timeの完全なEvidenceは得られなかった。このためTask 6.2および6.3を成功扱いにせず、正本公開Resume（Task 6.4）は実行しなかった。
- 正本Runのcheckpoint DB size／mtime、SPLIT～LOAD Artifact、公開STRUCTURE、Run outputおよび外部exportは実行前後で不変だった。追加Model request、同一Runの公開Resumeおよびtemp再実行は行わない。

## Verification Report: isolate-historical-resume-structure-typeerror

### Summary

| Dimension | Status |
| --- | --- |
| Completeness | FAIL — 20/25 tasks complete; temp実Model Gateの終端Evidence不足により6.2〜6.6未完了 |
| Correctness | FAIL — STRUCTURE TypeErrorはtemp public lifecycleで再発しなかったが、TRANSLATE終端と最終成果物を確認できていない |
| Coherence | PASS — read-only clone、path rebase、逐次実行、Atomic公開および一回限りGateの停止条件に適合 |

### CRITICAL

1. Task 6.2: temp public ResumeはSTRUCTURE 351ページ完了後にTRANSLATEへ進んだが、PTYから最終summary／Failure／usage／call countを回収できず、全Workflowの実Model Gate成功を証明できない。終了状態を安全な永続Evidenceへ記録できる実行境界を追加し、同じChangeでの追加Model requestは行わない。
2. Task 6.3: temp ResumeのTRANSLATE完了、Atomic最終Artifact、Qdrant write 0件および最終statusを確認できないため、正本公開Resume条件を満たしていない。
3. Task 6.4: Task 6.3が未達のため、同一Runへの公開CLI Resumeを実行していない。公開Resumeを行わない判断は正しいが、Changeは未完了である。
4. Task 6.5: 正本Resumeを行っていないため、進捗100%、最終Markdown／DOCX、表紙画像一回、本文1ページ目除外および外部exportのEvidenceがない。
5. Task 6.6: 最終受入判定は未完了であり、本Changeはarchiveしてはならない。TRANSLATE終端の診断性改善を次の独立Changeへ引き渡す。

### WARNING

- temp実行の標準出力をPTYだけへ依存したため、終了時の安全なResultが失われた。実行前にtemp外の秘密非含有status sinkまたは永続Eventを用意し、終了時に必ず状態を確定できるようにする。

### SUGGESTION

なし。

### Final Assessment

CRITICAL 5件。STRUCTUREでの元TypeErrorはloggerの数値argument型保持修正により回避でき、351ページの実Model処理を完了した。しかしTRANSLATE中にtemp実行が終了し、完全な終端Evidenceがないため、正本公開Resumeおよびarchiveは許可しない。
