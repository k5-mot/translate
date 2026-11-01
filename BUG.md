# 🐛 検証中に見つかった不具合

## 🧾 Reviewのmatch callがLLM応答不正で失敗する

- 再現条件: `sample.pdf`のReviewでstructured LLM応答が不正になる。
- 結果: match round 32が`LLMInvalidResponseError`の再試行上限後に`failed`で保存された。他roundでは再試行成功もあった。
- 影響: Reviewの一部matchを完了できないcallが出る。
- 記録: `outputs/document.ja-office/01a182a0-8f23-7960-a9c9-2b94e76ce2ac/tasks/41-review/calls`と`review.log`。

## 🧠 Upgrade matchの対象がLLM入力上限を超える

- 再現条件: `sample.pdf`と末尾ページを除いた新版、日本語訳PDFでUpgradeする。
- 結果: DIFF match round 6が`Selected document scope exceeds REVIEW_INPUT_TOKENS`でfailedになった。
- 影響: Upgrade差分の一部をmatchできない。
- 記録: `outputs/sample/01a182c8-bd5b-7403-b17c-ef4d215248f0/tasks/21-diff/calls/call-4a008e837f411a1a853941ffd639c4ebbcfd9f3a4533b2a48b09d3cd54dacda2/call.json`。

- 再現条件: `sample5.pdf`と末尾ページを除いた新版、日本語訳PDFでUpgradeする。
- 結果: 旧UpgradeではDIFF matchのround 0、1、2、6で`LLMInputExceededError`が発生し、Upgradeが`TimeoutError`で失敗した。再実行ではround 0/1の入力上限超過と一部roundの`LLMInvalidResponseError`が続いたが、分割された後続roundが成功し、Upgrade自体は完了した。
- 影響: match callの失敗後に多数の分割・再試行が必要になり、Upgradeが約1時間47分かかった。
- 記録: `outputs/sample5/01a18922-4bc7-7151-a2a5-364605853df4/tasks/21-diff/calls`と`upgrade.log`。

- 再実行時、DIFFのround 0/1は`LLMInputExceededError`、複数roundは`LLMInvalidResponseError`で失敗したが、round 97までに細分化された後続callが成功しUpgrade全体はsucceededになった。
- 影響: 大きなmatch scopeとLLM応答不正によりDIFFが多数のcallと再試行を要する。
- 記録: `outputs/sample5/01a18e04-4bbe-7a00-b64d-9a235d704c44/tasks/21-diff/calls`、`upgrade.log`、`state-upgrade.json`。

## 🌐 Docling変換の接続失敗と長時間応答待ち

- 再現条件: `sample5.pdf`（5ページ）をRegister、またはTranslateする。
- 結果: RegisterはDocling pollの接続が2回の実行で各6回失敗して`ConnectError`となった後、3回目で約57分後に成功した。TranslateはDocling `/health`・`/ready`が200でも、変換開始から30分以上`processing`のまま完了ログがない。
- 影響: 成功まで非常に長くかかり、後続工程を開始できない。
- 記録: `outputs/sample5/01a182dd-787a-7a90-b549-48ff5107e193/registration.log`、`outputs/sample5/01a18489-706b-7c60-b014-f563dbda2932/translation.log`。

- 再現条件: `sample5.pdf`のReviewまたはUpgradeを実行する。
- 結果: ReviewはDocling変換開始後15分以上完了せず、UpgradeもDocling変換開始後に応答待ちとなった。接続先`192.168.1.100:31100`の`/health`、`/docs`、`/openapi.json`も3〜5秒でタイムアウトした（TCPポートは接続可能）。
- 影響: ReviewとUpgradeがDocling工程で停滞し、後続工程へ進めない。
- 記録: `outputs/document.ja-office/01a18dce-7caf-74c2-ae9b-bb7a1bfec1ce/review.log`、`outputs/sample5/01a18ddc-dd53-7ab2-9563-55e861edfed9/upgrade.log`。
- 再現条件: Doclingが再起動中に`sample5.pdf`のUpgradeを実行する。
- 結果: 変換POSTが6回の接続再試行後に`ConnectError`で失敗し、Upgradeもfailedになった。
- 影響: Docling再起動中に処理を開始するとUpgradeを完了できない。
- 記録: `outputs/sample5/01a18ddc-dd53-7ab2-9563-55e861edfed9/upgrade.log`と`state-upgrade.json`。
- 結果: 再起動後に`/health`がHTTP 200となってからUpgradeを再実行したが、DoclingのGET状態確認も約14分後に6回の接続再試行を使い切り`ConnectError`で失敗した。
- 影響: Doclingはhealth応答後も処理中に接続が切れ、Upgradeを完了できない。
- 記録: `outputs/sample5/01a18df6-d862-7d81-8568-e2c1c881ebc0/upgrade.log`と`state-upgrade.json`。

