<!-- markdownlint-disable MD013 MD041 -->

## Apply検証（2026-09-26）

4/5 tasks完了。実Modelの新規E2Eと正式verify・archiveは未完了。

- 実装前にWindowsのProcess一覧でPython/uvが存在しないことを確認した。
- 本番`run_public_run_detached()`の実`python -m`起動へ、Test専用sitecustomizeで設定と公開処理fixtureを注入した。socket接続を禁止し、Run入力と終端JSONは実際に保存する。製品処理全体の実E2Eではない。
- 修正前: 成功/公開失敗の2ケースとも、status・exit・実行1回・cleanup検査を通過した後、期待2/1/3に対してLLM/Embedding/Qdrant計数が0/0/0で失敗。2 failed、7.55秒。
- 修正後: `__main__`入口を通常importした既存`main()`へ委譲し、同2ケースが期待値を保存。2 passed、7.96秒。新Module・依存・計数台帳・設定・Schema変更なし。
- 実LLM Adapterと応答stubによる検査では、一時接続失敗→成功は2試行、有限retry終了の失敗は3試行。各ケースを連続2回束縛して値の混入がないこと、束縛解除後のhookが以前の値を変更しないこと、外部socket呼出し0を確認した。
- 関連Testは41 passed、11.55秒。既存context入れ子・例外復元、実convert child、watchdog、JSON排他/直接書込み、cleanupを含む。秘密sentinelをFailure理由へ入力しても終端JSONに含まれないことを確認した。
- 最初のself関数importはtyが解決できなかったため、module importと属性呼出しへ調整した。`__main__`と通常moduleの区別が目的のため、当該1行だけRuff PLW0406を説明コメント付きで抑止した。全体の規則は変更しない。
- 最終版の全体検査: Ruff check成功、format 362 files、ty成功。pytest session 76689は732 passed / 1 skipped、47.58秒、exit 0。WindowsでPOSIX PTY試験をskip。前のsuite session 92440も732 passed / 1 skipped、48.91秒で終了したが、途中のimport調整後に開始した76689を最終証拠とする。二つの自動Test実行は一部重なった。実Model/Embedding処理は起動していない。
- OpenSpec strict validationとgit diff --check成功。

検査基点はa8f17c9と既存未commit差分を含むworktree。製品File SHA-256はac595e2e298bc2cdc62ebe82e53586fe63131e9c6fdf1b6ff9bcc83f175470f1、Testは88e115a36f176d0639b746793be940a4e372a3af0e2fdb21b49760d50d97412b。製品hashには既存FailureKind/context-exceeded差分も含むが、その1行を本commitに含めない。他の既存差分・.agents・サンプル・outputs/runsも含めない。

## 計測の限界と残る指摘

- 旧比較Run 01a0d8e0-73da-73e0-97b9-e1d0bcf442f2の0値は計測不成立。原記録を保持し、未呼出しの証拠として使わない。
- LLMはAdapterのinvoke試行数。Langfuse spanはretryを内包するため、件数は無条件には一致しない。
- EmbeddingはClient生成試行数、Qdrantは登録Client生成と検索retry外のhook回数。物理通信回数や同時実行数の証拠にはならない。この粒度の課題は本修正では未解決。
- 途中heartbeatは計数を更新しないため、強制終了/timeoutの0値も未呼出しを証明しない。今回確認した終端保存は成功とPublicRunErrorの経路。
- Task 2.2はreasoning OFF・逐次のsample3新規Translation→Word PDF→Comparison Reviewで検査する。旧結果は修正後の実E2E証拠に流用しない。用語集Changeの受入と共有し、ALIGN/表内画像/利用者目視などの未解決指摘を保持する。

## 新規実E2E開始

実装commit a222a9b後、2026-09-26 11:35 UTCに新規翻訳Run `01a0dd7f-a0a9-75f0-bc80-4693ee212389`を開始した。旧Runは再利用せず、既存prepare_run→run_public_run_detached→成功時export_runを使用する。tool sessionは86144。入力sample3.pdfのSHA-256は5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34fで前回と一致する。

設定はreasoning_mode=off、request timeout=1800秒、Task deadline/watchdog=21600秒。保存先は未使用だったoutputs/sample3-acceptance-off-counter、終端Evidenceは同directoryのtranslation-terminal.json。所有tempはoutputs/.sample3-counter-cjvct6cy。既存のRun rootと出力命名を使用しており、希望のoutputs新構成を実装済みとはしない。

