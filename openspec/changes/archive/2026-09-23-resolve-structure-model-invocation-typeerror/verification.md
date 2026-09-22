<!-- markdownlint-disable MD013 MD041 -->

## Status

- Date: 2026-09-23
- Progress: 12/12 tasks complete
- State: the reproducible SDK length exception is normalized at the product boundary with a failing-first test; the historical Run is preserved without another Resume

## Preserved Run Baseline

- Run ID: `01a0c97c-f5cf-7031-b808-4ad545133925`（UUIDv7）
- Operation／status: `translate`／`failed`
- Fingerprint SHA-256: `fdd0ce952338a28d78dc2d99e976c812f8bce23f85e79e250ecc1f54b3cece96`
- Source and Run input copy SHA-256: `0185CD9631266FAD92FFCEDE31A447E51CFFA94EE572308310A490DC78A74182`（一致）
- Failure: `STRUCTURE` page 3、`page/3`、`text-invoke`、`TypeError`
- Checkpoints: 9、checkpoint writes: 51
- 完了済みSPLIT〜LOAD Artifact: 313 files、aggregate SHA-256 `6769262F16739771F1EC5FB9E1EEC7E07298E204A3348F6BE9E091D22D924D4A`、最新更新2026-09-22 23:48:35 JST
- STRUCTURE公開Artifact: なし。Run outputs: 0 files。指定外部export先`outputs/sample-translation`: 未作成
- 旧Run `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`の最終file更新: 2026-09-21 10:10:51 JST
- Baseline取得ではRun／旧Run／外部exportを変更していない

## Local Model Conditions

- Model: `google/gemma4:12b`、同時処理中request 0件
- 調整前: LM Studio管理context 8,192、推論process `--ctx-size 8192`、parallel 4
- 調整後: LM Studio管理context 30,208、推論process `--ctx-size 30208`、parallel 1、queued 0、idle
- Application: context 30,208、最大出力16,384、既定request timeout 300秒、Task deadline 21,600秒、retry attempts 3
- Probe／後続Resumeではprocess環境の`TRANSLATE_REQUEST_TIMEOUT_SECONDS=900`を使用する。製品既定値とRun fingerprintは変更しない
- raw prompt、文書本文、reasoning content、raw response、Credential、endpointおよび画像binaryはEvidenceへ保存していない

## Sequential Page 3 Probes

### Text-only `structured()`

- Requests／attempts: 1、同時実行数1
- Request timeout: 900 seconds
- Result: success、schema-valid、patch 1件、response body非空（331文字）
- Finish reason: `stop`
- Input tokens: 1,328、output tokens: 7,671、total tokens: 8,999
- Wall time: 212.049 seconds
- Exception chain／origin／HTTP status: なし
- 先行した直接`_model().invoke()` probeも成功しており、`structured()` text-only経路の常時失敗は再現しなかった

### Vision `structured()`

- Requests／attempts: 1、同時実行数1
- Request timeout: 900 seconds
- Result: `vision-invoke`で`OpenAIInvalidRequestError`、HTTP statusあり、schema応答なし
- Wall time: 7.099 seconds
- Input／output／total usage、finish reason: 応答前の拒否のため取得不可
- 入力画像: 1,020 × 1,320 pixels（1.3464 megapixels）、PNG 542,237 bytes。画像binary自体はEvidenceへ保存していない
- 直後にlocal `llama-server.exe`が終了し、LM Studioのloaded model一覧は空になった
- 2026-09-23のlocal server logには`llama-context.cpp`の`n_ubatch >= n_tokens`を要求する非causal attentionのassertion失敗と、続く`TypeError`が記録されている。raw log行とexception messageはEvidenceへ転記していない

## Cause Classification

Text-onlyの`structured()`は成功した一方、visionではlocal推論processがassertionで終了した。これは画像requestを受けたlocal runtime／Model組合せの障害と判断する。LangChainはserver側の拒否を`OpenAIInvalidRequestError`へ正規化しており、製品のparserが`TypeError`を生成した証拠はない。前回Runのtext fallback `TypeError`が同じruntime終了に続いたかは保存済み診断だけでは確定できない。

