<!-- markdownlint-disable MD041 -->

## 1. Run入力Schemaと互換読込み

- [x] 1.1 `RunInput`のlogical path／source keyとschema version 2を実装し、version 1 Runが一覧・Download・export・削除および翻訳／比較Resumeで引き続き読めることをmigration Testで確認する（Q-COMP、移行Evidence）
- [x] 1.2 File／Directoryを対応形式のcanonical `InputSource` manifestへ展開し、順序、相対path、SHA-256、空Directory、未対応形式、重複名をUnit Testで確認する（Q-FUNC）
- [x] 1.3 symlink、junction、root外childおよびpath traversalを収集・copy前に拒否し、失敗時に部分Runが残らないことをWindows/POSIX fixtureで確認する（Q-SEC、Q-PORT）
- [x] 1.4 入力copyとhashを固定size chunkでstream処理し、Directory入力でも本文・binaryが`run.json`とcheckpointへ入らず、全File読込みAPIを使用しないことをTestする（Q-PERF）
- [x] 1.5 flattened input hash、logical path、source keyおよび実使用template hashをcanonical fingerprintへ接続し、Credential・retry・Langfuse・Qdrant状態を引き続き除外する差分Testを通す（Q-COMP、Q-REL）

## 2. 参照Directory登録とQdrant Revision

- [x] 2.1 CLI `register`へoptionalな`--source-id`、Streamlitへ確認可能な登録元IDと置換確認を追加し、両者が共通Lifecycleの同じsource keyを使用するUI／CLI Testを通す（Q-USE、Q-COMP）
- [x] 2.2 Qdrant metadataとPoint IDをRun内pathではなくsource key、logical path、source hash、chunk indexから構成し、旧revision削除条件をsource key単位へ変更するUnit Testを通す（Q-REL）
- [x] 2.3 公開CLIから対応形式を含むDirectoryを二つの異なるRunとして登録し、再登録後の旧Chunk・重複Chunk・誤成功が0件になるIntegration Testを通す（Q-FUNC、Q-REL）
- [x] 2.4 Qdrant書込み・確認・旧revision削除の一時障害と恒久障害を注入し、有限retryでの回復または登録全体の失敗を確認する（Q-REL）
- [x] 2.5 source keyを持たないversion 1登録Runだけを理由付きでResume拒否し、一覧・export・明示削除は維持するTestと運用移行手順を作成する（ISO/IEC/IEEE 12207移行・運用・廃止Evidence）

## 3. 参照DOCX入力とPandoc Preflight

- [x] 3.1 CLI `convert`へ`--reference-doc`、Streamlitへ参照DOCX uploadを追加し、省略時defaultを含む実使用templateをRun入力・fingerprint・Resume互換性へ反映する相互運用Testを通す（Q-FUNC、Q-COMP）
- [x] 3.2 Markdownの読取り、参照DOCXのZIP／必須entry／CRC、Pandoc機能および出力directoryの書込み可能性をprocess開始前に検証し、各前提条件ErrorでPandoc未実行・既存出力未変更になるTestを通す（Q-REL）
- [x] 3.3 実Pandoc fixtureで見出し、List、Code、Table、画像、Caption、FootnoteおよびLinkをDOCXから再抽出し、全要素が保持されることを確認する（Q-FUNC、供給Evidence）
- [x] 3.4 Pandoc途中失敗、不正DOCX、replace失敗を注入し、旧完全版または未作成状態だけが観測され、temporary FileがcleanupされるTestを通す（Q-REL）

## 4. Task失敗記録と秘密情報保護

- [x] 4.1 `TaskStatusCallback`とatomicな`.workspace/failure.json` schemaを実装し、startedで`last_task`を更新し、failedでTask、page/group/対象ID、Error型、redact済み原因だけを保存するUnit Testを通す（Q-USE、Q-SEC）
- [x] 4.2 翻訳・比較Workflowの実node wrapperへstarted/completed/failed通知を接続し、node内部例外で失敗Taskを正しく記録して成功済みTaskを再実行せずResumeするIntegration Testを通す（Q-REL）
- [x] 4.3 CLIとStreamlitの共通Error formatterを実装し、外部Service例外時にrun ID、Task、対象および安全な原因だけを表示してraw tracebackを公開しないsubprocess／AppTestを通す（Q-USE、Q-SEC）
- [x] 4.4 FIX/VERIFYのfallback Errorをpage／対象ID付きのredact済み値へ変更し、Credential、本文全文、endpoint credentialおよび画像binary sentinelがTask Artifactと最終warningへ残らないSecurity Testを通す（Q-SEC）
- [x] 4.5 成功Resumeでactive failure Artifactを除去し、過去のredact済み障害をRun logから追跡できることをTestしてSupport手順へ反映する（ISO/IEC/IEEE 12207運用・Support Evidence）

## 5. Langfuse Run Warning

- [x] 5.1 Credential、Run warning sinkおよびTask contextを実行単位の`contextvars`へ束縛し、Langfuse初期化・start・update・finish・flush障害をlogとRun warningへ一度だけ記録して本処理を継続するTestを通す（Q-REL、Q-SEC）
- [x] 5.2 warning sink自身の失敗を本処理から分離し、秘密を含むSDK例外でも`run.json`、log、CLI/UIおよびtraceへ秘密値が出ない障害注入Testを通す（Q-SEC）

## 6. 公開ProcessとCapability Scenario Evidence

- [x] 6.1 空、暗号化済み、破損および読取り不能PDFを翻訳・比較の公開Lifecycleへ入力し、対象roleを示すError、公開成果物0件およびResume可能なfailed Runを確認する（Q-FUNC、Q-REL）
- [x] 6.2 POSIXの実PTYで対話CLIを起動し、同一入力候補の複数選択、`y` Resume、`n`新規Runを検証し、Windowsでは非対話subprocessとPTY skip理由を検証する（Q-USE、Q-PORT）
- [x] 6.3 `streamlit run main.py`をheadless subprocessで起動してhealth応答と安全な終了を確認し、既存`AppTest`でrerun、Resume確認、Download、exportおよび削除確認を継続検証する（Q-USE）
- [x] 6.4 Python 3.12のWindows／Ubuntu必須CI matrixを追加し、Pandocを明示導入してRuff、Format、ty、pytestおよび公開process Testを両Platformで成功させる（Q-PORT、供給・保守Evidence）
- [x] 6.5 5 Capabilityの30 Requirement／48 ScenarioをTest IDへ対応付け、未実行Scenario、実装だけの主張およびHarness名の不一致を0件にしたTraceability表を検証Evidenceへ追加する（Q-FUNC、Q-MAIN）

## 7. 文書、移行および最終Gate

- [x] 7.1 `run.json`をRun root、Workflow固有metadataを`.workspace/workflow.json`とするlayoutへDesign・README・運用文書を統一し、相対linkと旧`.work/`非互換記述を文書Testで確認する（Q-MAIN、移行・運用Evidence）
- [x] 7.2 version 1登録Run、Qdrant source key移行、Rollback、容量監視、失敗診断、明示削除および外部export保持を運用checklistへ反映し、ISO/IEC/IEEE 12207の移行・運用・保守・Support・廃止観点をReviewする
- [x] 7.3 `uv sync --dev`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`、`uv run pytest`、両ChangeのOpenSpec strict validationを実行し、全commandのerror 0件と実行環境をverification Evidenceへ記録する（Q-MAIN）
- [x] 7.4 `establish-translate-ja-contracts`と本ChangeをOpenSpec verifyで再検証し、CRITICAL 0件、Requirement／Scenario未対応0件およびArchive可の判定を記録する