11:35:42 UTC確認ではRunはrunning/DOCLING、直近完了通知はSPLIT 1/17。親uv PID7704→Python22180→30444、child launcher5692→Python35512が生存していた。途中counter=0は今回も確定値ではなく、終端保存で検証する。Word変換・比較Review・成果物検査は未実施であり、Task 2.2を完了にしない。

### STRUCTURE待機中の観測（11:42 UTC）

同じsession 86144を継続pollし、親30444/child35512の生存とheartbeat更新を確認した。Runはrunning/STRUCTURE、完了通知はLOAD 7/17で、STRUCTUREのページ成果物はまだない。processのCPUが低いことだけで停止とは判定しない。新規Run起動・既存Run再開・実行中Code変更は行っていない。

Langfuse読取りで今回の製品traceは9737d6c01fd035071ef4ac25d6e7a61e、LOADまでのTask終了を確認。別のprovider trace 889de226b6ed86e258dfc0754552fb18のobservation fb026fbc38103359は、11:35:57.335〜11:38:11.508 UTC（134.173秒）でERROR、InternalServerError/HTTP 500。error messageの分類にはconnectionを含む。raw本文/stack/endpointは記録しない。送信パラメータはreasoning_effort=none、max_completion_tokens=16384、temperature=0だった。

11:42 UTCの再取得でも終了済みprovider要求は上記1件で、製品llm.requestの終端観測はまだ取得できていない。provider側のERRORとクライアント側の終了を同一視せず、実際の再試行回数・停止原因・最終counterは未確定とする。接続関連のHTTP 500だけを根拠に製品Codeの不具合、context超過、reasoning ONと断定しない。request timeout 1800秒・watchdog 21600秒の既存上限を変更せず、同じprocessの結果を待つ。

### STRUCTURE待機の追跡（12:07〜12:09 UTC）

同じsession 86144のpollは継続中を返し、親30444/child35512の生存、terminal heartbeat更新、Runのrunning/STRUCTUREを再確認した。直近完了通知はLOAD 7/17のまま。再起動・追加Model要求・Code変更はしていない。

Langfuseの読取りでは、provider側の終了済み要求が4件へ増加していた。各件はInternalServerError/HTTP 500で、秘密を出さず分類したerror messageはいずれもconnectionを含む。reasoning_effort=none、max_completion_tokens=16384を4件とも確認した。

| Provider observation | 開始UTC | 終了UTC | 秒 |
| --- | --- | --- | --- |
| fb026fbc38103359 | 11:35:57.335 | 11:38:11.508 | 134.173 |
| fe3e533a4babe972 | 11:45:01.686 | 11:47:16.197 | 134.511 |
| 94f8ef3f1e01c32c | 11:54:07.003 | 11:56:20.964 | 133.961 |
| 9b3b5978f276477d | 12:03:11.094 | 12:05:25.732 | 134.638 |

製品trace 9737d6c01fd035071ef4ac25d6e7a61eのllm.request observation d7769acce95418a9も取得できた。11:35:56.892〜12:03:11.285 UTC、1634.393秒でLLMError、reasoning=none/thinking=disabledだった。したがって「製品側の最初のLLM処理がまだ終わっていない」という11:42時点の観測は更新されるが、STRUCTURE全体の終端は未観測である。

現行実装ではAdapterのSDK retryは0、外側の有限retryは設定3回。STRUCTUREは画像付き要求のLLMError後にテキスト要求へ逐次fallbackする。この制御と今回の時系列は整合するが、製品spanにはvision/text識別がなく、provider spanとの直接の親子関係もないため、4件を厳密な製品試行数やfallbackの確定証拠としては扱わない。provider要求の約134秒と開始間隔の約544〜545秒の差も、現在の観測だけでサーバー内部retry・通信待機などへ確定分類できない。

今回の確認は実際の接続関連500と有限処理の経過を示す。context超過やreasoning ON、計数修正による性能劣化と断定しない。終端counter・成果物・Word PDF・Comparison Reviewは引き続き未確認で、Task 2.2を完了にしない。

### 新規実E2Eの失敗終端（12:30 UTC）

