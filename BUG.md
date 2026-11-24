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
- 再発（2026-11-12 23:43、HEAD `9bc1892`と未コミットの変更）: sample5のUpgradeで、Doclingの状態確認GETが4回応答なしの後にHTTP 404となり`HTTPStatusError`で失敗した。Docling側で変換taskが失われたとみられる。実機検証`20261112-195025-4baa45ca`は、sampleの4工程とsample5のRegister、Translate、Reviewが成功した後に停止した。コードは変わっていないため、`-StartAt sample5`でsample5から再実行した。記録: `outputs/sample5/01a1d01a-0a73-7091-9c2d-c98322fdb296/upgrade.log`。
- 再発（2026-11-13 23:36〜11-14 03:46、HEAD `9bc1892`と未コミットの変更）: sample2のRegisterで、Docling変換POSTが50分ごとに6回応答なしとなり`ReadTimeout`で失敗した。失敗直後は`/health`も応答しなかった。実機検証`20261113-224636-86aa4d70`はsample2のRegisterで停止した。製品コードは変わっていないため、Doclingの応答が戻ってから`-StartAt sample2`で再実行した。記録: `outputs/sample2/01a1d529-30f7-7aa3-b324-60cbed8c2104/registration.log`。
- 再発（2026-11-15 00:32〜01:02、HEAD `9bc1892`と未コミットの変更）: 利用者がDoclingを再起動し11-14 20:20に再開したsample2のRegisterは成功したが、11-15 00:32の再実行では開始時点からDoclingが接続を拒否し、約30分の回復待ちの後に`ConnectError`で失敗した。失敗後も`/health`は応答しなかった。Doclingの応答が戻ってから`-StartAt sample2`で再実行する。記録: `outputs/sample2/01a1dab0-58b1-7c11-b5d1-5c8b3c9a688a/registration.log`。

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

- 再現確認（2026-11-01）: sample2 Upgradeの再開処理はround 156まで進行した後、worker processが終了。state-upgrade.jsonとDIFF taskがprocessingのまま残り、error/completed_atも設定されなかった。保存済み入力は再開時にSHA-256一致済み。
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

- 再開確認（2026-11-01 22:47 JST）: 保存済み3入力のSHA-256一致を確認し、既存IDをResume。round 142、144、146、149〜156は成功した後、worker終了でstateがprocessingのまま残った。2回目のResume後はround 163まで成功し、round 164を実行中。最終結果は未確定。
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


## ❌ sample1 Reviewが入力上限超過後にTimeoutErrorで未完了

- 再現条件: sample1 Translate が生成した訳文PDF（Word変換）と原文PDFでReviewする。初回ReviewがTimeoutErrorになったため、保存済み入力のhash一致を確認し、2026-11-02 01:52 JSTに同じReview ID `01a1956c-0f32-7a40-a128-a08f86f2354a`をResumeした。
- 結果: Docling変換は原文36/36、訳文38/38を完了したが、Resumeから約50分後の02:42 JSTにstateが`failed`となった。終端エラーは`TimeoutError: REVIEW did not complete.`。callは323件で、265件成功・58件失敗（`LLMInputExceededError` 45件、`LLMInvalidResponseError` 13件）。round 287〜293では同じ16対象が7回、round 294〜298では同じ14対象が5回連続で`Selected document scope exceeds REVIEW_INPUT_TOKENS`となり、処理が進まないままReview Agentのstep/time limitに達した。Review成果物は生成されていない。
- 影響: 大規模文書の一部対象がReview入力上限を超えると、同じ対象を繰り返し試して全体ReviewがTimeoutErrorで失敗する。対象を確実に小さく分割するか、個別対象を明示的に処理不能として記録して残りを完了できる対策が必要。
- 記録: `outputs/document.ja-office/01a1956c-0f32-7a40-a128-a08f86f2354a/state-review.json`、`review.log`、`tasks/41-review/calls/`、`.tmp/acceptance/sample1-review-resume.err`.

