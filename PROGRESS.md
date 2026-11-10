# 📈 進捗

Review／Upgradeの対応付け精度の改善と、その実機検証の進捗を記録する。不具合は[BUG.md](BUG.md)、監査の詳細と証跡は[対応付け精度検証](docs/MATCHING_VALIDATION.md)へ記録する。

## 🧭 現在の状況

- 作業ブランチ: `feature/review-matching-audit`（`origin/main`の`e3696fd`から分岐。未push）
- 実装: 完了。修正ごとにコミット済み
- 品質検査: `pytest`（unit・regression）405件成功、`ruff check`、`ruff format --check`、`ty check`は問題なし。照合の修正だけを含むコミット`58d2d69`でも385件成功
- 実機検証: 実行中（記録 `.tmp/acceptance/20261110-200735-a65687bc/state.json`）
- 範囲外: LLMとEmbeddingを含む外部APIの安定性は、この作業の対象外とする。外部APIが原因の失敗は記録だけ行う

## 🧪 実機検証

順序はsample、sample5、sample4、sample3、sample2、sample1とする。起動は`scripts/real_acceptance.ps1`、記録は`.tmp/acceptance/20261110-200735-a65687bc/state.json`にある。

Reviewの訳文はTranslateのDOCXをWordでPDF化したものを使う。Upgradeは英文v1に元PDF、英文v2に最終ページを削除したPDF、日本語v1に訳文PDFを指定し、差分処理も検証する。

| 文書 | Register | Translate | Review | Upgrade |
|---|---|---|---|---|
| sample | 成功 (`01a1c524-8e7f-7161-9d57-bbcf4550b2ac`) | 成功 (`01a1c526-5354-7140-bad3-95914c56a06e`) | 実行中 (`01a1c52f-0cd2-7440-8367-745afa7ae1c6`) | 未実行 |
| sample5 | 未実行 | 未実行 | 未実行 | 未実行 |
| sample4 | 未実行 | 未実行 | 未実行 | 未実行 |
| sample3 | 未実行 | 未実行 | 未実行 | 未実行 |
| sample2 | 未実行 | 未実行 | 未実行 | 未実行 |
| sample1 | 未実行 | 未実行 | 未実行 | 未実行 |

## ✅ 実装済みの修正

| コミット | 内容 |
|---|---|
| `b2acdf3` | 構造文脈と文書別の短縮IDで、表の別行や数式の誤対応を減らす |
| `46ab972` | 正しい対応の欠落を応答不正と区別し、未確認候補として扱う |
| `58d2d69` | Embeddingで照合候補を文書全体から検索する。照合規則の世代をCall IDへ含める。同じunitの照合が3回失敗したら未確認とする。複製された英語表紙は原文を比較基準にする。操作選択の出力上限とrole別ID上限を直す |
| `ef251ce` | 抽出空白、日付区切り、ページ参照、ドットリーダー、固有名詞、略語、書誌タイトル、単位換算の誤検知を抑える |
| `1634faa` | Reviewで進捗のない照合が手数の上限に達したら、評価を含む残作業を状態から決めて完了させる |

## 🔬 照合精度の確認結果

保存済みReviewで見つけた誤対応と誤検知を、現行コードの候補検索と実LLMで個別に再照合した。個別の照合は全文Reviewの代わりにならないため、全文の確認は上記の実機検証で行う。

| 文書 | 確認した内容 | 結果 |
|---|---|---|
| sample | 長表の別行への誤対応 | 66セル中66セルで正しい行・列を選択 |
| sample1 | 目次の別行、表紙見出し、`PREFACE`、campaign概要への誤対応 | すべて期待どおりの対応、または原文のみ（source-only）として扱われることを確認 |
| sample2 | source97、439、632〜635、900、1062、58・62、294、482への誤対応 | すべて正しい訳unitを選択 |
| sample3 | 表のgross／net行の取り違え、ページを跨ぐ表の誤対応 | 6件中6件が正しい行 |
| sample4 | 本文とFigure captionの誤対応、表の数値と列見出しの誤対応 | すべて期待どおりの対応 |
| sample5 | 式と説明文の誤対応、複製された英語表紙のOCR差 | 誤対応は解消。表紙のOCR差による指摘11件は抑制される |

## ⏸️ 未解決と既知の限界

- sample5の式(17)・(18)は原文のLOADに存在する（`#/texts/131`、`#/texts/133`）。以前の「LOADから欠落」という記録は誤りだった。訳文の番号誤記（式(18)を(13)と記載）を原文の式(18)へ対応付けられるかは、全文Reviewで確認する
- sample3の原文表の負号は、元PDFのテキスト層に存在しない（画像では`−1,796`、テキスト層は`1,796`）。テキスト層を読むDoclingでは取得できず、LOADの問題ではない
- sample1の訳文PDFの表紙は画像で、テキスト層がない。DoclingのOCRは紺地の`Joint Planning`を読み取れない。LOADの問題ではない
- [matching.py](translate/pipeline/matching.py)の閾値の多くは、sample1〜5で観測した値から決めている。他の文書での妥当性は未確認
- LOADのdocling-coreへの移行は、ブランチ`feature/load-docling-core`で完了した（`30479fe`、`58b250a`）。既存87文書でLOAD結果が移行前と完全に一致する。実機検証の終了後に取り込む
- `.env.sample`へ`LLM_INPUT_BYTES_PER_TOKEN`を追記していない。権限設定で`.env*`の読み取りが禁止されているため
- コードブロックの言語はLOADで取り込んでいない。Doclingのキーは`code_language`だが、既存実装は`language`を読んでいた。挙動を変えないよう、移行でもそのままにした
