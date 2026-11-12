# 📝 設計の改善事項

現状の設計で改善すべき事項を、実機検証と監査で観測した事実から洗い出す。不具合そのものは[BUG.md](BUG.md)、作業の進捗は[PROGRESS.md](PROGRESS.md)、照合精度の証跡は[対応付け精度検証](docs/MATCHING_VALIDATION.md)へ記録する。

優先度は、成果物を得られない失敗につながるものを高、時間や保守性に効くものを中、利用者の分かりやすさに効くものを低とする。

## 🤖 Agentの制御

### 🔴 高: 操作の選択をLLMに任せる範囲を絞る

- 現状: ReviewとUpgradeは、毎手`choose_action`でLLMに次の操作を選ばせる。選択が不正または進捗がないときだけ、状態から決める`_fallback_action`へ切り替える。
- 問題: 照合、評価、再確認、終了の順序は、状態からほぼ一意に決まる。sampleのReviewでは、Agentが照合を165回選んで評価を一度も選ばず、`TimeoutError`で失敗した（`1634faa`で回避）。操作選択のLLM Callは時間を使うが、成果物の質には寄与していない。
- 改善案: 操作の順序は状態機械で決め、LLMは照合と評価の中身だけを担当する。overview、read、searchのような探索操作が必要な場面を実測し、残すかを決める。

### 🟡 中: ReviewとUpgradeのAgentループを共通化する

- 現状: [review.py](translate/pipeline/review.py)と[upgrade.py](translate/pipeline/upgrade.py)は、それぞれ独自のループと上限を持つ。進捗のない手数の上限はReviewが12、Upgradeが12と36。同じunitの照合失敗の上限は`_MATCH_NO_PROGRESS_LIMIT`と`_MATCH_FAILURE_LIMIT`として別々に定義されている。
- 問題: 片方で直した停止条件が、もう片方へ反映されない。`1634faa`の修正もReviewだけに入っている。
- 改善案: 期限、進捗のない手数、対象ごとの失敗回数、決定的な操作への切り替えを共通のループへまとめ、上限値は設定として一か所で持つ。

### 🔴 高: 処理できない対象を記録して先へ進む

- 現状: 1つの対象が入力上限超過や応答不正を繰り返すと、全体が`TimeoutError`や`DIFF did not complete.`で失敗する。sample1のReview（`LLMInputExceededError`45件）、sample1のUpgrade（text 1419）、sample2のUpgrade（同じセルの照合を12回）で観測した。
- 改善案: 対象ごとの失敗回数が上限に達したら「処理不能」として成果物へ明記し、残りの対象を完了させる。入力上限を超える対象は、送信前に分割するか縮小する。

## ⏱️ 時間と入力の予算

### 🔴 高: 期限を文書の規模に合わせる

- 現状: LLM Taskの期限は`llm_task_deadline_seconds`の固定値で、文書の規模によらない。
- 問題: sample（14ページ）でも4工程に約1時間20分かかる。357ページのsample1や88ページのsample2では、ReviewやUpgradeが期限内に終わるかを実行のたびに確認する必要がある。
- 改善案: unit数とLLM Call数の見積もりから期限を決めるか、期限に達しても保存済みの結果から再開できる単位で区切る。

### 🟡 中: 入力トークン数の見積もりを実測に近づける

- 現状: 入力の大きさは、バイト数を`LLM_INPUT_BYTES_PER_TOKEN`で割って見積もる。
- 問題: 日本語と英語でバイト当たりのトークン数が大きく異なり、見積もりを外すと`LLMInputExceededError`になる。
- 改善案: 利用するモデルのトークナイザーで数えるか、上限超過の応答から実測の比率を学習して安全側へ補正する。`.env.sample`への設定例の追記も必要（権限設定により未対応）。

### 🟡 中: Upgradeの差分検出で、LLMを使う前に機械的な対応付けを行う