## ❌ sample1 UpgradeのDIFFが入力上限超過で未完了

- 再現条件: 357ページ・23表（原文正規化後990セル）と6,421テキストunitのsample1原文、新版（末尾ページ除外）、sample1訳文PDFでUpgradeする。
- 結果: Upgrade `01a195f9-109d-7c41-8b24-04233ab82879` は3入力のDocling変換後、開始から約1時間54分でDIFFのcallが380件（round 379）まで増加し、開始から約3時間後の2026-11-01 19:18 JST時点でもprocessing。複数callで`LLMInvalidResponseError`が再試行上限後にfailedとなる。round 348〜359では同一対象（`source_v1/source_v2:#/tables/3/cell-r0007-c0001/content`）が12回連続で失敗し、round 360で成功した。続くcell-r0007-c0002はround 361の失敗後round 363までに次候補へ進んだ。またcell-r0011-c0001もround 377〜385の9回連続失敗後、round 386で成功し、round 387で次セルへ進んだ。round 393〜394で別セルも同様に失敗後、round 395で成功し次へ進んでいる。
- 最終結果: 2026-11-01 15:10 UTC（11-02 00:10 JST）、round 1326でsource_v1/source_v2の`#/texts/1419/content`を処理する際、`Selected document scope exceeds REVIEW_INPUT_TOKENS`（`LLMInputExceededError`）が発生。callは1回でfailedとなり、Upgradeは`DIFF did not complete.`（`InputError`、retryable=true）でfailed、成果物は生成されなかった。
- Resume後は以前timeoutしたtext 1190を成功させたが、text 1419の入力予算超過で停止した。変更前のジョブも同じUpgrade ID・同じ入力でResumeし、失敗位置まで処理を進めた。
- 影響: 大規模文書の一部unitが入力上限を超えるとDIFF全体が完了せず、成果物を得られない。入力超過unitの分割・縮小または明示的なskip/フォールバックが必要。
- 記録: `outputs/sample1/01a195f9-109d-7c41-8b24-04233ab82879/upgrade.log`、`tasks/21-diff/calls/`、`state-upgrade.json`。
- 進捗更新（2026-11-01 23:19 JST）: 同じUpgradeジョブは継続中。text 815は8回、text 1060は3回、text 1152・1184は各1回のLLMInvalidResponseError後に回復。round 1205（text 1181）まで成功し、round 1206（text 1182）処理中。累計1,207 call。
- 最終更新（2026-11-02 00:10 JST）: Upgradeはround 1326でfailed。途中のLLMInvalidResponseErrorやLLMTimeoutErrorはResumeと再試行で後続へ進んだが、text 1419の入力上限超過が最終停止要因となった。失敗時の状態は`outputs/sample1/01a195f9-109d-7c41-8b24-04233ab82879/state-upgrade.json`。
## ⏳ sample2 UpgradeのDIFF処理が長時間化

- 再現条件: sample2の原文2版と訳文PDFでUpgradeする。Upgrade `01a190b1-157a-7131-9b8f-71543b87efc3` はround 142〜156まで進んだ後、stateは`processing`のままworkerが消失したため、保存済みの同一入力（SHA-256一致）で同じIDをResumeした。Resume workerも途中で終了したため再度Resumeし、2026-11-02 01:50 JSTに処理完了。
- 追跡結果: round 857（text 1096）まで到達。複数の`LLMInvalidResponseError`が発生したが、多くは後続callで回復。最終call後にstateは`succeeded`となり、DIFF成果物が作成された。Resume実行から約2時間28分（開始・終了UTC時刻の差）。
- 影響: sample2のUpgrade完了まで長時間を要し、worker停止後のstateがprocessingのまま残るケースもある。
- 記録: `outputs/sample2/01a190b1-157a-7131-9b8f-71543b87efc3/upgrade.log`、`tasks/21-diff/calls/`、`state-upgrade.json`.

