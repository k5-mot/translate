<!-- markdownlint-disable MD013 MD041 -->

## Status

- Date: 2026-09-23
- Progress: 9/12 tasks complete。実Runのpage 3 probeは部分成功、明示Resumeは未実施。
- Scope: 画像上限、完全なtext-only回復、非公開page checkpoint、STRUCTURE documentのatomic publish。

## Implementation Evidence

- 元のpage 3画像: 1,020 × 1,320 pixels。STRUCTUREへの送信前: 879 × 1,137 pixels、999,423 pixels、縦横比差0.00036。画像の四隅を保持する合成page Testは成功し、COVERの150 DPIは不変。
- visionの`output-truncated`では同じrequestをretryせず、切れた応答を採用しない。完全なtext-only応答だけで回復する成功／両失敗／画像準備失敗のfocused Testは成功。
- 各page checkpointはsource PDF、入力page、rules、Model、endpoint、token設定、画像上限をhash keyへ結び付け、page／auditのSHA-256とcomplete markerを検証してから再利用する。metadataには本文、Model名、endpointを平文で保存しない。失敗中の公開STRUCTURE directoryは存在せず、完了時だけ`document.json`とpage／auditを一括公開する。
- 入力PDF差分、Model差分、破損page、旧Runにprogressがない場合および失敗後ResumeのTestは成功。互換な完了pageの再推論0件、破損checkpoint採用0件。
- 先行`align-llm-token-budget-and-truncation-diagnostics`の保留中deltaを、STRUCTUREの完全な別mode回復だけ例外とする文言へ整合。両Changeのstrict validationは成功。

## Quality and Security Gate

- `ruff check .`: pass
- `ruff format --check .`: pass（149 files）
- `ty check`: pass
- Focused STRUCTURE Test: 13 passed
- Full `pytest -q`: 178 passed、1 skipped
- `openspec validate bound-structure-vision-and-recover-truncation --strict`: pass
- Dependency差分: 0件。新しいModel／Embedding並列処理: 0件。
- Test出力、既存Run Failure／run.logおよび43件のpage checkpoint metadataをCredential、endpoint、prompt、本文、reasoning、raw応答、画像binaryのsentinelで走査し、検出0件。raw値はEvidenceへ転記していない。

## Pending Real-Run Verification

既存Run `01a0c97c-f5cf-7031-b808-4ad545133925`はまだResumeしていない。Resume前のread-only gateでは、LM Studioの管理値・推論processのcontextが共に30,208、parallel 1、queued 0／idle、現在のRun fingerprintとの完全一致、差分0件を確認した。既完了SPLIT〜LOADは313 files、相対pathとfile SHA-256から算出したaggregate SHA-256は`F45B6BD83048A6293F9267E3F8B2BD561171C94920F781A308C095B73325537F`。Runは`failed`／`STRUCTURE`で、公開STRUCTUREとprivate page progressは共に存在しない。

page 3だけをOS一時領域で処理する有界画像probeは、約221.9秒で完全なschema適合応答とprivate page checkpointを得て成功した。mode別回数はこのprobeで計測していない。続く注入probeではvisionの`output-truncated`を一度だけ模擬し、text-onlyに実Modelを呼び出した。mode列は`vision,text`で同時実行なし、結果は約424.75秒後に`text-output`／`LLMOutputTruncatedError`で停止した。以前の同page text-only単発成功は再現性を保証しない。

Task 4.1の完全な別mode回復は実Modelで確認できず未完了とする。設計のgateに従って同RunをResumeしていない。probe後もRunは`failed`／`STRUCTURE`、既完了313 filesのaggregate SHA-256は不変で、公開STRUCTUREとprivate page progressは存在せず、Modelはidle／queued 0である。text-onlyの出力枯渇を解消する追加設計なしに、Task 4.2と4.3を完了扱いにしない。