- 現状: sample2のUpgradeはround 857まで進み、Resume後だけで約2時間28分かかった。sample1ではround 1326まで進んで失敗した。
- 改善案: 英文v1とv2で本文が一致するunitは、LLMを使わずに「変更なし」と判定する。LLMには、変更・追加・削除の候補だけを渡す。

## 🧩 照合

### 🟡 中: 照合の閾値を検証用データで管理する

- 現状: [matching.py](translate/pipeline/matching.py)の`_MIN_NEIGHBOR_SIMILARITY = 0.69`、`_TABLE_ROW_CANDIDATE_MARGIN = 0.03`などは、sample1〜5で観測した値から決めている。
- 問題: 他の文書での妥当性が確認されておらず、過適合のおそれがある。閾値を変えたときの影響を測る手段が、保存済みReviewの個別再照合に限られる。
- 改善案: 正解の対応付けを持つ検証用データを`inputs/validation-pdfs/`の文書（sample1〜5以外を含む）から作り、閾値の変更ごとに正解率を測れるようにする。

## 📄 文書の読み込み

### 🟡 中: 中間表現をdocling-coreの型で扱う

- 現状: LOADは`feature/load-docling-core`でdocling-coreへ移行した。POSITIONとNORMALIZEは、まだJSONを辞書のまま操作している。
- 問題: MERGEの出力に`origin.binary_hash`が欠けていたように、辞書の操作では文書として不正な形を早期に検出できない。
- 改善案: POSITIONとNORMALIZEもdocling-coreの型で読み書きし、各Taskの出力を検証する。

### 🟡 中: 中間成果物に形式の世代を持たせる

- 現状: Artifactには形式の世代がない。
- 問題: MERGEを修正すると、修正前のArtifactから再開した処理がLOADで受け付けられない。原因がエラーから分かりにくい。
- 改善案: Artifactに形式の世代を記録し、古い世代を検出したら該当Taskから作り直すか、理由を明示して停止する。照合ではすでに`MATCHING_VERSION`をCall IDへ含めているので、同じ考え方を広げる。

### 🟢 低: テキスト層の欠落を検出して警告する

- 現状: sample3の負号は図形として描かれ、テキスト層にない。sample1の訳文表紙は画像で、OCRが文字を読み取れない。
- 問題: どちらも検出されず、照合や評価の誤りとして後から見つかる。
- 改善案: ページの画像と抽出テキストの量が大きく食い違う場合や、OCRの信頼度が低い場合に、成果物へ警告を残す。

### 🟢 低: コードブロックの言語を取り込む

- 現状: Doclingのキーは`code_language`だが、LOADは`language`を読むため、言語は常に空になる。
- 改善案: 出力が変わることを確認したうえで`code_language`を取り込む。

## 🔁 再開と運用

### 🔴 高: 実行中のまま残った処理を再開できるようにする

- 現状: UIのworkerが終了すると、処理記録が`processing`のまま残る。UIは`processing`の記録にStopだけを表示し、Resumeを表示しない。
- 改善案: workerの生存確認を記録へ持たせ、応答のない`processing`を中断として扱い、Resumeできるようにする。

### 🟡 中: 実機検証の記録をスクリプト自身が更新する

- 現状: [real_acceptance.ps1](scripts/real_acceptance.ps1)は`state.json`と標準出力だけを残し、PROGRESS.mdの表は外部のスクリプトで書き換えている。Registerは成功時にしか記録されないため、実行中の表示ができない。
- 改善案: 各工程の開始、成功、失敗と所要時間を`state.json`へ記録し、表への反映もスクリプトから行う。

### 🟢 低: 外部APIの停止を処理の開始前に検出する

- 現状: LLMのendpointが停止していると、Translateは約15秒で`failed`になる。外部APIの安定性は今回の範囲外とした。
- 改善案: 開始前にLLM、Embedding、Doclingの疎通を確認し、停止中なら処理を始めずに理由を表示する。

## 🖥️ UI

### 🟢 低: 結果画面の見出しを処理の種類に合わせる

- 現状: ReviewとUpgradeの結果画面でも、大見出しが`Translate`と表示される。
- 改善案: 処理記録の種類から見出しを決める。