## 🔌 LLM endpoint停止中にTranslateが数秒で失敗する

- 再現条件: `OPENAI_LLM_BASE_URL`の`192.168.1.183:1234`が接続を拒否している状態でTranslateを実行する。
- 結果: 2026-11-02 20:19、STRUCTUREの全試行が`LLMConnectionError`となり、約15秒でTranslateが`failed`になった。直接の接続確認も`WinError 10061`で拒否された。endpoint復旧後は再実行で先へ進んだ。
- 影響: Docling断線と異なりLLMの短時間の停止を待機しないため、数秒の再試行枠を使い切ると処理全体が止まる。
- 記録: `outputs/sample/01a19bfb-981d-71b1-9860-7f18c1459fb9/translation.log`、`state-translation.json`。

## 🧾 受け入れスクリプトが日本語を含む処理記録を解析できない

- 再現条件: 失敗理由に日本語を含む処理記録を`scripts/real_acceptance.ps1`が読む。
- 結果: PowerShell 5の`Get-Content`がUTF-8を既定で解釈せず、`ConvertFrom-Json`が例外になった。
- 影響: 本来の失敗理由が表示されない。
- 対応: `cb409ad`で`-Encoding UTF8`を指定して修正済み。

## 🪝 rulesyncのguard hookが日本語を含むコマンドを拒否する

- 再現条件: Windowsで日本語を含むBashコマンドを実行する。
- 結果: `.rulesync/hooks/harness.py guard`が`Destructive or unknown shell command blocked by project hook.`で拒否した。破壊的な操作は含まない。
- 原因の推定: `sys.stdin`をcp932で読み、JSON解析に失敗して「不明なコマンド」扱いになると見られる。コードからの推定で、再現試験は未実施。
- 影響: コミットメッセージなどを直接渡すコマンドが実行できない。
- 対応: 未修正。`sys.stdin`をUTF-8で読む修正を想定する。


## 🧭 操作選択の応答不正が続くとReviewがTimeoutErrorで失敗する

- 再現条件: `sample.pdf`と訳文PDFをReviewする。再現性はなく、同じ状態から再生すると先へ進んだ。
- 結果: 2026-11-02 21:41、round 33の後に`choose_action`の`LLMInvalidResponseError`が連続し、Agentの12手上限で`TimeoutError`となった。応答検証の詳しい理由はログに残っていなかった。
- 影響: 残り作業が明確でも、操作選択の失敗だけでReview全体が止まる。
- 対応: 連続3回の不正で状態から決まる次の操作へ進め、拒否理由をログへ残すよう修正した。
- 記録: `outputs/document.ja-office/01a19c28-1c4a-7c23-9850-89614f2a31e6/review.log`、`tasks/41-review/calls/`。

## 🧭 進捗のない照合が続くとReviewが評価を行わずTimeoutErrorで失敗する

- 再現条件: `sample.pdf`と訳文PDFをReviewする（2026-11-10、HEAD `579e8f9`）。
- 結果: Agentが未対応unitの照合を165回選び、評価を一度も選ばないまま進捗のない12手に達し、未評価の対象が残るため`TimeoutError`となった。LLM要求370件はすべて成功しており、外部APIの問題ではない。
- 影響: 対応付けが済んだ対象があっても、Review全体が失敗する。
- 対応: 進捗のない手数が上限に達した後は、競合の再確認、未評価の評価、未照合の照合、終了の順に状態から操作を決めて残作業を完了させるよう修正した。切り替え後も進まない場合だけ停止する。
- 記録: `outputs/document.ja-office/01a1c2db-5847-7ae3-99ee-51865d5db8de/review.log`、`tasks/41-review/calls/`。

## 🌐 Embedding要求のタイムアウトで実機検証が停止する（範囲外）

