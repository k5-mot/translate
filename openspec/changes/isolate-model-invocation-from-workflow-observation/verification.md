<!-- markdownlint-disable MD013 MD041 -->

## Apply Evidence

### Preserved Run Baseline

- Run ID／operation／status: `01a0c97c-f5cf-7031-b808-4ad545133925`／`translate`／`failed`（UUIDv7）。
- Input copy SHA-256: `0185cd9631266fad92ffcede31a447e51cffa94ee572308310a490dc78a74182`。`run.json`のsource hashと一致した。
- Fingerprint: `fdd0ce952338a28d78dc2d99e976c812f8bce23f85e79e250ecc1f54b3cece96`。
- Failure: `STRUCTURE`、page 3、target `page/3`、stage `text-invoke`、cause `TypeError`。finish reason、usageおよびfailure kindは未取得。
- LangGraph checkpoint: 9件、writes 51件。private STRUCTURE checkpointはversion 4のpage 2だけで、`.complete.json`、`audit.json`、`meta.json`、`page.json`の4 files。
- 完了済みSPLIT～LOAD: 313 files、relative path UTF-8 bytesとfile bytesをpath順に連結したaggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`。
- 公開STRUCTURE Artifact、Run output、外部export `outputs/sample-translation`はいずれも0 files。
- Baseline取得は読取り専用であり、Run、旧Run、外部exportおよびQdrant Collectionを変更・削除していない。

### Runtime Baseline

- LM Studio: `google/gemma4:12b`、context 30,208、parallel 1、queued 0、idle。
- Application Settings: context 30,208、output 16,384、image 2,048、request timeout 300秒、Task deadline 21,600秒、retry attempts 3。
- Runtime packages: LangChain OpenAI 1.6.2、OpenAI SDK 3.16.2、Langfuse 4.15.4、OpenTelemetry API／SDK 1.44.0。
- 実機probeとResume時だけprocess環境でrequest timeoutを900秒へ上書きし、製品既定値とfingerprintは変更しない。
- EvidenceにはCredential、endpoint、prompt、文書本文、raw response、reasoning本文、tracebackおよび画像binaryを記録していない。

### Failing-First Observation Boundary

- Test用`InMemorySpanExporter`を渡した実Langfuse 4.15.4 clientと、`httpx2.MockTransport`を渡した実ChatOpenAI／OpenAI SDK response stackを組み合わせた。Network接続は0件で、strict-schema completionを一件だけ返す。
- 修正前の公開Translation root観測ではModel handler内のOpenTelemetry current spanがvalidとなり、期待した`[False]`に対して`[True]`で失敗した。Provider callは1件、schema parse自体は成功した。
- workflow chain→Task span→generationの明示的detached三層Testは、修正前Adapterがgeneration／embedding以外のdetached観測を拒否するため`ValueError`で失敗した。
- child create／update／end障害後の親ContextVar resetを要求する3条件も同じ未対応境界で失敗した。既存Testはroot create／end、warning sink、Provider call 1件および秘密非出力を既に固定している。
- failing-first実行は2 failed／14 deselectedと3 failed／16 deselected。失敗出力にraw response sentinelとCredential値は含まれなかった。

### Non-Current Observation Hierarchy

- Adapterはdetached rootをLangfuse clientの`start_observation()`、detached childを親観測objectの`start_observation()`から作成し、製品ContextVarへ観測objectだけを束縛する。OpenTelemetry current contextは変更しない。
- 実Langfuse／OpenTelemetry exporter Testではworkflow→Task→generationの3 spansが同じtrace IDを持ち、Taskのparentはworkflow、generationのparentはTaskだった。Model handler内のcurrent spanはinvalid、Provider callは1件、Pydantic適合だった。
- child create／update／endの各障害はwarning一回へ縮退し、成功値または元の業務Errorを保持した。観測終了の成否にかかわらず親ContextVarをresetし、次の独立rootはclientから開始した。
- TranslationとComparison Reviewのroot workflowおよび全Task call siteを明示的detachedへ変更した。各WorkflowのIntegration Testはroot、途中Task、最終Taskを含む全観測でdetachedがtrueであることを確認した。
- Langfuse単体suiteは19 passed。Adapter retry、STRUCTURE checkpoint／診断、Failure、Resume、input manifest、fingerprint、Atomic公開、Workflowおよび成果物契約のfocused suiteは126 passed。
- `pyproject.toml`、`uv.lock`、Run schema、fingerprint、checkpoint v4、zero-thinking policy、strict schema、Model／token設定、CLIおよび逐次実行方針に本実装の差分はない。

### Automated Quality and Security Gate

- Focused pytest: 126 passed。実Langfuse hierarchy、Adapter retry、STRUCTURE checkpoint／診断、Failure、Resume、input manifest、fingerprint、Atomic公開、Translation／Comparison Review workflowおよび成果物契約を含む。
- Full quality: `ruff check .`成功、`ruff format --check .` 185 files、`ty check`成功、全pytest 208 passed／1 skipped。
- `openspec validate isolate-model-invocation-from-workflow-observation --strict`は成功した。`skip_specs: true`は既存`run-lifecycle`／`pdf-translation`への実装適合として受理された。
- `pyproject.toml`／`uv.lock`差分0件、OS固有の製品分岐追加0件、生成・一時FileのGit status混入0件。
- Change Evidence、Run metadata、Failure、workflow metadata、SQLite checkpoint、Run logおよびprivate page checkpointの10 filesとfocused Test outputを、`.env`由来の秘密／endpoint値と固定sentinel計18値でmemory上走査し、永続File leak 0件、Test output leak 0件だった。値自体は出力していない。
- Data migrationと個別廃止処理は不要である。Rollbackは本Changeの製品Code／Test commitを通常のGit操作で戻し、Run、checkpoint、外部exportおよびQdrant Collectionを保持する。

### Non-Current Short Provider Gate

- Preflight: LM Studio `google/gemma4:12b`、context 30,208、parallel 1、queued 0、idle。他のPython Translation processとModel／Embedding requestは0件だった。
- Conditions: application retry attempts 1、OpenAI SDK retry 0、request timeout 900秒、同時request 1、strict Pydantic schema、zero-thinking、実workflow→Task→generationのdetached三層観測。
- Result: Provider request 1件、HTTP成功、Pydantic適合、schema-valid、input 34／output 18／total 52 tokens、reasoning length 0、wall time 1.702秒。Model handler内のOpenTelemetry current spanはinvalid、三層すべての観測objectを作成し、Langfuse warningは0件だった。
- 製品の`_response_diagnostics()`はtruncationだけを`length`として返し正常終了を`None`へ正規化するため、追加requestを送らず、直近LM Studio request segment 81行をraw表示なしでallowlist集計した。`finish_reason=stop` 1、`length` 0、thinking budget 0 markers 1、strict schema markers 2、server-side `TypeError` 0だった。
- raw prompt、response、reasoning本文、Credential、endpoint、tracebackおよびserver log本文はconsole、RunまたはRepositoryへ保存していない。

### Sequential Real Page 3 Gate Preflight

- Short probe成功後にRunを再読込みし、status `failed`、保存fingerprintと現在fingerprintの一致、Run input copyのSHA-256一致、およびpage 2 checkpoint keyの現在実装との一致を確認した。checkpoint versionは4である。
- LM Studioは`google/gemma4:12b`、context 30,208、parallel 1、queued 0／idleだった。Applicationはcontext 30,208、output 16,384、image 2,048、Task deadline 21,600秒である。
- Page 3はRun外のOS一時directoryで実行し、OpenAI SDK retry 0、Application retry 1、request timeout 900秒、同時request 1とする。visionを一回実行し、失敗時だけ製品fallbackによりtextを一回実行する。失敗後の追加requestおよびRun Resumeは行わない。

### Sequential Real Page 3 Result

- 実workflow→Task→generationのdetached三層観測内で保存済みpage 3だけを逐次実行した。Vision 1 requestで成功し、text fallbackは0 requestだった。応答は`finish_reason=stop`、input 1,324／output 453／total 1,777 tokens、reasoning length 0、Pydantic適合、schema-valid、audit 4件である。
- 有界化後の画像は879 × 1,137 pixels（999,423 pixels）で、Model handler内のOpenTelemetry current spanはinvalidだった。観測objectは三層すべてで作成され、warning 0件、Task wall time 12.879秒、probe全体13.289秒だった。各responseは一度だけ消費した。
- ProbeはRun外のOS一時directoryだけへTask output 4 files／private progress 4 filesを作成し、終了時に全削除した。残存するprobe一時directoryは0件である。
- Probe後もRunは`failed`／`STRUCTURE`、保存Failureはpage 3／`text-invoke`／`TypeError`、LangGraph checkpoint 9件／writes 51件のままである。Private STRUCTURE checkpointはpage 2の4 filesだけで、公開STRUCTURE Artifact、Run output、外部exportはいずれも0 filesだった。
- SPLIT～LOADは313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`でbaselineから不変だった。Probe経路はQdrant Adapterを呼ばず、Qdrant writeは0件である。Qdrant外部状態はfingerprintおよびResume拒否判定へ含めない。
- Evidence、tasks、Run metadata、Failure、workflow metadataおよびpage 2 checkpointの9 filesをCredential／endpoint／page本文／prompt／画像data URIの18 sentinelで走査し、漏えいは0件だった。Raw response、reasoning本文、tracebackおよび画像binaryは保存していない。