上流の[llama.cpp Gemma4高解像度画像issue](https://github.com/ggml-org/llama.cpp/issues/28954)は、1.2 megapixels超の画像で同じassertionが起き、1.15 megapixels未満で回避したと報告している。今回の1.3464 megapixelsとassertion一致から、同系統のruntime回帰である可能性が高いという推論である。製品コードに推測の回避策はまだ加えない。

## Additional Controlled Probe and Scope Decision

- LM Studioの公開Model load APIで`context_length=30208`、`eval_batch_size=2048`、flash attention有効を指定して再ロードした。管理APIは設定を受理したが、推論processの実引数ではphysical micro-batchが512のままで、parallelも4だった。assertionに必要なphysical micro-batchの改善を確認できないため、元画像で再probeしなかった。
- そのModelをunloadし、元のModel identifier、context 30,208、parallel 1で再ロードした。他のLLM／Embedding呼出しはない。
- page 3画像だけを108 DPIのOS一時directoryへ描画した。1,090,584 pixels（約1.09 megapixels）。入力文書、RunのArtifact、製品コードは変更していない。
- 同じpage 3 payload、rules、`structured()` vision経路を逐次1 request／1 attempt、900秒timeoutで実行した。結果は`vision-output`／`LLMOutputTruncatedError`、約414.36秒。高解像度probeの即時runtime終了は再現せず、Model応答までは進んだがschema-valid outputは得られなかった。
- よって、画像サイズとruntime assertionの関連は強まったが、画像解像度を下げるだけではSTRUCTURE完了を保証できなかった。この時点では現Changeの「環境原因なら製品コードを変更せず設定処置で解消」というTask 3.1を満たせず、変更範囲の判断待ちとしてRun Resumeを行わなかった。その後に再現した製品側の診断不具合と完了根拠は、後段のCause-Specific Correction Completionに記録する。

## Subsequent Correction and Automated Gate

- 後続Change `bound-structure-vision-and-recover-truncation`で、vision入力を1,000,000 pixels以下へ有界化し、vision出力枯渇後の完全なtext-only回復、非公開page checkpointおよびTask全体のAtomic公開を実装した。公開CLI、fingerprint、Model、Dependencyおよび逐次実行契約は変更していない。
- vision成功、vision失敗後text成功、両方失敗、旧Failure読取り、Atomic Artifactおよびfingerprint不変を含むfocused Testは37 passed。
- `ruff check .`、`ruff format --check .`（157 files）、`ty check`は成功。archive後の固定pathを修正した後の全pytestは181 passed、1 skipped。Change strict validationは成功し、Dependency差分は0件。
- Resume前後のRun診断File scanはCredential、endpointおよびraw sentinel検出0件。Model／Embedding呼出しはparallel 1で逐次実行した。

## One Allowed Explicit Resume

- Preflight: LM Studio管理値と推論processのcontextはいずれも30,208、parallel 1、queued 0／idle、Modelは`google/gemma4:12b`。900秒request timeoutを設定した現在fingerprintは保存値`fdd0ce952338a28d78dc2d99e976c812f8bce23f85e79e250ecc1f54b3cece96`と一致した。
- Sanitized operation: 公開CLIの`translate inputs/sample.pdf --output-dir outputs/sample-translation --resume <run-id>`を一度だけ実行。別Runは作成していない。
- Result: exit code 1、total 1,645.108秒。Runは`failed`／`STRUCTURE`を保持し、page 3、target `page/3`、stage `text-invoke`、cause type `TypeError`で停止した。finish reason、usageおよびfailure kindは取得されなかった。
- Resume境界: page 2だけが検証済み非公開checkpointとしてAtomic確定し、page 3のcheckpoint、公開STRUCTURE Artifact、Run outputおよび外部exportは0件。
- 成功済みSPLIT〜LOADは313 files、同じ算出方法によるaggregate SHA-256 `E70724F50CF1C24D12E339D135488D8C4513009F99F24EE6F46C5BB47F1DDF64`、latest mtime `2026-09-22T14:48:35.1483938Z`でResume前後不変。
- 終了後、LM Studioはidle、queued 0、parallel 1へ戻った。追加Resumeは実行していない。

## Cause-Specific Correction Completion

- 後続の実page 3 probeでは、visionとtextの両経路が`finish_reason=length`で停止し、OpenAI SDKがAIMessage返却前に`LengthFinishReasonError`を投げる製品境界を再現した。これは、SDK由来の出力枯渇が安全なSTRUCTURE診断へ変換されず`invoke`失敗として露出する、再現可能な製品側の診断不具合である。
- `tests/test_adapter_retry.py`へSDKの実返却形を模したfailing-first Testを追加し、`translate/adapters/llm.py`では例外classのmodule／nameを限定して、raw completionを読取り・保存せずfinish reasonと数値usageだけを抽出する最小修正を行った。対象は`LengthFinishReasonError`だけであり、未知の`TypeError`一般や他のProvider例外は握りつぶさない。
- 修正後は`text-output`／`LLMOutputTruncatedError`／`output-truncated`へ正規化され、有限retry、既存AIMessage truncation、permanent HTTP 400およびFailure伝播の契約を維持する。
- 再検証はfocused 40 passed、全体195 passed／1 skipped、`ruff check .`、`ruff format --check .`（165 files）、`ty check`および本Changeのstrict validationがすべて成功した。Dependency、公開CLI、Run layout、fingerprintおよび並列度は変更していない。
- Designの一回限りのResume制約と後続Changeの停止条件に従い、修正後の追加Model requestおよび同一Run Resumeは実行していない。保存済みRun、Failure、Artifactおよび外部exportを変更しないためである。

## Completion and Handoff

本Changeが対象とした再現可能な製品側のinvoke診断不具合は、限定的なSDK length正規化と回帰Testにより解消し、Task 3.1を含む12件を完了した。一方、実page 3はreasoning tokenの出力枯渇により完全schemaを生成できておらず、Translation全体の成功を意味しない。この残存課題は`bound-structure-reasoning-and-schema-output`のEvidenceと未完了Taskへ引き渡し、同Changeの停止条件に従って別の修正なしにRunを再開しない。Word-to-PDF変換、目視比較およびComparison Reviewも完了扱いにしない。

## Verification Report: resolve-structure-model-invocation-typeerror

### Summary

| Dimension | Status |
| --- | --- |
| Completeness | PASS — 12/12 tasks complete、delta requirements 0件（`skip_specs: true`） |
| Correctness | PASS — SDK length再現、限定正規化、retry／truncation／Failure回帰をTest済み |
| Coherence | PASS — failing-first、raw値非保持、有限retry、逐次実行、一回限りのResume制約に適合 |

### CRITICAL

なし。

### WARNING

なし。

### SUGGESTION

なし。

### Final Assessment

全検査に合格した。本Changeはarchive可能である。実PDF Translationの成功判定は本Changeの範囲外であり、後続Changeの未完了Taskとして維持する。
