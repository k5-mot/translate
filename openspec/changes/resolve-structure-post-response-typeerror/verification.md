<!-- markdownlint-disable MD013 MD041 -->

## Apply Evidence

### Preserved Run Baseline

- Run ID／operation／status: `01a0c97c-f5cf-7031-b808-4ad545133925`／`translate`／`failed`（UUIDv7）。
- Input copy SHA-256: `0185cd9631266fad92ffcede31a447e51cffa94ee572308310a490dc78a74182`。`run.json`のsource hashと一致した。
- Fingerprint: `fdd0ce952338a28d78dc2d99e976c812f8bce23f85e79e250ecc1f54b3cece96`。
- Failure: `STRUCTURE`、page 3、target `page/3`、stage `text-invoke`、cause `TypeError`。finish reason、usageおよびfailure kindは未取得。
- LangGraph checkpoint: 9件、writes 51件。private STRUCTURE page checkpointはversion 4のpage 2だけで、`.complete.json`、`audit.json`、`meta.json`、`page.json`の4 files。
- 完了済みSPLIT～LOAD: 313 files、relative path UTF-8 bytesとfile bytesをpath順に連結したaggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`。
- 公開STRUCTURE Artifact、Run output、外部export `outputs/sample-translation`はいずれも0 files。
- Baseline取得前後でRun fileを変更していない。Run、外部exportおよびQdrant Collectionの削除も行っていない。

### Runtime Baseline

- LM Studio: `google/gemma4:12b`、context 30,208、parallel 1、queued 0、idle。
- Application Settings: context 30,208、output 16,384、request timeout 300秒、Task deadline 21,600秒、retry attempts 3。
- Runtime packages: LangChain OpenAI 1.6.2、OpenAI SDK 3.16.2、Langfuse 4.15.4。
- 実機probeとResume時だけprocess環境でrequest timeoutを900秒へ上書きし、製品既定値とfingerprintは変更しない。
- EvidenceにはCredential、endpoint、prompt、文書本文、raw response、reasoning本文、tracebackおよび画像binaryを記録していない。

### Offline Differential and Correction

- OpenAI SDK 3.16.2はlock済みruntime Dependencyのhttpx2を使用するため、計画中の`httpx.MockTransport`表記を実stackに一致する`httpx2.MockTransport`へ訂正した。Dependency fileは変更していない。
- failing-firstでは`observe()`にdetached modeがなく、generationがcurrent observationを使用したため、Langfuse focused suiteは8 failed／6 passedだった。
- strict-schemaのsynthetic completionを実`ChatOpenAI.bind(...).invoke()`へ渡すoffline fixtureを追加した。Network接続なしで観測なし／current／detachedの各Provider callは1件、Pydantic適合100%、current contextの観測値は順にfalse／true／falseだった。
- `observe()`のgeneration／embedding用detached modeはLangfuse `start_observation()`で作成し、処理Error時の`update()`と全経路の`end()`を明示する。Workflow／Task spanの`start_as_current_observation()`は維持した。
- `structured()`はgenerationだけをdetachedにし、Modelの有限retryを観測Failure domainから分離した。観測create／update／endのfault injection、warning sink、応答後end失敗、実SDK stackおよび秘密sentinelを含むLangfuse suiteは14 passed。
- Adapter retry、page checkpoint v4、zero-thinking budget、strict schema、Run fingerprint／input manifest／CLI-UI相互運用を含むfocused suiteは68 passed。観測終了失敗時のProvider callは1件、既存transport／parseの有限retryと恒久4xx即時停止は不変だった。
- `pyproject.toml`、`uv.lock`、`translate/tasks/structure.py`、Run schema、CLIおよび`main.py`に本Changeの差分はない。Model／Embeddingの並列要素も追加していない。
- focused Ruff、Formatおよび製品Codeのty checkは成功した。offline logへCredential、endpoint、prompt、raw response、reasoning本文、tracebackおよびmodule名のsentinel漏えいは0件だった。

### Automated Quality and Security Gate

- Focused pytest: Langfuse、Adapter、STRUCTURE checkpoint／診断、Failure、Resume、Translation workflow、Atomic公開、workflow stateおよびfingerprintの91 passed。観測終了fault時はProvider call 1件、transport／parse Failureは設定済み有限attemptだった。
- Full quality: `ruff check`成功、`ruff format --check` 181 files、`ty check`成功、全pytest 203 passed／1 skipped。
- `pyproject.toml`／`uv.lock`差分0件、OS固有の製品分岐追加0件、公開CLI／Run schema／fingerprint／checkpoint v4／zero-thinking policyの差分0件。
- Run metadata、Failure、workflow metadata、LangGraph checkpoint、private page checkpoint metadata、Run logおよびChange Evidenceの9 filesを、`.env`から値だけをmemoryへ読んだ6 Credentialと固定sentinelで走査し、Credential leak 0件、sentinel leak 0 filesだった。Credential値自体は出力していない。
- `openspec validate resolve-structure-post-response-typeerror --strict`は成功した。Data migrationと個別廃止処理は不要で、Rollbackは製品Code／Test commitだけを戻し、Run、checkpoint、外部exportおよびQdrant Collectionを保持する。

### Observation-Enabled Short Provider Gate

- Preflight: LM Studio `google/gemma4:12b`、context 30,208、parallel 1、queued 0、idle。Langfuseは有効。他のModel／Embedding requestは0件。
- Conditions: application retry attempts 1、OpenAI SDK retry 0、request timeout 900秒、同時request 1、STRUCTURE zero-thinking budget、strict `StructureResponse` schema、detached generation observation。
- Result: Provider calls 1、HTTP成功、`finish_reason=stop`、input 32／output 18／total 50 tokens、reasoning length 0、schema-valid、patches 0、wall time 1.924秒。
- Langfuse warning 0件。観測終了後もschema-validな成功値を保持した。prompt、response、reasoning本文、Credential、endpoint、tracebackおよびraw logは保存していない。

### Observation-Enabled Real Page 3 Gate

- Preflight: 現在fingerprintは保存値と一致。private page checkpointはpage 2だけで、製品定数と回帰Testによりversion 4。LM Studioは対象Model、context 30,208、parallel 1、queued 0、idle。
- Conditions: Run外のOS一時directory、application retry 1、OpenAI SDK retry 0、request timeout 900秒、同時request 1。vision失敗時だけtextを一回送る逐次条件とした。
- Result: vision Provider calls 1、text calls 0、`finish_reason=stop`、input 1,324／output 453／total 1,777 tokens、reasoning length 0、完全schema、Pydantic適合、page 3成功、wall time 13.432秒。Langfuse warning 0件。
- Probeは一時directoryに4 filesを生成して終了時に削除した。Runは`failed`のまま、page checkpointはpage 2の4 filesだけ、Run output 0 files、外部export 0 filesだった。
- SPLIT～LOADは313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`でprobe前後不変。Qdrant APIを呼ばないSTRUCTURE単体probeでwrite 0件。Qdrant状態はfingerprintへ含めていない。
- Failure file SHA-256は`41a41395c179f57fbc8941cc5363019d64420327d43fb7e84d0e6be0b7a0dc47`。安全なstage、target、finish reason、数値usage、reasoning長、schema適合、attemptおよびwall timeだけを記録し、秘密・本文・raw値は保存していない。

