<!-- markdownlint-disable MD041 -->

## 1. UUIDv7 Run Identity

- [ ] 1.1 Python 3.12標準libraryだけでRFC 9562 UUIDv7を生成する共通helperを実装し、固定clock／randomによるbit layout、version、variant、canonical文字列、時刻範囲および衝突0件をUnit Testで確認する（Q-FUNC、Q-PORT）
- [ ] 1.2 Run RepositoryのID生成とvalidatorをcanonical UUIDv7限定へ切り替え、不正version・大文字・path traversalがFilesystem access前に拒否されるTestを通す（Q-SEC、Q-COMP）
- [ ] 1.3 UUIDv4 metadataを一覧から警告付きで除外し、CLI／StreamlitのResume、exportおよび削除が同じ安全なErrorで拒否する相互運用Testを通す（Q-COMP、ISO/IEC/IEEE 12207移行・運用Evidence）

## 2. 安全な登録失敗診断

- [ ] 2.1 登録Errorを`collect`／`hash`／`split`／`extract`／`write`／`verify`／`replace`のallowlist stageと下位例外型だけを持つ構造へ変更し、raw message、path、responseおよびDocling job IDが転記されないUnit Testを通す（Q-USE、Q-SEC）
- [ ] 2.2 `FailureRecord`へ後方互換なoptional stage／cause typeを追加し、`failure.json`、Run log、CLIおよびStreamlitが`REGISTER`と同じ診断値を表示し、旧形式failure JSONも読めるTestを通す（Q-COMP、Q-USE）
- [ ] 2.3 抽出、書込み、確認およびrevision置換の障害を公開Lifecycleへ注入し、各stageの識別、非0終了、Resume可能なfailed Run、成功件数0件ならびにCredential・本文・raw応答・job ID sentinel漏えい0件を確認する（Q-REL、Q-SEC、Support Evidence）

## 3. 大規模PDF登録Pipeline

- [ ] 3.1 source hashを共通streaming SHA-256へ切り替え、`registration-v2`、抽出影響設定およびChunk設定からregistration revisionとPoint IDを決定的に生成するTestを追加する（Q-PERF、Q-MAIN）
- [ ] 3.2 legacy Point、設定違いPointおよび失敗済みrevisionを含むQdrant fixtureで、全新Point確認後だけ現在revision以外を削除し、同一再登録の重複Chunkと旧revisionを0件にするIntegration Testを通す（Q-FUNC、Q-REL、移行Evidence）
- [ ] 3.3 登録LifecycleからRun workspaceを渡し、PDFをsource key／hash別のatomic directoryへ`PDF_SPLIT_PAGES`以下で分割して、complete manifest一致時だけResumeで再利用するUnit／Integration Testを通す（Q-REL、Q-PERF）
- [ ] 3.4 PDF partをpage順に抽出してglobal chunk indexを付け、最大64件ずつEmbedding／upsert／retrieve確認するbounded pipelineへ変更し、原PDF全量読込み0件、Docling上限超過0件、Qdrant batch超過0件をspy Testで確認する（Q-PERF）
- [ ] 3.5 登録全体で一つの絶対deadlineを共有し、Docling partとQdrant batchが残時間を超えず、期限切れ時に現在stageの`TimeoutError`で停止するclock制御Testを通す（Q-REL）
- [ ] 3.6 中間batch後の失敗と明示ResumeをTestし、旧revision保持、決定的upsert、未確認登録の成功報告0件、Resume後の完全Chunk確認および旧revision cleanupを確認する（Q-REL）

## 4. 公開契約、運用文書および品質Gate

- [ ] 4.1 UUIDv7限定への破壊的切替、UUIDv4成果物の事前export／明示削除、登録stageの意味、同一run IDでのResume、workspace容量、部分Pointの収束およびRollbackを運用文書へ反映し、新規Dependency・公開option・Word→PDF機能が追加されていないことをReviewする（Q-USE、ISO/IEC/IEEE 12207移行・運用・保守・Support・廃止Evidence）
- [ ] 4.2 UUIDv7限定、UUIDv4拒否、stage診断、大規模PDFの有界処理およびrevision移行をCapability／Scenario／Test IDへ対応付け、未対応Scenario 0件のverification Evidenceを作成する（Q-FUNC、Q-MAIN）
- [ ] 4.3 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest`をWindowsで実行し、CIのWindows／POSIX matrixを含む既存Testと新規Testをerror 0件で完了する（Q-MAIN、Q-PORT）
- [ ] 4.4 検証専用Collectionで公開CLIから`inputs/sample.pdf`を登録し、設定済みTask deadline内の完了、各Docling入力10 page以下、登録Chunk 1件以上、重複Chunk・旧revision・誤成功・秘密漏えい0件およびUUIDv7 run IDを`verification.md`へ記録する（Q-FUNC、Q-PERF、Q-REL、Q-SEC）
- [ ] 4.5 `verify-sample-pdf-end-to-end`へTask 4.4のEvidenceを引き継いでRegister gateを再開し、本Changeと影響する既存ChangeをOpenSpec strict validation／verifyしてerror・CRITICAL・未判定Requirementを0件にする（Q-MAIN、保守Evidence）
