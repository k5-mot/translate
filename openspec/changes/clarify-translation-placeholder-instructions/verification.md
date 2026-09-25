<!-- markdownlint-disable MD013 MD041 -->

## 2026-09-25: 提案段階

状態は計画完了・実装未着手。`TRANSLATE-PROTECTED-OFF-001`は未解決で、tasksは0/9。既存の失敗記録は[OFF検証記録](../configure-verification-reasoning-policy/verification.md)を参照する。

- proposal/design/tasksを作成。既存要求の実装指示修正のため`skip_specs: true`でDeltaを作らない。
- OpenSpec statusはproposal/design/tasksがdone、specsがskipped。これは計画Artifactの充足で、実装・受入完了ではない。
- `openspec validate clarify-translation-placeholder-instructions --strict`: valid。
- `openspec validate configure-verification-reasoning-policy --strict`: valid。
- `uv run pytest tests/test_documentation.py -q`: 21 passed、0.30秒。
- `git diff --check`: 指摘なし。
- 既存configの未知operation `verify`警告は継続しており、今回の修正範囲外として変更しない。
- 製品Code・翻訳Rule・既存成果物は変更していない。モデル要求、Word操作、全製品suiteは今回未実行で、apply/verifyの未完了Taskに残す。
- 既存未コミット差分を保持し、新Changeの文書と元失敗記録への引継ぎリンクのみをcommit対象とする。`.agents`、サンプル、outputs/runs、秘密は含めない。

## 次の検証条件

配布ルール修正と自動Testの後、新しいルールhashでsample3のOFF翻訳を新規実行する。成功した同じDOCXをWordでPDF化し、原本とReviewする。本文内の保護値保持、利用者目視、既知ALIGN/表内画像問題を別々に判定し、未達条件がある間はarchive・main merge・pushを完了扱いにしない。

## 2026-09-25: 実装・自動検査

- 配布ルールへ4項目を追加した。製品Python・Dependency・retry/復元条件は変更していない。
- Test先行で配布指示10条件＋送信経路6条件が旧ルールに対して16 failed。ルール修正後は翻訳出力Test 42 passed、fingerprint/Workflowを含む関連60 passed。さらに別IDへ記号を移した応答の拒否Testを追加した。
- 配布ルールを実loaderで読み、通常/OFF、初回・欠落retry・逐次分割のsystem指示到達、IDごとの保護値復元、送信順と推論指定を検査した。Mock応答による検査は実LLMの成功証明ではない。
- 通常/OFFそれぞれのルール変更で公開Resumeが非互換となり、旧metadata不変、Workflowのルールhash/thread IDが異なることを、実GraphをSPLITで停止する外部通信なしのTestで確認した。
- 全体初回: **652 passed / 4 failed / 1 skipped、40.09秒**。テスト親にだけ`PYTHONUTF8=1`を与えた一方、既存CLI隔離Testは子環境へその値を渡さず、cp932のstderrを親がUTF-8で読みUnicodeDecodeErrorになった。4件とも出力読取り側の同じ失敗だった。
- 追加した環境指定を外し、既存CLI Testを変更せず再確認: **5 passed / 1 skipped、14.63秒**。同じ通常環境の全体再実行: **656 passed / 1 skipped、40.26秒**。初回失敗は上記に保持する。任意の親子文字コード混在への対応を今回実装したとは扱わない。
- `ruff check .`、`ruff format --check .`（340 files）、`ty check`、OpenSpec strict、`git diff --check`: 成功。
- 全体検査は既存未コミットのLLM/REVIEW/Lifecycle/terminal Evidenceの差分も含むworktreeを対象とする。それらを本Changeへ混ぜず保持する。今回のcommit対象はルール、既存Test 2 files、tasks/verificationのみ。
- tasks 1.1〜1.4を完了。2.1以降の実検証、利用者目視、正式verify、archive、merge/pushは未完了である。

新ルールSHA-256: `501f2e459290ea37b0f5bb70c09d166dc4ef1e3c422c5e410f46c70d44d45f81`。入力sample3 SHA-256: `5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`。09:51 JSTの確認時点で`outputs/sample3-acceptance-off-markers`は存在しない。旧失敗Runは保持している。

## 新規実翻訳（09:54 JST開始）

