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

## 実検証の開始記録

実装commit 17ebaf2と上記既存差分を含むworktreeで、新規公開CLI翻訳を2026-09-25 13:17:31 UTCに開始した。入力SHA-256は5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f。旧Runや既存exportは上書きしていない。

- Run: 01a0d8b6-c2ab-7c92-bed9-58403a8410b3、tool session: 75952。
- 入力: inputs/sample3.pdf。export先: outputs/sample3-acceptance-off-literals。
- LLM_REASONING_MODE=off。保存snapshotもoff。context/output/image=30208/16384/2048、request timeout=1800秒、Task deadline=21600秒、retry=3。
- 起動系列: uv PID 49236 → Python launcher PID 41572 → Python PID 19172。プロセス数はModel並行数を意味しない。
- SPLIT〜LOAD完了、DOCLING=26.987秒、STRUCTURE=104.580秒。前回失敗した第2ページを通過し、第4ページのTRANSLATEまで進行中。この途中記録はWorkflow成功証拠ではない。終了handleと最新結果を確認するまで再起動・Resumeしない。
- この翻訳は通常CLIで起動したためdetached childの呼出しcounterは未接続。未取得の呼出し数を0と記録しない。後続の実比較は既存診断runnerを使用し、診断保存Changeとの共通証拠を得る。
- 読取り専用Langfuse v2 observations照会で、trace 56e4ac20ce055e2988a2f42e599bb1b6の終了済み18 llm.request（STRUCTURE 15、TRANSLATE 3）のmetadataが全てreasoning=none / thinking=disabledであることを確認した。取得時点の件数であり最終件数ではない。Provider内部の推論token実測0は主張しない。旧trace一覧APIはv4 events_only環境の404を返したため、導入済みSDKのv2 observationsへ切り替えた。診断照会はModel要求を追加していない。
- QdrantClientからAPI keyを暗号化されていない接続で使用する旨の警告が出た。処理停止は起きていない。接続設定を無断変更せず、Security受入の残確認として保持する。
