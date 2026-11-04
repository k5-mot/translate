# 🧪 Review／Upgradeの対応付け精度検証

## 🔎 保存済み結果の監査

2026-11-04、[進捗](../PROGRESS.md)に記載されたReviewと、その後に完了したsample2 Reviewを確認した。
sample1は完了済みReviewが存在しないため、失敗したReviewの成功済みcallを確認した。
処理の成功は対応付けの正しさを保証しない。指摘数の減少だけも改善の根拠にしない。

| PDF | Review ID | 確認した誤対応例 |
|---|---|---|
| sample | `01a19c6e-5408-7722-a481-343979864921` | `alignment-000093`で原文の表の行05と訳文の行07を対応付け。「番号の誤訳」として誤検知。長表で異なる行番号の対応が6組ある |
| sample1 | `01a1956c-0f32-7a40-a128-a08f86f2354a` | 原文の「Examples of Requested Military Flexible Deterrent Options」と訳文の「要求された外交的柔軟な抑止選択肢の例」を対応付け。最終ReviewはTimeoutErrorで失敗しており、部分結果での確認 |
| sample2 | `01a1a043-6246-76b0-9fcb-a743005bb887` | `alignment-000250`で「What the Warrior Needs」の引用を、別の目的・要約の段落へ対応付け |
| sample3 | `01a19e1a-96b2-7f73-835e-6adaf2252131` | `alignment-000438`で「Key Components」の施設数の説明を、汚染除去の段落へ対応付け |
| sample4 | `01a19d9a-a44d-7d73-980e-61ede59e59bb` | `alignment-000177`でcontroller overheadの本文をFigure 2のcaptionへ対応付け |
| sample5 | `01a19cf1-bc56-7be0-8049-5b34d11b211a` | `alignment-000040`で式(8)を「重み(8)は自由フェルミオン条件を満たす」という説明文へ対応付け |

保存先は各IDの`outputs/document.ja-office/<ID>/tasks/41-review/`。
sample1以外は`review.json`、sample1は`calls/*/response.json`と`call.json`を照合した。

照合とは別に、識別子の未翻訳を不備とする指摘や、原文と訳文の向きを取り違えた指摘もある。
sample4では原文が`Background andMotivation`、訳文が`Background and Motivation`であるのに、訳文の空白欠落を指摘していた。
これらも再検証時の確認対象にする。

## 🛠️ 修正の判断

現行の`TextUnit`はDocling由来の本文Block・Caption・表セルであり、文分割された`TextSpan`を内包する。
Agentの対応付けはunit全体の文字列を使う。

確認した誤対応は、文境界のずれだけでは説明できない。
sampleのmatch round 12では原文の行05の相手が候補集合になく、残った行07へ誤対応した。
また、LLMに渡す情報は本文と長い参照IDだけで、表の行・列の意味や数式・captionの種別がなかった。

このため、まず次の変更を選ぶ。

- 要素種別・節見出し・表の行見出しと列見出しを、候補選択と対応付けの両方へ渡す。
- 構造情報を比較対象の本文と分け、表番号やページ位置の一致を対応の根拠にしない。
- 照合入力には文書ごとに異なる短いIDを使い、応答Schemaを選択したIDへ限定する。保存時は元IDへ戻す。
- 段落の分割・結合には複数unitの対応を使い、翻訳上の追加・省略と対応箇所の特定を区別する。

一文ずつへの全面変更は加えていない。再検証で段落境界が原因の誤対応が残る場合に、次の修正候補として評価する。

## 📋 検証記録

既存PDFのSHA-256と保存済みLOAD ArtifactのSHA-256を元の処理記録と照合したうえで、現在のAgent／Taskを実LLMへ接続して再実行する。
Docling変換の繰り返しは行わず、同一PDFから得た文書表現を使って照合の変更を比較する。
実行結果とコードのSHA-256は`.tmp/matching-audit/`配下へ保存する。

| 検証 | 結果 |
|---|---|
| 保存済みsampleの長表検査 | 異なる行番号の対応6組を検出し、検査は失敗。再現できることを確認 |
| sampleのmatch round 12の16候補 | 構造情報追加後は正しい3組だけがmatchedとなり、候補内に相手がいない残りは未対応。期待結果と一致 |
| sample5のmatch round 4の16候補 | 数式・本文の誤対応は解消。初期の正解データには原文102と訳文63の取り違えが1組あり、式の前後を確認して訂正した。訳文63の実際の相手は原文108で、元の候補には入っていない |
| 同じsample5候補で短いIDを追加 | 初回は3組を返したが、訂正後の正解に照らすと原文102と訳文63の1組が誤対応。短いIDだけで精度改善完了とは判定しない |
| 対応が確認できた組だけをLLMから返す方式 | sampleの正しい3組、sample5の正しい2組に一致。候補に実際の相手を加えた検証も継続中 |
| sample全文Review、構造情報のみの途中版 | 同じIDの重複出力による再試行を確認。ログを保存して停止し、短いIDを含む版で再検証する |
| sample1〜4の既知の誤対応に実在する正しい相手を追加 | 短いID版でそれぞれ8組・1組・2組・1組の正解に一致。sample4は英語2段落と日本語1unitの対応を確認 |
| sample5で原文106・108を候補に追加 | 対応が確認できた組だけを返す方式で、正しい説明文2組を含む計4組に一致。似た表現の原文102へは誤対応しない |
| sample5 Upgrade全文（旧5ページ・新4ページ） | `de6d32d`で旧88unit／新81unitを確認し、末尾ページの7unitだけを削除と判定。誤った追加・変更・訳文参照はなし。ただし冗長な確認済みID配列の省略で再試行が発生 |
| 同じUpgradeの失敗callを応答保存付きで再現 | LLMは削除7件を正しく返していたが、確認済みID配列の省略で失敗したことを確認。確認範囲をchange一覧から導出する修正後、1回で7件を正しく処理 |
| sample1〜4の同じ正解集合を応答形式の修正版で再検証 | 全ケースが1試行で正解8組・1組・2組・1組に一致。`.tmp/matching-audit/other-pdfs-v4/*/check.json`に入力IDと正解・実結果を保存 |

2回目の修正では、Reviewの残余候補をアプリ側で未確認として補い、LLMへ全候補の列挙を要求しない。
不明ID・重複IDの拒否は維持する。Upgradeはchange一覧による全英文IDの一度限りの網羅を引き続き検証し、
同じIDを繰り返す確認済み配列だけをアプリ側で導出する。
`de6d32d`の全文Reviewはこの応答形式の再試行を記録して停止し、修正版でやり直す。

実行した検査は`.venv/Scripts/python.exe -m pytest tests/unit tests/regression -q`（329件成功）、
`.venv/Scripts/python.exe -m pytest tests/unit/test_agents.py -q`（73件成功）、
`.venv/Scripts/ruff.exe check translate tests/unit/test_agents.py`、`.venv/Scripts/ty.exe check`。

全文Review／Upgradeと、残るPDFの失敗箇所の再検証は継続中。現段階では誤検知がなくなったとは判定していない。