### Public Resume Preflight

- Page 3成功後に保存fingerprintと現在fingerprint、Run input copyと保存SHA-256、およびSPLIT～LOAD baselineの一致を再確認した。他のPython processは0件だった。
- LM Studioは`google/gemma4:12b`、context 30,208、parallel 1、queued 0／idleである。Docling healthはHTTP 200、Qdrant Collectionは読取り可能でpoints 1,009だった。Qdrant状態はResume互換性には使用していない。
- 公開Resumeではprocess環境だけrequest timeout 900秒とし、Applicationの有限retry 3、OpenAI SDK retry 0、Model／Embedding同時request最大1を維持する。条件がすべて成立したため、同じRun IDを公開CLIから一度だけResumeできる。

### One Allowed Public Resume

- 公開CLIの`translate inputs/sample.pdf --output-dir outputs/sample-translation --resume <run-id>`を一度だけ実行した。別Runは作成せず、request timeout 900秒、Application retry 3、SDK retry 0、parallel 1を使用した。
- Result: exit code 1、total wall time 55.778秒。Runは`failed`／`STRUCTURE`、page 3、target `page/3`、stage `text-invoke`、cause `TypeError`で停止した。finish reason、usageおよびfailure kindは取得されなかった。設計どおり追加Resumeは実行していない。
- 終了後のLM Studioは対象Model、context 30,208、parallel 1、queued 0／idleへ戻った。Runは同じFailureとfingerprintを保持し、再開可能である。

