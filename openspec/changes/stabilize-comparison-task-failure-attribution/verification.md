<!-- markdownlint-disable MD013 MD041 -->

## Status

- Date: 2026-09-23
- Apply progress: 7/8 tasks complete。verify／archive引き渡しだけ未完了。
- Scope: 比較Reviewの完全逐次実行、失敗Task／入力role帰属、既存Resume境界。

## Root Cause Evidence

- 修正前の全pytestは同じprocess条件で成功と失敗が混在し、失敗時は`SOURCE-SPLIT`／`target_id`なし／`PermissionError`を記録した。単独の無効PDF Testは成功したため、入力内容や固定順序ではなく競合と判定した。
- raw messageを出さずに例外originのmodule／functionだけを一時収集した結果、`comparison_review.wrapped`の`started`通知から`lifecycle.task_status`、`RunRepository.save`、`atomic_write_bytes`の最終replaceへ至る経路で`PermissionError`を確認した。
- 比較Graphはsource／targetを同じSTARTから開始していた。両workerが同じ`run.json`を保存し、Windowsのatomic replaceが競合すると、active Failure作成前に外側fallbackへ進んで直前のTaskを誤帰属した。

## Correction and Contract Evidence

- Graphを`SOURCE-SPLIT → TARGET-SPLIT → source残Task → target残Task → ALIGN`へ接続した。両PDFを外部Service前に検証し、Run metadata、Docling、ModelおよびEmbeddingの同時実行要素を0件にした。
- source／targetの全nodeは独立したままで、checkpointとTask単位Resumeを維持する。target POSITIONの一回失敗後、source POSITION／LOADは各1回、target POSITIONだけ2回となる既存Integration Testが成功した。
- 比較SPLITが下位`target_id`を持つ場合はその値を維持し、欠落時だけ`source_en`／`translation_ja`を補うTestを追加した。公開Lifecycleで両入力roleの読取り不能PDFを検証し、Task／role一致、部分report 0件、Resume可能なfailed Runを確認した。
- 旧Failure JSON読取り、active Failure優先、外側fallback、Credential／本文redactionの既存Failure契約Testを含むfocused suiteは21 passed。

## Quality and Security Gate

- `ruff check .`: pass
- `ruff format --check .`: pass（153 files）
- `ty check`: pass
- Focused pytest: 21 passed
- Full `pytest -q`: 181 passed、1 skippedを5回連続で確認
- `openspec validate stabilize-comparison-task-failure-attribution --type change --strict --json`: pass（`skip_specs`のINFOだけ）
- Dependency差分: 0件。新しいModel／Embedding並列処理: 0件。Graphのwaiting edge: 0件。
- 最新pytest一時rootの`failure.json`、`run.log`、`run.json`をCredential、endpoint、本文sentinel、raw responseおよび画像data markerで走査し、検出0件。診断用raw tracebackは保存していない。

## Lifecycle and Handoff

既存Run、外部exportおよびQdrantには変更を加えていない。Data migrationは不要で、旧Failure readerを維持する。Rollbackは本ChangeのGraph edge、role fallbackおよびTest差分を通常のGit操作で戻す。保留中の`resolve-translate-contract-verification-gaps`も現行Gateで再verifyし、両Changeをarchive可能と判定した。

## OpenSpec Verify Report

| Dimension | Result |
| --- | --- |
| Completeness | 8/8 tasks。Spec deltaは契約変更なしの宣言どおりskip |
| Correctness | 逐次Graph、source／target role、Resume、旧Failureおよびredactionを実装・Testへ対応 |
| Coherence | Proposalと更新済みDesignに一致。既存のnode、checkpoint、Atomic Artifact patternを維持 |

- CRITICAL: 0件
- WARNING: 0件
- SUGGESTION: 0件

全検査に合格し、archive可能と判定する。
