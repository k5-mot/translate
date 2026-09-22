<!-- markdownlint-disable MD013 MD041 -->

## Apply Evidence

### Safe Historical Response Reclassification

- 2026-09-23のlocal server logをread-onlyで解析した。Parserはrequest key、boolean／number、finish reason、content／reasoning長および数値usageだけを出力し、raw line、prompt、文書本文、response本文、reasoning本文、Credential、endpointおよび画像binaryを表示・保存していない。
- 対象のvision／text requestはいずれも`model`、`max_tokens`、`messages`、`response_format`、`temperature`および`chat_template_kwargs`を持ち、`enable_thinking=false`、`max_tokens=16384`だった。`thinking_budget_tokens`と`reasoning_effort`はProvider request logに存在しなかった。
- Vision responseは`finish_reason=length`、content 0文字、reasoning 58,715文字、prompt 1,324／completion 16,384／total 17,708／reasoning 16,381 tokensだった。
- Text responseは`finish_reason=length`、content 0文字、reasoning 56,993文字、prompt 890／completion 16,384／total 17,274／reasoning 16,381 tokensだった。
- したがって先行probeの`ValidationError`表示は空contentをfinish reasonより先に検証したharnessの誤分類であり、両responseの正しい分類は`output-truncated`である。

### Preserved Run Baseline