- 再現条件: 実機検証のTranslateで、RAG用のEmbedding要求を送る（2026-11-10 20:0x、HEAD `1634faa`）。再現性はない。
- 結果: `EmbeddingError`（要求の時間切れ）でTranslateが失敗し、実機検証が停止した。
- 影響: 外部APIの一時的な遅延だけで、実機検証を先頭からやり直す必要がある。
- 対応: 外部APIの安定性は今回の範囲外のため、記録だけ行い再実行した。
- 記録: `outputs/sample/01a1c51d-373e-72d3-892a-433596c5f31b/translation.log`。
- 再発（2026-11-11 04:57、HEAD `1634faa`）: sample3のReviewで、16件のEmbedding要求が約3分応答せず`EmbeddingError`となった。実機検証`20261110-200735-a65687bc`は、sample〜sample4の16工程とsample3のRegister、Translateが成功した後に停止した。コードは変わっていないため、`-StartAt sample3`でsample3から再実行した。記録: `outputs/document.ja-office/01a1c6f8-d2ed-74e2-9f3a-9d20d47759af/review.log`。
- 再発（2026-11-11 22:39、HEAD `1634faa`）: sample1のTranslateで、1件のEmbedding要求が約2分後に接続失敗となり`EmbeddingError`で失敗した。実機検証`20261111-050121-a17050f4`は、sample3〜sample2の8工程とsample1のRegisterが成功した後に停止した。コードは変わっていないため、`-StartAt sample1`でsample1から再実行した。記録: `outputs/sample1/01a1ca24-1db5-77c2-95ec-82a4ee6f86b3/translation.log`。
- 再発（2026-11-13 22:45、HEAD `9bc1892`と未コミットの変更）: sample2のTranslateでEmbedding要求が時間切れとなり`EmbeddingError`で失敗した。実機検証`20261113-064015-2e593111`は、sample〜sample3の16工程とsample2のRegisterが成功した後に停止した。製品コードは変わっていないため、`-StartAt sample2`でsample2から再実行した。記録: `outputs/sample2/01a1d3cd-c8b9-79e1-ad22-82a696743cac/translation.log`。
- 再発（2026-11-14 21:10〜11-15 00:31、HEAD `9bc1892`と未コミットの変更）: sample2のTranslateで、1件のEmbedding要求が約3時間20分応答せず、最後にHTTP 429で`EmbeddingError`となった。実機検証`20261114-202013-69c9eba1`はsample2のRegister成功後に停止した。失敗後、接続先`192.168.1.100:31000`は応答していた。製品コードは変わっていないため、`-StartAt sample2`で再実行した。記録: `outputs/sample2/01a1d9ee-2dcf-7802-a90d-1d1e9f02a2c9/translation.log.2026-11-14`と`translation.log`。
- 再発（2026-11-15 05:38、HEAD `9bc1892`と未コミットの変更）: Docling復旧後に再開したsample2のRegisterで、237件のEmbedding要求がHTTP 500で失敗した。製品コードは変わっていないため、時間をおいて`-StartAt sample2`で再実行した。記録: `outputs/sample2/01a1dbc4-e07e-7412-b322-35ceb932d2a7/registration.log`。
- 中断（2026-11-16 08:34〜11-18、HEAD `9bc1892`と未コミットの変更）: 実機検証`20261115-214801-df24d278`は、sample〜sample3の16工程とsample2のRegisterが成功した後、sample2のTranslateでEmbedding要求の開始を最後にログが止まった。この間に検証用PCのスリープ復帰（11-16 19:36）と再起動（11-17 19:54）があり、検証プロセスは終了していた。製品コードは変わっていないため、11-18 09:09に`-StartAt sample2`で再実行した。記録: `outputs/sample2/01a1e15c-bdf1-77b1-878b-c8cd8814045d/translation.log`。
- 中断（2026-11-19 08:41、HEAD `9bc1892`と未コミットの変更）: 実機検証`20261118-120141-af6f2abd`は、sample2の全4工程とコラム確認、sample1のRegisterが成功した後、sample1のTranslate（STRUCTURE・TRANSLATE・REVIEW・FIXは完了）の途中で、検証用PCがスタートメニューから電源を切られて終了した。製品コードは変わっていないため、11-19 23:17に`-StartAt sample1`で再実行した。記録: `outputs/sample1/01a1eed8-67cb-7153-8b5f-13a32e8382b6/translation.log`。
- 中断（2026-11-20 08:36、HEAD `9bc1892`と未コミットの変更）: 再実行`20261119-231759-cf8b0496`も、sample1のRegister成功後、TranslateのREVIEW中に検証用PCの電源が切られて終了した。sample1はTranslateだけで約20時間かかり、検証スクリプトは途中から再開できないため、利用者の判断でsample1のTranslate以降の検証を終了した。記録: `outputs/sample1/01a1f4e1-7142-7113-ade9-88fa7f511bb8/translation.log`。

