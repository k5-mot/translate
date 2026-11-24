# 📈 進捗

Review／Upgradeの対応付け精度の改善と、その実機検証の進捗を記録する。不具合は[BUG.md](BUG.md)、監査の詳細と証跡は[対応付け精度検証](docs/MATCHING_VALIDATION.md)へ記録する。

## 🧭 現在の状況

- 作業ブランチ: `feature/review-upgrade-completion`（`origin/main`の`701c359`へrebase済み）
- 実装: ReviewとUpgradeを、対象を分割して最後まで処理する決定的な手順へ改めた。訳者が追加したコラムは修正の対象にしない
- 品質検査: `pytest` 362件成功、`ruff check`、`ruff format --check`、`ty check`は問題なし
- 実機検証: sample〜sample2の全20工程とコラム確認が成功。sample1はRegisterまで成功し、Translate以降は検証用PCの電源断が続いたため、利用者の判断で検証を終了した
- 範囲外: LLMとEmbeddingを含む外部APIの安定性は、この作業の対象外とする。外部APIが原因の失敗は記録だけ行う

## 🧪 実機検証

順序はsample、sample5、sample4、sample3、sample2、sample1とする。起動は`scripts/real_acceptance.ps1 -AllowUncommitted`、記録は`.tmp/acceptance/`配下の`20261115-214801-df24d278`（sample〜sample3）と`20261118-120141-af6f2abd`（sample2、sample1）の`state.json`にある。

Reviewの訳文は、TranslateのDOCXへ`scripts/add_translation_columns.py`で英文にないコラムを加え、WordでPDF化したものを使う。Upgradeは英文v1に元PDF、英文v2に最終ページを削除したPDF、日本語v1にコラム入りの訳文PDFを指定する。各Review・Upgradeの後に`scripts/check_translation_columns.py`で、コラムが照合・指摘・修正提案の対象になっていないことを確認した（表の「コラム」列）。

sample2の初回Translateは、providerの入力上限超過（HTTP 400）を分割せず停止したため修正した（[BUG.md](BUG.md)）。この修正はそのエラーを受けた場合の動作だけを変えるため、sample〜sample3は再実行していない。sample1は規模が大きく（Translateだけで約20時間）、2026-11-19と11-20に検証用PCの電源が切られてTranslateが2回中断した。検証スクリプトは途中から再開できないため、Translate以降は未検証とした。

| 文書 | Register | Translate | Review | Upgrade | コラム |
|---|---|---|---|---|---|
| sample | 成功 (`01a1df40-3c81-7c91-9837-cd147ff223e3`) | 成功 (`01a1df42-aa83-7773-97b2-05e85330212b`) | 成功 (`01a1df4c-175c-7963-9fbb-29fb38fefea9`) | 成功 (`01a1df62-af70-7e53-8f72-9bc1fb894dbc`) | 成功 |
| sample5 | 成功 (`01a1df66-b66c-79a2-9ad2-6ee87b4d320d`) | 成功 (`01a1df8c-dda2-7631-bca7-b2cc8867fb70`) | 成功 (`01a1dfb6-32b2-7a00-9173-5c47a448a88c`) | 成功 (`01a1dffd-d39b-7c00-8a4a-27b87d2f12f6`) | 成功 |
| sample4 | 成功 (`01a1e04c-1494-7022-b91a-d585f1bdabdc`) | 成功 (`01a1e054-ec15-7f12-997e-0c7adc8fb157`) | 成功 (`01a1e06e-286b-7233-8b6c-4e82ba0604e9`) | 成功 (`01a1e09b-ed5b-77b1-9624-fcb4be97e7ef`) | 成功 |
| sample3 | 成功 (`01a1e0b1-25fb-74f2-bb24-fd26c2a8c120`) | 成功 (`01a1e0ba-ad63-70a3-bac4-d978f0b36ddd`) | 成功 (`01a1e0da-d94f-7c91-8303-e8e2f93497c3`) | 成功 (`01a1e11d-02c7-7e52-b471-c3135fefa729`) | 成功 |
| sample2 | 成功 (`01a1ec9a-7fc7-7840-a4c1-4d459064d86f`) | 成功 (`01a1ecbe-d4f7-7cb1-b1a6-c020a6e26c43`) | 成功 (`01a1ed38-7040-7753-b6e1-e2fb225db2d1`) | 成功 (`01a1ee1c-6b86-7c12-b8d7-df832c9963c2`) | 成功 |
| sample1 | 成功 (`01a1f42c-18ca-78d2-a58e-a807a7c6d78f`) | 中止 (`01a1f4e1-7142-7113-ade9-88fa7f511bb8`) | 未実行 | 未実行 | 未実行 |

## ✅ 実装済みの修正

| コミット | 内容 |
|---|---|
| `b2acdf3` | 構造文脈と文書別の短縮IDで、表の別行や数式の誤対応を減らす |
| `46ab972` | 正しい対応の欠落を応答不正と区別し、未確認候補として扱う |
| `58d2d69` | Embeddingで照合候補を文書全体から検索する。照合規則の世代をCall IDへ含める。同じunitの照合が3回失敗したら未確認とする。複製された英語表紙は原文を比較基準にする。操作選択の出力上限とrole別ID上限を直す |
| `ef251ce` | 抽出空白、日付区切り、ページ参照、ドットリーダー、固有名詞、略語、書誌タイトル、単位換算の誤検知を抑える |
| `1634faa` | Reviewで進捗のない照合が手数の上限に達したら、評価を含む残作業を状態から決めて完了させる |
| `feature/review-upgrade-completion` | ReviewとUpgradeを、英文の要素を文書順に起点とする決定的な手順へ改め、失敗した範囲は縮めて続け、全対象を処理する |
| `feature/review-upgrade-completion` | 分割できない最小の対象が出力超過・応答不正となった場合に、`LLM_RETRY_ATTEMPTS`回まで生成し直す |
| `feature/review-upgrade-completion` | 原文が数式・コードだけの組は対応だけを記録し、品質確認へ送らない。訳文を変えない修正案は不備なしとする |
| `feature/review-upgrade-completion` | 「コラム：」「訳注：」「訳者注：」「補足：」で始まる訳文の要素を、照合・比較の候補から除く |
| `feature/review-upgrade-completion` | providerが入力上限超過と分類できるHTTP 400を、文言が既知でなくても分割の対象とする |

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
- 見出しのないコラムを照合しないことは、LLMへの指示だけで守らせている。sample3では本文の行と結合したコラムを確認したが、すべての文書で守られる保証はない
- Translateは数式を`$$…$$`の文字としてDOCXへ出力し、Word経由の訳文PDFでは数式が複数の要素に分かれる。原文が数式・コードだけの組はReviewで評価しない
- 単一要素でもprovider側で入力上限を超える場合は、従来どおり失敗として停止する
- sample1（357ページ）のTranslate以降は、このブランチのコードで実機検証していない