## 🧭 Review/Upgrade結果画面の見出しがTranslateのまま

- 再現条件: ReviewまたはUpgradeの完了結果をUIで表示する。
- 結果: 完了したReview/Upgradeの結果画面でも大見出しが`Translate`と表示される一方、履歴と進捗にはReview/Upgradeと表示される。
- 影響: 結果画面の処理種別が分かりにくい。
- 記録: `.tmp/acceptance/sample5-review.png`、`.tmp/acceptance/sample5-upgrade.png`。

## ♻️ worker終了後にprocessing状態の処理をUIからResumeできない

- 再現条件: UI workerが終了し、処理記録が`processing`のまま残る。
- 結果: UIはprocessing記録にStopだけを表示し、Resume操作は終端状態の記録にしか表示しない。
- 影響: 保存済み入力があっても同じ処理を再開できない。
- 確認: `scripts/real_ui_step.py review --resume 01a17fd8-05f4-7ff2-b419-ec1cf05793f1` はResumeボタン待ちでタイムアウト。条件は`translate/ui/app.py`の`_render_processing_panel`。

## 🔎 sample5 TranslateのEmbedding応答が長時間戻らない

- 再現条件: `sample5.pdf`をTranslateする。
- 結果: DoclingとSTRUCTUREは成功し、最初のTRANSLATE callも成功したが、その後のEmbedding requestが7分以上完了しない。LiteLLM `/v1/models`はHTTP 200でも、`/health`は5秒でtimeoutした。
- 影響: Translateが長時間停滞し、全ユニット処理に大幅な時間がかかる。
- 記録: `outputs/sample5/01a18489-706b-7c60-b014-f563dbda2932/translation.log`。

- 再現条件: `sample4.pdf`をRegisterする。
- 結果: Docling変換後、38件のEmbedding要求が約8分後に完了した。待機中、接続先`192.168.1.100:31000`の`/health`と`/v1/models`はタイムアウトした。
- 影響: RegisterがEmbedding工程で長時間停滞する。
- 記録: `outputs/sample4/01a18e67-0569-7aa3-a3eb-7f05f8747210/registration.log`。



- 再現条件: `sample4.pdf`をTranslate後、生成PDFをReviewする。
- 結果: 2分割されたDocling変換とReviewは成功したが、一部LLM応答で`LLMInvalidResponseError`が発生し、再試行後に処理が継続した。
- 影響: Review完了まで約32分かかった。
- 記録: `outputs/document.ja-office/01a18e8d-12dc-70d2-a6d8-f8cbb95ef0ff/review.log`、`.tmp/acceptance/sample4-review.png`。

- 再現条件: `sample3.pdf`をRegisterする。
- 結果: 63件のEmbedding要求が約10分後に完了し、Qdrant登録は成功した。
- 影響: RegisterがEmbedding工程で約10分停滞する。
- 記録: `outputs/sample3/01a18ee5-2626-7fe2-9c79-39ad484105f8/registration.log`。

- 再現条件: 16ページの`sample3.pdf`と生成訳文PDFをReviewする。
- 結果: Reviewは成功したが、LLM応答の形式不正による再試行と、短すぎる出力が発生した。
- 影響: Review完了まで約54分かかった。
- 記録: `outputs/document.ja-office/01a18f13-c504-7c72-81b0-8ff47ea5b89b/review.log`、`.tmp/acceptance/sample3-review.png`。

- 再現条件: 16ページの`sample3.pdf`でUpgradeを実行する。
- 結果: Upgradeは成功したが、DIFF工程に282件のLLM呼び出しが発生し、多数の`LLMInvalidResponseError`再試行と短い出力があった。
- 影響: Upgrade完了まで約90分かかった。
- 記録: `outputs/sample3/01a18f45-e2c8-7e23-914a-2b88d15f19d0/upgrade.log`、`.tmp/acceptance/sample3-upgrade.png`。

- 再現条件: 9分割された`sample2.pdf`をRegisterする。
- 結果: 237件のEmbedding要求が約38分後に完了し、Qdrant登録は成功した。
- 影響: RegisterがEmbedding工程で約38分停滞する。
- 記録: `outputs/sample2/01a18f98-4520-7643-9113-47712309dfb2/registration.log`。

## 🧩 sample2 Upgradeが同一セルのmatch再試行後にTimeoutErrorで失敗する

- 再現条件: 88ページの`sample2.pdf`をUpgradeする。
- 結果: DIFFのround 142〜153で、`source_v1:#/tables/1/cell-r0035-c0001/content`と対応する`source_v2`セルが同じmatch対象として12回連続した。各callはLLM応答不正で5回試行後に失敗し、DIFFは`Upgrade target group exceeded 12 Agent steps`の`TimeoutError`で終了した。
- 影響: 対象セルを処理できず、Upgradeが65分後に失敗する。
- 記録: `outputs/sample2/01a190b1-157a-7131-9b8f-71543b87efc3/tasks/21-diff/calls`、`upgrade.log`、`state-upgrade.json`。