- Run ID／operation／status: `01a0c97c-f5cf-7031-b808-4ad545133925`／`translate`／`failed`。Fingerprintは`fdd0ce952338a28d78dc2d99e976c812f8bce23f85e79e250ecc1f54b3cece96`。
- SourceとRun input copyのSHA-256はいずれも`0185cd9631266fad92ffcede31a447e51cffa94ee572308310a490dc78a74182`。
- Failureは`STRUCTURE` page 3、target `page/3`、stage `text-invoke`、cause type `TypeError`。Graph checkpointは9件、writesは51件。
- SPLIT～LOADは6 Task directories、313 files。`.workspace/`からのrelative path UTF-8 bytesとfile bytesをpath順に連結したaggregate SHA-256は`2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtimeは`2026-09-22T14:48:35.1483938Z`。
- Private STRUCTURE page checkpointはpage 2の1件。公開STRUCTURE Artifactはなく、Run outputは0 files、外部export `outputs/sample-translation`は存在しない。
- LM Studioは`google/gemma4:12b`、context 30,208、parallel 1、queued 0／idle。他のloaded Model／Embeddingはない。
- Baseline取得ではRun、Artifact、外部export、Qdrantおよびruntime設定を変更していない。process command lineはEvidenceへ保存していない。

### Failing-First and Focused Contract Gate

- `disabled` policyにJSON numberの`thinking_budget_tokens=0`がないこと、およびprivate page checkpointがversion 3のままであることを2件の失敗先行Testで再現した。
- Adapterの`disabled` branchだけへtop-level budget 0を追加し、既存の`reasoning_effort=none`と`chat_template_kwargs.enable_thinking=false`を維持した。`provider-default` branch、公開設定、prompt、native API、Dependencyおよびglobal Model設定は変更していない。
- `PAGE_CHECKPOINT_VERSION`を4へ更新し、固定zero-budget値をprivate page keyへ含めた。公開Run fingerprintは変更していない。
- Adapter、STRUCTURE checkpoint／diagnostics、Failure、Translation workflow、workflow stateおよびfingerprintのfocused pytestは59 passed。vision→textは逐次で、vision成功、vision失敗後text成功、両方失敗、AIMessage／SDK length、permanent 400、Atomic publishおよび秘密非出力を確認した。

### Automated Quality, Security and Lifecycle Gate

- Adapter、STRUCTURE、checkpoint、Failure、Resume、workflow、Atomic Artifactおよびfingerprintを対象に広げたfocused pytestは81 passed。
- `uv run ruff check .`、`uv run ruff format --check .`（177 files）、`uv run ty check`および全pytest（196 passed、1 skipped）は成功した。
- Dependency manifest／lock、公開fingerprint／lifecycleおよび公開entry pointの差分は0件。製品変更はAdapterのprivate request bodyとSTRUCTURE private checkpoint policyに限定される。
- Changeのstrict validationは成功した。Data migrationは不要で、version 3以前のprivate page checkpointだけをkey不一致として再計算する。RollbackはCode commitを戻し、Run、外部exportおよびQdrantを保持する。新規Service／Package／公開optionがないため個別廃止処理は不要である。
- Verification、Run metadata、Failure、workflow、Run logおよびprivate checkpoint metadataの6 filesをCredential、endpoint、raw／secret sentinel、reasoning content、tracebackおよび画像dataの固定patternで走査し、検出0件だった。

### Short Provider Gate Preflight

- Loaded instanceは1件だけで、LLM `google/gemma4:12b`、context 30,208、parallel 1、queued 0／idle。Embedding instanceは0件だった。
- 固定短文と実`StructureResponse` strict schemaを使い、application attempt 1、SDK retry 0、request timeout 900秒、同時request 1で一回だけ送信する。Langfuseはprobe用Settingsで無効化する。
- 送信前server log offsetは1,216,697 bytes／4,599 lines。以後の解析はこのoffsetより後のrequest／responseに限定し、allowlist metadataだけを扱う。

### Short Provider Gate Result

- 固定短文を一回だけ送信し、1.248秒で成功した。Application attemptは1、strict `StructureResponse`へ適合し、patchは0件だった。
- 送信後server logは1,222,267 bytes／4,770 lines。開始offset以後のrequestは1件だけで、request keysは`chat_template_kwargs`、`max_completion_tokens`、`messages`、`model`、`response_format`、`temperature`および`thinking_budget_tokens`だった。
- `thinking_budget_tokens`はJSON integerの0、`enable_thinking=false`、message 2件、strict response formatあり。Provider logでは`reasoning_effort`は正規化後のrequest keyに存在しなかった。
- Responseは`finish_reason=stop`、content 19文字、reasoning 0文字、prompt 29／completion 22／total 51／reasoning 0 tokens。Modelは実行後もcontext 30,208、parallel 1、queued 0／idleだった。
- ParserとEvidenceはrequest／response本文、raw log line、reasoning本文、Credential、endpointおよび画像binaryを保存していない。Evidenceの固定秘密／raw pattern scanは0 findingsだった。

### Real Page 3 Gate Preflight

- Runの保存fingerprintと現在fingerprintはともに`fdd0ce952338a28d78dc2d99e976c812f8bce23f85e79e250ecc1f54b3cece96`で一致し、入力hashも一致した。
- LM Studioはloaded instance 1件、`google/gemma4:12b`、context 30,208、parallel 1、queued 0／idleを維持していた。
- 保存済みLOAD Documentのpage 3をRun外のOS一時directoryへ描画し、製品の1,000,000 pixels上限を適用する。Visionを一回、失敗時だけtextを一回、application attempt 1、SDK retry 0、timeout 900秒、同時request 1で逐次実行し、Run／Artifactへ書き込まない。
- 送信前server log offsetは1,224,649 bytes／4,786 lines。このoffset以後だけをallowlist解析する。

### Real Page 3 Gate Result

- 保存済みpage 3を999,423 pixelsへ有界化し、visionを一回だけ送信した。13.470秒でstrict `StructureResponse`へ適合し、patch 4件を得た。Visionが成功したためtext fallbackは送っていない。全体wall timeは13.660秒だった。
- 開始offset以後のProvider requestは1件。RequestにはJSON integerの`thinking_budget_tokens=0`、`enable_thinking=false`およびstrict response formatが到達した。
- Responseは`finish_reason=stop`、content 1,564文字、reasoning 0文字、prompt 1,324／completion 453／total 1,777／reasoning 0 tokens。Parserはcontentとreasoning本文を表示・保存していない。
- Probe後もRunは`failed`／`STRUCTURE`、保存Failureはpage 3／`text-invoke`／`TypeError`、private checkpointはpage 2の1件、公開STRUCTUREはなし、Run output 0 files、外部exportなしだった。
- SPLIT～LOADは313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`でbaselineと一致した。一時directoryは自動破棄され、Runへprobe Artifactを書き込んでいない。
- Qdrantのread-only exact countは現在1,009 pointsで、過去Evidenceの1,079 pointsから外部状態が変化している。本probeはQdrant module／clientを呼ばずwrite 0件であり、この外部変更は既決契約どおりfingerprintまたはResume拒否条件に含めない。

### Explicit Resume Preflight

- 実page 3成功後も保存／現在fingerprintとinput SHA-256は一致し、SPLIT～LOAD 313 filesのaggregate／mtimeはbaselineと一致した。
- LM Studioは対象Model、context 30,208、parallel 1、queued 0／idle。short probeとpage 3の双方でOpenAI互換request／strict schema／zero-budget contractを実証した。
- Qdrantはread-only exact countを取得できた。状態変化は許容しfingerprintへ含めない。Docling以前のTaskは完成済みcheckpointを再利用するため、Resume前のDocling requestは不要である。Langfuseは障害時も警告だけで継続する既存契約を維持する。
- 全条件が成立したため、`TRANSLATE_REQUEST_TIMEOUT_SECONDS=900`をprocess内だけに設定し、公開CLIから同じRun IDを一度だけ明示Resumeする。別Runと並列Model／Embedding requestは作成しない。

### One Allowed Explicit Resume Result