### Failed Resume Artifact and Lifecycle Audit

- LangGraph checkpoint 9件／writes 51件、private STRUCTURE checkpointはpage 2の4 filesだけだった。Page 3 checkpoint、公開STRUCTURE Artifact、Run outputおよび外部exportは0 filesで、部分成果物は公開されていない。
- 既完了SPLIT～LOADは313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`で不変だった。Run、外部exportおよびQdrant Collectionの自動削除は0件である。
- Translationが未完了のため、進捗100%、最終Markdown／DOCX、表紙画像一回、本文1ページ目除外およびAtomic最終Artifactは未達であり、成功扱いにしない。Word-to-PDF変換、利用者の目視比較およびComparison Reviewも未実施である。

### Final Quality, Security and Decision

- 最終Gateは`ruff check .`成功、`ruff format --check .` 185 files、`ty check`成功、全pytest 208 passed／1 skipped、strict OpenSpec validation成功だった。Dependency追加とOS固有製品分岐はない。
- Changed files、Run metadata、Failure、workflow metadata、Run logsおよびpage 2 checkpointの17 filesをCredential／endpoint／page本文／prompt／画像data URIの18 sentinelで走査し、漏えいは0件だった。`git diff --check`も成功した。
- Non-current観測階層、fail-open cleanup、offline回帰、short probeおよび単独page 3は期待どおり機能した。しかし、公開Workflowは同じpage 3で`text-invoke`／`TypeError`を再現したため、本Changeの公開Resume受入は未達である。Apply tasksは実証と停止条件を含め23/23完了とするが、verifyはCRITICAL、archive不可と判定し、公開Workflow固有差分を次の独立Changeへ引き渡す。

## Verification Report: isolate-model-invocation-from-workflow-observation

### Summary

| Dimension | Status |
| --- | --- |
| Completeness | PASS — 23/23 tasks complete、delta requirements 0件（`skip_specs: true`） |
| Correctness | FAIL — non-current観測契約はTestと単独pageで成立したが、公開Resume受入は未達 |
| Coherence | PASS — 設計した逐次Gate、一回限りのResume、Failure保持および次Changeへの引渡しに適合 |

### CRITICAL

1. 公開Workflowは、単独page 3がVision 1 requestでschema-validに成功した直後でも、同じRunの明示ResumeではSTRUCTURE page 3の`text-invoke`／`TypeError`で停止した。提案のQ-FUNC「公開ResumeがSTRUCTUREの応答後境界を通過する」を満たしていない（`proposal.md:43`、`verification.md:79`）。Archive前に、実LangGraph node／checkpoint／Task wrapperを通る公開Workflow固有境界をNetworkなしの失敗先行Testで再現し、TypeErrorの発生元を安全な型・stage・call countへ限定してから、実証された境界だけを次の独立Changeで修正すること。

### WARNING

なし。

### SUGGESTION

なし。

### Final Assessment

CRITICAL 1件。23件のApply taskとnon-current観測実装は完了しているが、公開Resume受入が未達のためarchiveしてはならない。保存Runへ追加Resumeを行わず、公開Workflow固有差分を診断・修正する独立Changeを提案する。