- 起動HEAD `fcc7947`、session `79743`。旧translate/review processがないこととexport先未存在を確認して開始した。
- 新規Run `01a0d60e-228b-7350-b800-e908a4177727`、作成09:54:05.717 JST。旧OFF RunのResumeではない。
- プロセス限定`LLM_REASONING_MODE=off`、`PYTHONUTF8=1`。公開CLIは`translate inputs/sample3.pdf --output-dir outputs/sample3-acceptance-off-markers`、非対話・resumeなし。`.env`は変更しない。
- fingerprint `a71c664e195c523d93697ff5fdb684c2e8751d1c74a540b7d60a805099ad19e6`、context/output/image=30208/16384/2048、translation rule hashは上記新ルールと一致。
- 09:54 JSTにworker PID52832、親50708、uv51072を確認し、同じsession handleで進行を観測した。SPLIT 0.051秒、DOCLING 26.752秒、LOADまで7/17通知。その後STRUCTUREへ進んだ。
- 09:55 JSTの読取り専用Langfuse照会で、終了済み2要求のproduct metadataはnone/disabled。対応Provider chatのusageはinput/output/totalのみで推論token明示値はないため、実測0とは報告しない。追加モデル要求は発行していない。
- 起動時の既存未コミット製品4 filesのSHA-256は、[先行OFF検証の起動worktree](../configure-verification-reasoning-policy/verification.md)に記録したllm/lifecycle/terminal_evidence/reviewとすべて同一。今回もcommit単独の実検証とは扱わない。
- 開始時点ではDOCX/PDF/Review未完了。Task 2.1は起動だけでは完了にしない。

## 実検証の終端（09:58 JST）

**失敗。** session `79743`は09:58:39 JSTにexit 1で終了した。STRUCTUREは125.237秒で完了、TRANSLATEは120.398秒、TOTALは273.425秒。Run metadataはfailed/TRANSLATE、failureはpage=2、target=`page-0002-chunk-0001`、stage=text-parse、cause=ProtectedFragmentMissing。公開outputsは空、export先DOCXは存在せず、Word/PDF化とReviewは未実施。対象CLI processの終端も確認した。

Checkpoint SQLite（86016 bytes）、入力copy、STRUCTUREまでのArtifactを保持している。旧Runの削除・上書き、追加モデル要求、推論ONへの切替、失敗訳の採用は行っていない。

### 保存済み応答による再現

`diagnosing-bugs`に従い、既存Langfuse応答を実`PydanticOutputParser(TranslationResponse)`と`_restore_chunk_placeholders`へ渡す読取り専用probeをPowerShell here-stringから`uv run python -X utf8 -`で実行した。新しい実入力の保存やモデル要求は行わず、出力は記号ID・件数・判定だけとした。

- 観測ID: `b522dd8f5de231d4`、`2be89f39fa04d66a`、`edc100ac9583bf6c`。3応答を各2回再生し、**6/6でProtectedFragmentMissing**、約2.5秒、probe exit 1。
- いずれも14訳文、期待14 IDと一致。1要素＋1保護対応へ縮小しても`__PROTECTED_5_0__`はRED、`__PROTECTED_6_0__`と`__PROTECTED_10_0__`はGREENだった。
- 仮説を「指示到達後のモデル省略」「新指示の未到達」「表記揺らぎによる復元失敗」の順に比較した。全3要求のsystemに配布新ルール全文が含まれ、targetと記号一覧は保存済みSTRUCTUREから再構成した値と完全一致した。
- 全3応答で`__PROTECTED_5_0__`はexact/NFKC/casefoldいずれも0、元保護値もNFKC前後とも0。残る2記号は各1回、検出可能な記号も合計2個。従って新指示未到達や許容表記の揺らぎではなく、応答内の1断片不出力が直接原因である。
- 前回は2記号欠落、今回は1記号欠落だった。ただしモデル出力の変動と切り分けた効果量ではなく、指示追加だけで解決したとは判定しない。
- 3要求の実効metadataはnone/disabled。Provider input/output/totalは4684/1254/5938、4684/1253/5937、4684/1253/5937。推論token明示値はなし。出力上限到達による切断を示す失敗ではない。

## Verification Report: clarify-translation-placeholder-instructions

| Dimension | 判定 |
| --- | --- |
| Completeness | 4/9。2.1〜2.3、3.1〜3.2未完了 |
| Correctness | 指示到達・有限retry・非互換性の自動Testは成功。実LLMは保護断片1件を欠落し公開契約未達 |
| Coherence | 既存Rule/loaderを使用。Module/Dependency/再開台帳の追加、検査緩和、暗黙ON切替なし |

### CRITICAL

