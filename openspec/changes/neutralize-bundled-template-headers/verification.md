# Verification: neutralize-bundled-template-headers

## 2026-09-27 Apply結果

基点`9ebfd73`。8/9 Task完了。製品資産の修正、回帰Test、Word PDF検査は完了。新規sample3の全工程と利用者目視受入（3.2）は未完了であり、同期・archiveは保留する。計画Artifactが揃っていることを実装・受入完了とは扱わない。

## 修正と回帰Evidence

- 修正前に追加Testを実行: 2 failed / 1 passed。テンプレートと実Pandoc出力に仮ヘッダーが存在して失敗した。独自テンプレート保持Testは修正前から成功。
- 修正後: 同じ3 Testはすべて成功。通常ページの有効フッターを空にし、未使用フッターにPAGEを残す負例も検出した。
- ZIP部品比較: `word/header1.xml`、`word/footer1.xml`、`word/footer3.xml`、`word/footer4.xml`だけを変更。残る25部品はbyte単位で不変。部品名の追加・削除なし。
- 一回限りの機械的ZIP編集でsection参照を解決し、先頭／通常の用途が競合していないことを確認。変更前後のpackageを検証して置換した。製品変換経路への新規処理は追加していない。編集用一時Scriptは削除済み。
- 先頭用`header2/footer2`と文書section、relationships、settings、stylesは不変。通常フッターは中央揃えの動的PAGEのみ。見出し参照、保存日付、付録用接頭辞を除去した。
- 本文内の仮文言に似た文字列を保持。独自参照DOCXのヘッダー／フッター部品保持と入力SHA-256不変を実Pandocで検証。
- `template-style.md`の全110スタイルについてID、種別、表示名、継承元がXMLと一致。

| 検査 | 結果 |
| --- | --- |
| output contract + documentation | 81 passed / 7.08s |
| Ruff check | 成功 |
| Ruff format --check | 395 files、成功 |
| ty check | 成功 |
| 全pytest（PYTHONUTF8指定なし） | 1023 passed / 1 skipped、66.49s |
| OpenSpec strict validate | 成功 |
| git diff --check | 成功 |

全pytestは開始時から存在する未コミット変更も含む作業ツリーで実行した。これらを今回の変更としてコミットしない。WindowsのPOSIX PTY Test skipは既存の環境条件による。

## Wordによる表示検査

検証用Markdownを既存`create_docx`で変換し、Microsoft Word 16.0の専用COMインスタンスで開いてPDF化した。これは利用者操作相当の検証であり、製品のPDF変換機能追加ではない。Wordの警告は`wdAlertsAll`のまま、入力DOCXは読取り専用、マクロは無効とした。

- 最終実行はexit 0、全6ページ、対話入力なしでOpen・再ページ計算・Exportが終了。更新確認により停止する挙動は観測されなかった。非表示COM実行のため、画面上のポップアップを直接撮影したEvidenceではない。
- 全6ページをレンダリングして確認。全ページのヘッダーは空。1ページ目のフッターは空、2〜6ページはそれぞれ`2`〜`6`のみ。社名・文書名・機密表示・保存日はヘッダー／フッターにない。
- 最初の実行はPDF出力後の`Quit(0)`でPowerShellの参照引数Error。専用インスタンスのPIDと起動時刻を確認し、開いている文書0件を確認して終了した。終了引数を`[ref]`へ修正した再実行は正常終了。最終検査時にWINWORDプロセスの残存なし。
- 保存先は未追跡の`outputs/template-neutralization/`。DOCX/PDF、レンダリング画像、運用用Scriptはコミット対象外。既存のsample3成果物は未変更。

| 対象 | SHA-256 |
| --- | --- |
| 同梱template.docx（変更前） | b093da1464a715da8bf76563cde0921c553bbdf5e9f18cceab04796653095cec |
| 同梱template.docx（変更後） | 273e611fe5f2e69f4aebb530ec4e3f82a8f34e7f279bdcda57eb779ded09d44f |
| word-check.docx | 074d1e8c110721dac243f010ce859c96791a831bda90eff5ee4f54ec74127e31 |
| word-check.pdf | 0d8ed52258800ee03791196541c95f849da4a5d39c3517c84d982b3f8b1c3c05 |

## 品質・Lifecycle・残件判定

Q-FUNC/Q-COMP/Q-REL/Q-MAINTは上述の自動検査で確認。Q-INTERACTIONはWord PDFの全ページで確認。Q-SECは既存の外部参照拒否Test成功、追加の外部参照／自動更新要求なし、警告を抑制せずWord export完了で確認した。

新規依存、LLM/Embedding/Docling/Qdrant呼出し、移行、旧形式loader、互換切替、既存成果物の更新・削除はいずれも追加していない。同梱資産の旧仮表示は廃止し、新規生成物にだけ適用する。Git管理済みの製品テンプレートは修正対象だが、サンプルPDF/DOCXと`.agents`はコミットしない。

3.2の新規sample3 Translation→Word PDF→原文とのComparison Reviewは、この変更後には未実行。既存受入Changeの未完了項目と利用者目視受入が残っている。今回の合成文書による検証を代替Evidenceにせず、3.2を未完了のまま保持する。3.3の判定結果は**archive保留**。外部サービスが復旧したという新しいEvidenceも本実行からは得ていない。