## 🧷 コラム追加の位置が訳文の表現差で見つからず実機検証が停止する

- 再現条件: 実機検証でsampleのTranslate後、`scripts/add_translation_columns.py`が訳文DOCXへコラムを追加する（2026-11-12 19:49）。
- 結果: 新しい訳文は見出しを「数式」ではなく「方程式」と訳しており、挿入位置の語句が見つからず`ValueError`で検証が停止した。
- 原因: 挿入位置を一つの語句だけで探していた。訳文の表現は実行ごとに変わる。
- 対応: 語句の候補を追加し、どの語句も見つからない場合は文書内の決まった位置の本文段落の後ろへ挿入して検証を続けるようにした。検証は先頭からやり直した。
- 記録: `.tmp/acceptance/20261112-193658-014e0fd9/state.json`。
- 関連（2026-11-13、検査スクリプト）: sample3のReviewで、コラム本文と直後の本文行「ジョージ・W・ブッシュ大統領 2003年10月」が日本語PDFの抽出で一つのunitへ結合された。Reviewは本文行の部分で原文と対応付け、このunitへの指摘・修正はなかったが、検査は`translation_only`でないことを`COLUMN FAIL`とした。検査を、コラムだけのunitは`translation_only`であること、本文と結合したunitは修正後もコラムの文が変わらないことを確かめるよう改めた。改めた検査でsample〜sample3のReviewはすべて合格した。記録: `outputs/document.ja-columns/01a1d34a-d27a-78d1-b936-0e7f8f9cb5a2/tasks/41-review/review.json`。

## 🔁 分割できない最小の対象で出力上限に達しReviewが停止する

- 再現条件: 実機検証`20261112-234510-00b3cd24`でsample5のReviewを実行する（2026-11-13 02:18、HEAD `9bc1892`と未コミットの変更）。
- 結果: 1組だけの評価対象`review/alignment-000021`（入力は他の組と同程度の約5,000 token）で、生成が約3分続いて`REVIEW_OUTPUT_TOKENS=8192`に達し、`LLMOutputTokenExceededError`でReviewが失敗した。他の組の出力は約90 tokenだった。
- 原因: 小さい入力でも生成が反復して出力上限へ達することがある。これ以上分割できない対象では、分割による継続ができず失敗を伝えていた。Upgradeの起点だけの比較も同じだった。
- 対応: 分割できない対象の出力超過・応答不正は、`LLM_RETRY_ATTEMPTS`回まで同じ要求を生成し直すようにした。入力超過は従来どおり失敗とする。実機検証は先頭からやり直した。
- 記録: `outputs/document.ja-columns/01a1d086-7330-7302-a982-7eb01f20592b/review.log`。
- 再発（2026-11-13 05:58、上記の対応後）: 同じ対象が5回の生成し直しですべて出力上限に達した。対象は原文が数式だけのunit（同じ6列行列が繰り返される約3,200文字のLaTeX）で、訳文側は数式が2つのunitに分かれて文字として抽出されていた。LLMが数式全体を書き直す修正を出力し、反復が止まらないため偶発ではなかった。
- 対応（再発分）: 数式・コードは翻訳せず原文の記法を残す対象のため、原文が数式・コードだけの組は対応だけを記録し、品質確認へ送らないようにした。実機検証は先頭からやり直した。記録: `outputs/document.ja-columns/01a1d141-a890-74a1-a65d-363124c9d8c6/review.log`。