1. **2.1 / TRANSLATE-PROTECTED-OFF-001未解決**: 指示の補足のみでは実翻訳が成功しない。今回の保存応答を根拠に、検証失敗後の同一要求再送に代わる是正を別途計画し、欠落を捏造せず新規実翻訳で確認する。現在のChange内でretry/分割方針を無断変更しない。
2. **2.2未実施**: 新規DOCXがない。翻訳成功後にそのDOCXの内容・Word PDF・利用者目視を検証する。
3. **2.3未実施**: 新規PDFがない。原本とのOFF Reviewと実物照合を行い、既知ALIGN問題も別判定する。
4. **3.1未完了**: 今回のverifyは不合格。必要な実成果物証拠を揃えて再verifyし、元指摘を解決済みにするのはその後とする。
5. **3.2未完了**: 実装commitから`.agents`/サンプル/生成物は除外済みだが、受入未達のためarchive/main merge/pushは行わない。

### WARNING

親子で異なる文字コード設定を持つCLI隔離Testが初回に失敗した。通常環境では再現せず全体656 passedだが、任意の親環境での安定性は未保証。必要な是正は今回の翻訳指示修正と分離して扱う。

**最終判定: 実検証失敗、archive不可。** Deltaはskip_specsのためなし。既存正式仕様の保護対象保持要求と、design/tasksの実検証条件へ照合した。Word/PDF/Reviewを省略して合格にすることはない。

## 次の是正案に向けた既存API調査（2026-09-25）

現在のretryは同じ要求を繰り返しており、検証で分かった情報を次回へ渡していない。新たなretry機構を再開発しないため、grill-with-docsの事実調査として導入済みAPIを読取り専用で比較した。モデル/Embedding要求、製品Code変更、新Change作成は行っていない。

導入済みVersion: langchain 1.4.2、langchain-core 1.6.3、langchain-openai 1.6.2、langgraph 1.2.11、pydantic 2.13.5、tenacity 9.1.4。調査はこの導入済みAPIと現行呼出し境界の比較であり、全Packageに同等機能が存在しないとの主張ではない。

| API / 現行境界 | 確認結果 |
| --- | --- |
| PydanticOutputParser（langchain_core/output_parsers/pydantic.py:25） | model_validateによるshape検査。Task固有の期待ID/marker mapを渡しておらず、形状適合・記号欠落の合成応答はparser成功後のTask検証で失敗する |
| RunnableRetry（langchain_core/runnables/retry.py:179） | 同じinputを再invokeする。回数/待機制御はあるが検証feedback生成はない |
| LangGraph RetryPolicy（langgraph/types.py:418） | node/task入力の再実行。既存Task内retryへ追加すると範囲・回数が変わり、今回の局所的な要求補足にはならない |
| OutputParserException(send_to_llm=True) | 情報を保持する例外。現在のAdapterにfeedback consumerはなく、フラグだけでは要求を変更しない。llm_output必須なので生応答を避ける本案には不要 |
| ToolStrategy(handle_errors=...)（langchain/agents/structured_output.py:196） | create_agent/tool-calling内ではToolMessageによるfeedbackがある。現在のprompt parserへそのまま適用できず、Agent loopと動的Task検証の接続が必要 |
| 現行structured / TRANSLATE | adapters/llm.py:345でshape検査、tasks/translate.py:77/251で保護・ID検査、同396行で検証失敗を捕捉。既存のTask loop内で次回要求だけを変える余地がある |

上記Package参照は`.venv/Lib/site-packages/`配下のローカルSourceを指す。旧RetryOutputParser/OutputFixingParserを持つlangchain_classicは未導入で、これだけのために依存を増やさない。

### 利用者へ提示した方針（回答待ち）

推奨は、既存の有限retry上限内で、検証失敗の固定分類と各IDに必要な保護記号を次回要求へ追加し、同じChunk全体を再生成すること。初回・通信retry・分割上限・逐次実行・OFFを維持する。既存検証関数を正本とし、feedback生成用に別の合否判定を再実装しない。生応答・原文保護値・例外全文は転記せず、feedbackは蓄積せず置換し、永続Cacheや完了台帳を作らない。

代替は欠落した翻訳単位だけ再生成する案だが、部分応答の保持・統合と文脈の扱いを追加設計する必要がある。利用者へ全Chunk再生成案を提示しており、回答前に採用済みとしない。新Changeは方針確認後に作成する。今回の元指摘・未完了Taskは変わらない。