- 再開確認（2026-11-01 22:37 JST）: 保存済み3入力のSHA-256一致を確認し、既存IDを直接Resume。round 142は以前失敗したcellを含む範囲で成功。大きな比較範囲でLLMInvalidResponseErrorが出るものの、round 144、146、149〜151は成功して先へ進んだ。現在round 152を再試行中でstateはprocessing、最終結果は未確定。
## 🕰️ sample2 ReviewのLLM再試行で完了まで長時間かかる

- 再現条件: 88ページの`sample2.pdf`と翻訳PDFをReviewする。
- 結果: Reviewは173件のLLM callを経て成功した。一部で`LLMInvalidResponseError`と`LLMOutputTokenExceededError`が発生し、再試行後も処理を継続した。
- 影響: Review完了まで約2時間7分かかった。
- 記録: `outputs/document.ja-office/01a1903a-f097-7933-bf46-58c373dcba01/review.log`、`.tmp/acceptance/sample2-review.png`。


## ⏳ sample1 RegisterのEmbedding応答が長時間戻らない

- 再現条件: 65MBの`sample1.pdf`をRegisterする。
- 結果: Doclingは36分割を処理した後、1038件のEmbedding要求を開始し、応答まで2時間55分29秒かかった。その後、Qdrantに1038 pointを登録してRegisterは`succeeded`となった。待機中は`processing`が続いた。
- 影響: Register完了まで約3時間かかり、Translate以降へ進めなかった。
- 記録: `outputs/sample1/01a190ec-d088-7702-8be3-fde5c83ba61b/registration.log`、`state-registration.json`。


## ⏳ sample1 Translate の処理に長時間を要する

- 2026-10-31 12:13 UTCに開始したTranslateが、2026-11-01 00:51 UTC時点でも処理中（約12時間38分）。
- 翻訳呼び出しフォルダーは318件。各ユニットでEmbedding（約15〜35秒）・Qdrant検索・LLM翻訳（約15〜30秒）が逐次実行され、直近も進行は継続している。
- 既知のSTRUCTURE計画667件を踏まえると、この大規模文書のTranslateは実運用上非常に長い。完了後、最終件数・所要時間を追記する。
- 証跡: outputs/sample1/01a191a6-1246-7b62-94ab-122a69cde35a/translation.log、tasks/30-translate/calls/。


## ❌ sample1 Translate がEmbedding HTTP 500で失敗

- Translate開始は2026-10-31 12:13 UTC。翻訳呼び出し406件の後、生成文書のREVIEW品質処理へ進み、tasks/41-review/calls/ が349件まで増加した。
- 約18時間後の2026-11-01 05:31 UTC、品質処理中のEmbedding要求がattempt 1〜5で再試行した後、attempt 6でHTTP 500となり、Translate全体がfailed。
- 証跡: outputs/sample1/01a191a6-1246-7b62-94ab-122a69cde35a/translation.log。
- 翻訳は406/406件完了。失敗タスクはTranslate内のREVIEW品質処理で、failed callは1件（表13の8セル）。その直前までレビューcall 348件が成功済み。
- stateのerrorはretryable=trueだが、outputsは空で翻訳タスク自体の成果物もstateに未登録。Translate全体のResumeは再翻訳・再レビューの重複実行になる可能性があり、UI経由のResume可否・挙動は未検証。
- 品質処理は失敗後も状態更新がなく、数分後もfailedのまま。
- 失敗記録のFingerprintは c1ddda48394e5751b53510e2def26e11866a17e1df395f622bd842a793fac025。targetはtable 13のCOA 2/COA 3行を含む8セル。失敗後に設定済みOPENAI_API_KEYで/v1/modelsを照会すると200、同一8セルのテキストを/v1/embeddingsに送ると200・1024次元だった。
- Resumeボタン操作はrunnerが30秒以内に処理IDを返さず、state-translation.json・translation.logに更新なし。再試行でも同じ。保存済みsample1.pdfは存在する。再開手順/ UI遷移の不具合を別途調査する。



## ⏳ sample1のReview/Upgrade受け入れ検証が未完了