- 公開CLIは同じRun IDを`mode=resume`で開き、55.063秒後に終了した。別Runは作成していない。設計の一回制約に従い追加Resumeを行わない。
- Runは`failed`／`STRUCTURE`を保持し、Failureはpage 3、target `page/3`、stage `text-invoke`、cause type `TypeError`。finish reason、usageおよびfailure kindは保存Failureにない。
- Resume中のProvider requestは6件で全て逐次だった。全requestにJSON integerのbudget 0、template hintおよびstrict response formatが到達し、全responseが`finish_reason=stop`、reasoning 0だった。Prompt／completion／total tokensは有限だった。
- 保存済み6 responseをofflineで本文非表示のまま`StructureResponse`へ検証し、vision 3件／text 3件の全てがschema-validだった。したがって今回のTypeErrorはreasoning枯渇、Provider拒否、length終了またはschema不適合ではなく、Provider response受領後のclient invoke境界で発生している。
- Direct page 3 probeはLangfuseを無効化して成功し、公開CLIではLangfuseが有効だった。この差は次の診断対象だが、観測機構が原因とはまだ断定しない。追加Model requestなしで安全なoriginを特定し、観測障害を製品処理から分離する別Changeへ引き渡す。
- Page 2だけがversion 4／現在policy一致のprivate checkpointとしてAtomic確定した。Page 3 checkpoint、公開STRUCTURE、Run outputおよび外部exportは0件。
- SPLIT～LOADは313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`で不変。Fingerprintとinput hashも一致した。
- 終了後のLM Studioはloaded instance 1件、context 30,208、parallel 1、queued 0／idle。Run、入力copy、外部exportおよびQdrantを自動削除していない。

### Apply Assessment and Handoff

- 本Changeのzero-budget contractはshort probeと実page 3の両方で実証され、reasoning枯渇を解消した。一方、公開Workflowはschema-valid Provider response後の`TypeError`で完了していない。
- Apply checklistは失敗時の安全な停止、保存状態監査および引渡しまで完了したが、製品受入は失敗である。Verifyはこの残存不具合をCRITICALとして扱い、本Change単独をarchive可能と判定しない。
- 後続Changeでは、Langfuse有効／無効差分とProvider response後の例外originをraw値なしで再現し、観測障害が製品処理を失敗させない境界をfailing-first Testで固定する。保存済みRunへの追加Resumeは、その修正と実page gateが成功するまで行わない。
- Word-to-PDF変換、利用者の目視比較およびComparison Reviewは未完了であり、本Changeでは完了扱いにしない。

## Verification Report: enforce-structure-zero-thinking-budget

### Summary

| Dimension | Status |
| --- | --- |
| Completeness | PASS — 22/22 tasks complete、delta requirements 0件（`skip_specs: true`） |
| Correctness | FAIL — zero-budget contractは実証済みだが、公開WorkflowはSTRUCTUREで停止 |
| Coherence | PASS — request policy、checkpoint v4、逐次gate、一回Resumeおよび失敗時保存はDesignどおり |

### CRITICAL

1. 公開CLIの同一Run Resumeが、6件のProvider responseすべてでbudget 0、`finish_reason=stop`、reasoning 0およびschema適合を得た後にも、page 3の`text-invoke`／`TypeError`で停止した（`verification.md:75`、`verification.md:78`、`verification.md:80`）。既存`pdf-translation` capabilityの検証済みDOCX生成まで到達していないため、本Changeをarchiveしてはならない。
   - Recommendation: 別ChangeでLangfuse有効／無効差分とProvider response後の例外originをraw値なしのfailing-first Testへ固定し、`translate/adapters/llm.py:417`の観測境界がschema-valid resultを失敗へ変換しないよう最小修正する。自動品質gate、観測有効の短いprobe、実page 3を順に成功させた後だけ、保存済みRunを公開CLIから一度Resumeする。

### WARNING

なし。

### SUGGESTION

なし。

### Verification Evidence

- Request実装: `translate/adapters/llm.py:245-250`。`disabled` policyだけにtemplate hintとJSON integer budget 0を追加している。
- Private migration boundary: `translate/tasks/structure.py:77-82`および`translate/tasks/structure.py:118-139`。checkpoint version 4とbudget値をkeyへ含めている。
- Contract Test: `tests/test_adapter_retry.py:109-133`および`tests/test_structure_checkpoints.py:52-90`。
- 現HEADの`ruff check`、`ruff format --check`（177 files）、`ty check`、全pytest（196 passed、1 skipped）およびstrict validationは成功した。
- Dependency、公開CLI、公開Run fingerprintおよび並列度は変更していない。ユーザー変更の`AGENTS.md`と`openspec/config.yaml`は検証対象commitへ含めていない。

### Final Assessment

CRITICAL 1件。zero-budget修正自体は正しいが、公開Workflowが完了していない。Provider response後の`TypeError`を別Changeで解消し、実Run成功を確認するまでarchive不可である。
