<!-- markdownlint-disable MD013 MD041 -->

## 1. 空訳拒否の実装

- [x] 1.1 `tests/test_validate_contract.py`へ本文・図Caption・表Caption・結合セル起点のNone/空配列/空文字/空白/タブ/改行、最終訳と初回訳の優先順位の失敗Testを追加し、現実装で意図した失敗を確認する（Q-FUNC）
- [x] 1.2 `_require_translations()`を既存`block_text_units`・`inline_text`へ委譲し、非空白原文に対する選択訳層の欠落を拒否する。1.1と表紙/空原文除外/正常訳/原文と同一の数値・識別子のTestが成功することを確認する。セルIDは既存の行列形式へ統一する
- [x] 1.3 既存FIX skip警告、asset検査、TextUnit層選択、Markdown描画、独立Markdown→DOCX変換の回帰を実行し、新Dependency/Module/保存Schema/再開台帳が増えていないことを差分で確認する（Q-COMP/Q-MNT）

## 2. 公開・再開・安全性の統合検証

- [x] 2.1 実Translation Graphと実VALIDATEで欠落を発生させ、MARKDOWN/DOCX呼出0回、新しい成功reportなし、既存report/成果物hash不変、Checkpointの再開位置がvalidateであることを確認する。正常な合成Artifactによる別接続Resumeでは成功済み前段を再実行しないことを検査する（Q-REL）
- [x] 2.2 合成の本文/訳文/認証markerを含む失敗ケースで、公開診断、Failure、SQLiteとpending writesへのmarker追加保存0件を確認する。外部通信を禁止したTest境界と既存serializerを使用する（Q-SEC/Q-INT）
- [x] 2.3 Ruff check/format、ty、全pytest、OpenSpec strict validation、git diff --checkを実行し、Code版・対象範囲・結果をverification.mdへ記録する。新規/変更関数の目的説明、既存API委譲、無関係な差分と生成物の除外を確認する

## 3. 実受入と完了判定

- [ ] 3.1 LLM接続の回復確認後、sample3.pdfを新規処理として推論OFF・逐次でTranslationし、Microsoft WordでPDFへ変換し、元PDFと生成PDFをComparison Reviewする。入力/成果物hash・設定・終端・Run IDと空訳検査結果を記録する。失敗時は未完了を保持し、旧成果物を修正後の成功証拠へ流用しない
- [ ] 3.2 利用者へWord/PDFを提示して目視結果を記録し、Requirement/Scenarioと全Taskの証拠で正式verify・同期/archive可否を判定する。未完了項目を残したままarchiveせず、PR/CI→main merge/pushの条件と`.agents`・入力・PDF/DOCX・生成物の除外を確認する（供給・運用・保守・廃止）