同じsession 86144からexit 1を直接取得した。Run `01a0dd7f-a0a9-75f0-bc80-4693ee212389`はfailed/STRUCTURE、page 2、stage=text-invoke、cause=OpenAIAPIError、error=StructurePageErrorで停止した。開始11:35:25.946730〜終了12:30:26.709268 UTC、3300.762538秒。新しいDOCXは生成されず、Word PDF化・Comparison Reviewには進んでいない。Task 2.2は未完了のまま。

終端JSONのllm_calls=6、embedding_calls=0、qdrant_calls=0を確認した。製品traceの2番目のllm.request（3f35508c206baa9d）は12:03:11.286〜12:30:25.456 UTC、1634.170秒でERROR。前の製品要求と重ならず、providerの終了済みchat観測も6件で全件HTTP 500/接続関連・reasoning_effort=noneだった。最後の2件はab79edc471c3aea5（12:12:15.627〜12:14:30.500）と502f783ffb0d60dc（12:21:21.958〜12:23:35.267）。今回の公開失敗経路では、実際のLLM試行が0と保存される不整合は再発していない。これは翻訳品質や全E2Eの成功を意味しない。

対象PID 7704/22180/30444/5692/35512の不在と、所有temp outputs/.sample3-counter-cjvct6cyのcleanupを確認した。Runの入力コピー、.workspace/failure.json、77,824 bytesのcheckpoints.sqlite、workflow.json、およびSPLIT〜LOADのdirectoryは保持されている。入力hashは開始時と同一。既存Runを削除せず、Resumeの実行確認はまだ行っていない。

**診断値の限界:** 終端JSONのcheckpoint_count/artifact_countは0だが、失敗経路ではworkspace_countsを再計測せず以前の値を継承する実装である。したがって0をCheckpointや中間成果物の不在と解釈してはならない。ファイルの保持と実際のResume成功も区別する。この計測不足はcanonical module修正と別の未解決事項として保持し、本Changeで無断に修正範囲を広げない。

### 製品timeoutでの単発接続確認（2026-09-26 13:49 UTC）

短い診断timeoutと接続障害を区別するため、既存LLM Adapterの`_model(...).invoke()`で合成要求「Reply with OK only.」を1回送信した。製品設定のrequest timeout=1800秒を維持し、reasoning_mode=off、出力上限32 tokens、SDK retry=0、外側の製品retryなし。入力文書・画像・用語集・RAGは渡さず、Embeddingも呼ばない。新規Runや翻訳Workflowは開始していない。

- client開始: 13:49:24.691012 UTC。session 41953から **544.282秒後、exit 1** を直接取得した。例外はOpenAIAPIError、HTTP 500、内部原因InternalServerError。1800秒のtimeout到達ではない。
- 同じ時間帯のProvider observation `cdef950f696a9860`（trace `0e3ff2656316e31b0e4d7d8b58df5e41`）は13:49:24.914〜13:51:39.107 UTC、**134.193秒でERROR/HTTP 500**。秘密を出さず分類したerror messageはconnection/connectを含む。reasoning_effort=none、max_completion_tokens=32、temperature=0を確認した。
- Providerエラー記録からclient例外まで約410秒の差がある。時間帯の対応は確認できるが、直接の親子相関IDはなく、この差をProvider内部retry・Proxy・通信・client終了処理のいずれかへ確定分類する証拠はない。
- 終了後の同時間帯の観測は1件、未終了0件。ローカルPython/uv processも不在だった。応答本文、入力本文、接続先、認証値、raw stackは記録していない。

事前に、前の短時間probeに時間帯が対応するobservation `076334b3ce1b183d`が13:06:30.369〜13:08:46.818 UTCでERROR終端になったことを確認した。13:10〜13:49:06.480 UTCの観測は0件、ローカルPython/uvも不在だったため、その確認後に今回の単発要求を開始した。以前の「サーバー終端未確認」は当時の記録として保持し、この追跡結果で更新する。

出力32 tokens・推論OFF・長いtimeoutでも接続関連500が再現した。timeout延長だけでの回復は確認できず、製品不具合・context超過・推論ONとは断定しない。LM Studio側の22:49:24〜22:51:39 JST付近の到達/エラーログとの照合が必要。追加生成、全文翻訳、Word変換、Comparison Reviewは行わず、Task 2.2と実E2E受入は未完了のままとする。

記録更新の検査は文書Test 21 passed（0.29秒）、本Changeとexclude-cover-from-figure-numberingのOpenSpec strict validation成功、git diff --check成功。製品Code・設定・既存Runは変更せず、検証記録2件だけをcommit対象とする。