## ♻️ 訳文を変えない修正案を繰り返しReviewが停止する

- 再現条件: 実機検証`20261113-060352-7be2ce58`でsampleのReviewを実行する（2026-11-13 06:35、HEAD `9bc1892`と未コミットの変更）。
- 結果: 評価対象`review/alignment-000041`で、LLMが抽出空白だけを変える、または訳文を変えない修正案を返し続けた。再要求5回と生成し直し5回の計25回すべてが同じ理由で拒否され、`LLMInvalidResponseError`でReviewが失敗した。
- 原因: 訳文を変えない修正案を応答不正として再要求していた。LLMは同じ判断を繰り返すため、再要求では解消しなかった。
- 対応: 訳文を変えない修正案は、日付の区切り差と同様に再要求せず不備なしとして確定するようにした。実機検証は先頭からやり直した。
- 記録: `outputs/document.ja-columns/01a1d19e-4019-7800-bbb9-5109add1e2d3/review.log`。

## 🏷️ 本文の見出しに似たコラムの見出しが英文と対応付けられ修正される

- 再現条件: 実機検証`20261115-054915-e02d1b7f`でsample2のReviewを実行する（2026-11-15、HEAD `9bc1892`と未コミットの変更）。
- 結果: 追加したコラムの見出し「コラム：情報の質の基準について」が英文の見出し`INFORMATION QUALITY CRITERIA`と対応付けられ、「コラム：」を不要とする指摘と、見出しを「情報の質の基準」へ書き換える修正提案が作られた。コラムの本文は訳文のみとして正しく扱われた。
- 原因: コラムを対応付けない規則をLLMへの指示だけで守らせていた。コラムの見出しが本文の見出しとほぼ同じ語句だったため、LLMが対応付けた。
- 対応: 「コラム：」「訳注：」「訳者注：」「補足：」で始まる訳文の要素は、ReviewとUpgradeの照合・比較の候補から除くようにした。実機検証は先頭からやり直した。
- 記録: `outputs/document.ja-columns/01a1dc69-b0f2-7b81-b3ea-097a3c2ea31c/tasks/41-review/review.json`。

## 📏 providerの入力上限超過が分割されずTranslateが停止する

- 再現条件: 実機検証`20261118-090914-098b2a44`でsample2のTranslateを実行する（2026-11-18 11:55、HEAD `9bc1892`と未コミットの変更）。
- 結果: 翻訳後の品質確認で8件の評価対象をまとめた要求が、endpointからHTTP 400（診断`category=input_limit`）で拒否され、`LLMProviderError`としてTranslateが失敗した。送信前の入力検査は通過していた。
- 原因: 分割へ回すcontext超過の判定が既知の文言の一覧だけで行われ、診断で入力上限と分類した応答の文言が一覧になかった。そのため分割せず、通常のHTTPエラーとして停止した。
- 対応: 診断で入力上限と分類したHTTP 400もcontext超過として扱い、対象を分割して続けるようにした。この変更はこのエラーを受けた場合の動作だけを変え、受けずに合格したsample〜sample3の結果は変わらないため、実機検証はsample2から再開した。
- 記録: `outputs/sample2/01a1ec21-1aff-7412-992a-ab331002968f/tasks/41-review/calls/call-c453f171c3730701587c3b5fdad5e59b065d2d60357a903d3804a7b79caf963b/call.json`。