- 2026-11-01時点でsample1 Translateジョブ 01a191a6-1246-7b62-94ab-122a69cde35a はREVIEW品質処理のEmbedding HTTP 500でfailed。失敗後の同一入力Embedding要求はHTTP 200/1024次元を確認済み。
- scripts/real_ui_step.py translate --resume <id> を複数回実行したが、UI操作runnerは30秒超無応答。保存済み入力 outputs/sample1/<id>/inputs/translate/sample1.pdf はあり、state/translation.logは不変。
- 2026-11-01の再確認でも、uv run --offline python -c ... および .venv/Scripts/python.exe -V が30秒超無出力。直接Pythonの処理を起動・検証できないため、sample1のReview/Upgradeは未完了。実行環境のPython/uv起動経路復旧後、Translate Resumeと全工程検証を再開する。
- 既存成功記録上はsample、sample5、sample4、sample3、sample2でRegister/Translate/Review/Upgradeまで完了。sample2 Upgradeの先行失敗は後続の新規成功ジョブで解消済み。


## ⏳ sample1 Translate Resume後のREVIEW品質チェックが低速

- 再現条件: Embedding HTTP 500で失敗したsample1 Translate（`01a191a6-1246-7b62-94ab-122a69cde35a`）をUIからResumeする。
- 結果: Resumeは開始でき、失敗したREVIEW callのEmbeddingは再試行後に成功した。その後も1件ずつEmbedding・Qdrant検索・LLM呼び出しが進行するが、Embeddingに約15〜60秒かかり、LLM応答不正による再試行も発生。2026-11-01 12:39 JST時点でREVIEW品質チェックはprocessingのまま継続中。
- 影響: 既にTRANSLATE（406件）が完了した文書でも、失敗後Resumeの品質チェック完了まで長時間かかる。
- 追跡結果: 2026-11-01 13:36 JST時点で成功callは471件（split 5件、processing 1件）まで増加したが、Translate全体は引き続きprocessingで、outputsも未確定。処理は継続する一方、再開から約1時間9分経過しても品質チェックが完了していない。
- 最終結果: 同日13:39 JSTにTranslateが`succeeded`。Translate 406/406、内包REVIEWは473 planned / 473 completed（339 reused、failed 0）、DOCX 22,762,048 bytesを生成。Resumeから約1時間12分を要した。
- 記録: `outputs/sample1/01a191a6-1246-7b62-94ab-122a69cde35a/translation.log`、`tasks/41-review/calls/`、`state-translation.json`。


## ⏳ sample1 Review の処理時間が長い

- 再現条件: sample1 Translate が生成した訳文PDF（Word変換）と原文PDFでReviewする。
- 結果: Review `01a1956c-0f32-7a40-a128-a08f86f2354a` は開始後約110分時点でもREVIEWタスクがprocessing。Doclingは原文36/36、訳文38/38を完了し、判定callはround 173まで進行中。LLMInvalidResponseErrorで再試行上限に達したcallも複数発生。判定中にLLMInvalidResponseErrorで複数回の再試行と失敗callが発生しても処理は継続した。
- 影響: 65MB・357ページのPDFでは、Docling変換とReview判定に長時間を要し、後続Upgradeを開始できない。最終結果は追跡中。
- 記録: `outputs/document.ja-office/01a1956c-0f32-7a40-a128-a08f86f2354a/review.log`、`state-review.json`、`tasks/01-docling/*/docling-progress.json`。

## ⏳ sample1 UpgradeのDIFFでLLM応答不正が繰り返す

- 再現条件: 357ページ・23表（原文正規化後990セル）と6,421テキストunitのsample1原文、新版（末尾ページ除外）、sample1訳文PDFでUpgradeする。
- 結果: Upgrade `01a195f9-109d-7c41-8b24-04233ab82879` は3入力のDocling変換後、開始から約1時間54分でDIFFのcallが380件（round 379）まで増加し、開始から約3時間後の2026-11-01 19:18 JST時点でもprocessing。複数callで`LLMInvalidResponseError`が再試行上限後にfailedとなる。round 348〜359では同一対象（`source_v1/source_v2:#/tables/3/cell-r0007-c0001/content`）が12回連続で失敗し、round 360で成功した。続くcell-r0007-c0002はround 361の失敗後round 363までに次候補へ進んだ。またcell-r0011-c0001もround 377〜385の9回連続失敗後、round 386で成功し、round 387で次セルへ進んだ。round 393〜394で別セルも同様に失敗後、round 395で成功し次へ進んでいる。
- 影響: UpgradeのDIFFが長時間化し、LLM応答不正が同じ対象で長く続いても、完了まで後続判定に進めない。
- 記録: `outputs/sample1/01a195f9-109d-7c41-8b24-04233ab82879/upgrade.log`、`tasks/21-diff/calls/`、`state-upgrade.json`。
- 進捗更新（2026-11-01 22:37 JST）: 同じUpgradeジョブは継続中。text 714のLLM応答不正は再試行後に解消し、round 1084（text 752）は成功、round 1085（text 756）が処理中。累計1,086 call。DIFF完了前のため最終結果を継続確認する。