<!-- markdownlint-disable MD013 MD041 -->

## 中間検証（2026-09-25）

正式verifyは未完了。現在8/12 tasks完了。実translation→Microsoft WordでPDF化→入力PDFとのComparison Review、利用者目視の証拠が揃うまでarchiveしない。

## CONTENT-PROTECTED-001の修正

- [関数説明監査](../document-all-python-function-purposes/verification.md)で、`_restore_chunk_placeholders`が空の保護対応表を無条件で通す問題を再現した。未知marker拒否は本Changeの既存設計に含まれるため、別機能は追加せず漏れていた境界を是正した。
- 保護対象が0件でも、既存のmarker正規表現と標準`unicodedata.normalize`で検査する。正常応答はObject identityと本文表記を維持する。既存の`TranslationOutputError`と有限retry・atomic保存へ接続し、新しいHelper、依存、並列処理、独自再開状態を追加していない。
- 既存split成功Testは保護対象がない後半へもmarkerを返し、前半しかassertしていなかった。後半にはmarkerなしの応答を与え、両単位の結果と呼出回数をassertするよう修正した。新しい異常系Testでは後半への未知marker混入を明示的に検査する。

## 回帰証拠

| 観点 | Testと確認内容 |
| --- | --- |
| 空対応表の未知marker | `test_empty_protection_map_rejects_unknown_marker`。canonical、空白・大小文字・区切り揺れ、全角表記の3ケースを拒否し、本文を含まない原因分類と対象位置を確認 |
| 正常本文の不変性 | `test_empty_protection_map_preserves_valid_response_without_normalization`。全角英字、丸数字、結合文字の表記と応答identityが不変 |
| 通常・分割の有限retry | `test_unknown_marker_retries_and_publishes_only_valid_translation`。通常/分割×回復/枯渇の4ケースで、同じ対象の2試行、分割時の逐次順序を確認 |
| 成果物の公開境界 | 上記4ケースで実TranslateTaskと保存処理を使用。回復時だけ新しいpage Artifactを公開し、枯渇時は既存Artifactを保持。不完全な一時領域を残さず、入力Documentを変更しない |

- 修正前は追加した8ケース中7 failed / 1 passed。未知markerの検出・失敗停止・正しい訳文への回復が失敗した。正常本文不変の1ケースだけは修正前から成功。
- 修正後の翻訳出力Testは22 passed。全体は**409 passed, 1 skipped（25.76秒）**。skipはWindows上のPOSIX PTY Test。
- Ruff、Format（307 files）、ty、git diff --check、OpenSpec strict validationは合格。全角fixtureはUnicode escapeで表現し、Lintの規則を緩めていない。
- LLMと検索は固定応答へ置換している。これらのTestは実モデルの翻訳品質、公開CLIでの障害後Resume、DOCX/PDFの見た目を証明しない。

## 実検証の状態と残課題

- 同じtranslation session 40709のlive handleをpollし、Run `01a0d44f-1efa-7597-9d1b-0be4c5748b85`のREVIEW完了（2535.912秒）を確認した。これは翻訳Workflow内のREVIEWであり、Word PDFとのComparison Reviewではない。
- このProcessは修正前に起動しているため、今回のmarker修正が適用された実検証の証拠にはしない。停止・重複起動は行っていない。
- CRITICAL: tasks 3.1〜3.3。実サンプルの処理順、source hash、保護値、表紙、公開条件、同一RunのResume、機密値非包含とcleanupの証拠が不足。
- CRITICAL: task 4.3。Word/PDFの利用者目視と正式verifyが未完了のためarchive・main merge・pushは未実施。
- CONTENT-PROTECTED-001は実装修正とオフライン回帰確認済み。実E2Eを含む最終受入は未完了。過去のtask 2.1/2.2の完了記録も、今回の空対応表ケースを実CLIで検証済みという根拠には使わない。

## 2026-09-25: 本文保護記号の廃止と後継

利用者承認済みの後継 [simplify-translation-literal-checks](../simplify-translation-literal-checks/proposal.md) により、本文markerの生成・復元・正規化・一対一保持・未知marker拒否、および固有名詞/略語/識別子の完全一致を成功条件にする要求は廃止する。URL/既知拡張子ファイル名は事後warningとし、構造化CodeとLink先は保持する。

本Changeの履歴・旧Run・過去の検証結果は削除しない。marker専用の未完了受入を成功扱いにせず「後継要求へ置換」として扱う。対象ID・空応答拒否、有限retry、切断時の逐次分割、本文を含まない失敗診断、既存成果物保持、Rule hashによる旧Run拒否は後継Testに残す。新規sample3、Word PDF、比較Review、利用者目視は後継のtasks 3.1〜3.3で追跡し、旧成果物で代用しない。

同期/archive時は本Changeの旧marker Deltaを再適用しない。Deltaを持つChangeは後継仕様との統合後に仕様同期を省略してarchiveする。skip_specsのChangeはその設定を維持する。これはarchive済み・受入完了の宣言ではなく、旧要求を再導入しないための廃止記録である。
