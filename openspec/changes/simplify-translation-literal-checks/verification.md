<!-- markdownlint-disable MD013 MD041 -->

## 状態

2026-09-25、applyの静的・合成回帰を実施。実装tasks 1.1〜2.3は完了、実成果物tasks 3.1〜3.3は未完了。正式verify、仕様同期、archive、main merge/pushの完了を意味しない。

## 実装と検査証拠

- LLM/LibreTranslateの本文marker生成・復元・専用prompt fieldを削除。LLMの対象ID・空応答検査、有限retry、reasoning OFF、逐次切断分割は維持した。新依存・新製品Module・再開台帳を追加していない。
- CHECKの対象は明示http/https/www URLと小さい既知拡張子集合（pdf/docx/xlsx/pptx/txt/md/csv/json/yaml/yml）。固有名詞・略語・camelCase・underscore識別子を形だけで判定しない。変更はliteral-reference/warningとして対象IDと根拠を保存する。数値/単位・否定・条件・比較・用語集の検査は維持する。
- 構造化Inline Codeは翻訳とFIXの送信対象から外し、出力層へ原文を保持する。Linkはhrefを維持して表示ラベルを翻訳・修正する。通常textからCodeを推測しない。
- REVIEWはCHECKの参照warningを応答と併合し、モデルが追加指摘なしでもFIX/VERIFYへ渡す。比較reportではこの引継ぎwarningを二重集計せず、対象と根拠を残す。専用の検査LLM段階は追加しない。
- 公開fingerprintはLLM/LibreTranslateともtranslation/review Rule hashを既に含み、比較はreview Rule hashを含む。両Ruleの変更で旧契約を区別できたため、新version項目や互換性機構は不要。Workflow threadも既存Rule hashを使用する。入力やQdrant状態の扱いは変更しない。

| 試験 | 結果と範囲 |
| --- | --- |
| test_translation_output_failures | 24 passed。実装前の配布Rule/通常・retry・分割試験は9 failed。実装後はU.S.→米国、ID/空応答拒否、有限切断回復、安全な原因分類、失敗時の旧Artifact/入力保持が成功 |
| test_finding_contract | U.S./U.K./U.S.A./固有名詞/camelCase/underscoreの誤指摘0。URL、拡張子大小文字、句読点、未知拡張子の境界と既存検査を確認 |
| test_pdf_translation_capability | 12 passed。両Backend×本文/表題/表セルの6ケースで翻訳→CHECK→REVIEW→FIX→VERIFY→実Pandoc DOCXを実行。Code内容とhref保持、ラベル翻訳・修正、warning根拠保存、比較report集計を確認。各ケースは翻訳サービス1、REVIEW 1、FIX 1、VERIFY 1の既存呼出しのみ。LibreTranslateの件数不足/過剰/サービス例外で旧Artifactと入力を保持 |
| test_fingerprint | 17 passed。LLM/LibreTranslateの通常/OFFでRule変更が別threadとなる。公開translate両Backendとreviewが旧RuleのResumeを拒否し、旧manifestを変更しない |
| 全体品質 | 最終pytest: 675 passed, 1 skipped（43.70秒、session 38602、exit 0）。skipはWindows上のPOSIX PTY試験。Ruff check、format（351 files）、ty成功。OpenSpec strict成功。git diff --checkで空白不正なし |

合成試験のLLM/検索/LibreTranslateは固定応答であり、実モデルの翻訳品質や実PDFの受入を証明しない。DOCX試験のPandocは実実行した。URLの推測・未知拡張子の網羅・固有表現認識は提供しない。

## 廃止と後継

旧4 Changesのverificationへ後継と廃止対象を記録した。preserve-protected-fragments-after-split、harden-protected-fragment-restoration、protect-all-translation-chunksのmarker Deltaは再同期せず、後継要求との統合確認後に仕様同期を省略してarchiveする。clarify-translation-placeholder-instructionsは既存skip_specsを維持する。旧marker専用Testは削除したが、対象ID/空応答、逐次切断回復、既存成果物保持、安全な失敗診断のTestは残した。過去の失敗・旧Runを削除せず、旧未完了受入を合格へ書き換えていない。

## 実行時の差分境界

基点commitは38604ee（診断JSON直接上書き）。本Change以外に既存のAGENTS.md、openspec/config.yaml、review context/latency関連Code・Test、lifecycle/terminal_evidenceのcontext-exceeded対応、過去検証記録、未追跡Change/診断Script/outputsの差分がある。全体Testはそれらを含むworktreeで実行した。本Changeのcommitには本件の差分だけを入れ、review.pyはwarning引継ぎhunkのみを選択する。.agents、PDF/DOCX、outputs/runs、秘密値を含めない。

## 残る受入

1. sample3.pdfを新規Run・reasoning OFF・逐次で翻訳する。既存失敗Runを再利用しない。
2. 同じDOCXをMicrosoft Wordで別PDFへ変換し、原本PDFと生成PDFを比較Reviewする。診断保存Changeと証拠を共有する。
3. 利用者へDOCX/PDFを提示して目視を確認する。既知の表内画像・ALIGN・Template等の別件を合格扱いにしない。