### Explicit Resume Preflight

- 現在fingerprintと入力SHA-256は保存値に一致し、SPLIT～LOAD 313 filesのaggregate／latest mtimeもbaselineと一致した。Runは`failed`／last task `STRUCTURE`。
- LM Studioは`google/gemma4:12b`、context 30,208、parallel 1、queued 0、idle。別のTranslation processは0件。
- Docling healthはHTTP 200、Qdrant Collectionは利用可能でpoints 1,009。Qdrantの現在points数は外部可変状態としてfingerprint／Resume拒否に使用していない。
- 公開Resume条件はrequest timeout 900秒、application retry attempts 3、Model／Embedding同時最大1件。同一Runを一度だけ明示Resumeする。

### One Allowed Public CLI Resume

- Sanitized operation: 公開`cli.py translate`へ`inputs/sample.pdf`、明示run IDおよび外部output directoryを指定し、request timeout 900秒で一度だけResumeした。新Runは作成していない。
- Result: exit code 1、total 56.855秒。Runは`failed`／`STRUCTURE`、page 3、target `page/3`、stage `text-invoke`、cause `TypeError`で停止した。finish reason、usageおよびfailure kindはclient側Failureへ渡らなかった。
- local server logの当該07:29 segmentをraw表示せずallowlist集計すると、received requests 6、`thinking_budget_tokens=0` 6、strict schema 6、`finish_reason=stop` 6、empty reasoning 6、length 0、server-side `TypeError` 0だった。vision 3 attemptsとtext 3 attemptsの全Provider応答後にclient境界で失敗したことを示す。
- Run warningは既存3件から`StructurePageError` 4件へ増え、Failure timestampとRun更新時刻だけが更新された。LangGraph checkpoint 9件／writes 51件、private page checkpointはpage 2の4 filesだけで、page 3と公開STRUCTURE Artifactは0件。
- SPLIT～LOADは313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`で不変。Run output 0 files、外部export 0 files、部分成果物0件、自動削除0件。
- 終了後はTranslation process 0件、LM Studioはcontext 30,208、parallel 1、queued 0、idle。追加Model requestと追加Resumeは実行していない。
- Run／Evidence 9 filesを6 Credential値と固定sentinelで再走査し、Credential leak 0件、sentinel leak 0 files。server logのraw prompt／response／reasoning／endpointはconsoleまたはRepositoryへ出力していない。

### Outcome and Handoff

- generation観測をnon-current lifecycleへ変えたこと自体は、offline actual SDK stack、fault injection、short Provider probeおよび直接page 3で機能した。しかし公開Workflowでは外側の`workflow.pdf-translation` chain観測がcurrent OpenTelemetry contextとして残るため、Model invokeは完全には観測contextから隔離されていない。
- 「外側current chainあり」が、成功した直接page 3と失敗した公開Resumeの残る主要差分である。Providerは6件ともstop／reasoning 0／strict schema応答を返し、server側TypeErrorは0件なので、次Changeでは実Langfuse／OpenTelemetry outer span内のactual SDK response processingを再現し、Model invoke中だけcurrent contextを安全に隔離するか、workflow観測をnon-current lifecycleへ移す必要がある。
- 本Changeの23 tasksは、定義した失敗時停止・保存・引渡しを含め完了した。一方、Q-FUNCの公開Resume通過は未達であり、verifyはCRITICAL失敗、archive不可と判定する。
- Translation、最終Markdown／DOCX、Word-to-PDF利用者操作、目視比較およびComparison Reviewは未完了であり、完了扱いにしない。
