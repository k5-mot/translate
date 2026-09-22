<!-- markdownlint-disable MD041 -->

## Context

動機は[proposal.md](proposal.md)のWhyを参照する。正本Requirementは`establish-translate-ja-contracts`の5 Capabilityにあり、本Changeはその振る舞いを変更しない。現在はRun入力がFile専用で、Qdrantの登録元がRun内絶対path、DOCX templateが同梱File固定、WorkflowのTask通知が成功後だけ、Langfuse warningがlogだけに閉じている。TestはUnit Harness中心で、公開process境界と最低対応RuntimeのEvidenceが不足している。

## Goals / Non-Goals

**Goals:**

- Directoryを含む入力を決定的なmanifestへ正規化し、Run間で安定した登録元Identityを保持する。
- 公開CLI/UI、Run metadata、Task Artifactおよび観測Adapterに一つの失敗・redaction境界を適用する。
- 前提条件を副作用前に検証し、公開processを通る受入TestでRequirementとの対応を証明する。
- 既存のRun root、Artifact path、明示Resume、明示削除およびQdrantをfingerprintから除外する規則を維持する。

**Non-Goals:**

- 5 CapabilityのRequirement変更または新Capability追加。
- Qdrant Collectionのsnapshot化、transaction機構または外部Registry DBの追加。
- 旧`.work/`の移行、保存済みRunの一括書換えまたは自動削除。
- 汎用event bus、DI container、Task基底classまたは独自DOCX rendererの導入。
- WindowsへPTY emulation Dependencyを追加すること。

## Decisions

### 1. DirectoryをFile単位のCanonical Input Manifestへ展開する

公開境界でFileとDirectoryを`InputSource`へ正規化し、Directoryは対応拡張子の通常Fileだけを再帰収集する。各entryは入力role、表示名、rootからの論理相対path、size、SHA-256および登録元keyを持ち、論理相対path順にsortする。Run Repositoryは各entryを`inputs/<role>/<logical-path>`へstreaming copyし、copy後hashを検証する。

symlink、junction、root外へ解決するchild、重複logical pathおよび未対応形式はcopy前に拒否する。空Directoryは「登録対象なし」の入力Errorにする。Directoryそのものを`shutil.copy2()`へ渡す案は、hash、containmentおよび部分copyの完了条件を表現できないため採用しない。

`RunInput`へoptionalな`logical_path`と`source_key`を追加し、metadata schemaをversion 2にする。version 1は一覧、Download、export、削除および翻訳／比較Resumeで読込み可能にするが、安定したsource keyを持たない旧登録RunのResumeは理由付きで拒否する。

### 2. Qdrantの登録元IdentityをRun pathから分離する

Qdrant point metadataの`source`には表示用logical path、`source_key`にはcontent非依存の安定ID、`source_hash`にはrevision hashを保存する。Point IDは`source_key + source_hash + chunk index`から生成し、旧revision削除は`source_key`一致かつ`source_hash`不一致を条件にする。これによりRun IDやRun rootが変わっても同じ登録元を置換できる。

source keyは、登録batchのnamespaceと論理相対pathをcanonical化したSHA-256とする。CLIはoptionalな`--source-id`をnamespaceとして受け取り、省略時は元入力rootの正規化済み絶対pathをhash入力にする。Streamlitは利用者が確認・編集できる登録元IDを必須表示し、初期値をupload名から作る。同じ表示名の別文書を誤置換しないよう、既存source keyを検出した場合は置換対象を表示して再確認する。Run metadataとQdrantには元絶対pathを保存せず、hashと表示名だけを残す。

Adapterだけの再登録Testではなく、異なるRunを作成する共通Lifecycle Testを受入境界にする。

### 3. 参照DOCXをRun入力として扱い、Pandoc前にPreflightする

`convert`へoptionalな`--reference-doc`を追加し、Streamlitへ参照DOCX uploadを追加する。省略時は同梱templateを明示的なdefaultとして使用し、実際に使用したtemplate内容hashをfingerprintへ含める。利用者指定templateは`reference_doc` roleでRunへcopyする。

PreflightはPandoc process開始前に次を一括検証する。

- Markdownが通常Fileで読取り可能である。
- 参照DOCXがZIPで、`[Content_Types].xml`と`word/document.xml`を持ち、CRC検査に成功する。
- Pandoc executableと必要option/extensionが存在する。
- 最終出力の親directoryを作成でき、同一directoryのtemporary Fileを作成・削除できる。

Preflight後も生成DOCXの同じ検証をreplace前に実行する。Pandocへ検証を委ねる案は、変換開始前Errorと既存成果物非変更を区別できないため採用しない。

### 4. Task状態通知と失敗Artifactを進捗通知から分離する

Workflowへ小さい`TaskStatusCallback`を追加し、node wrapperが`started`、`completed`、`failed`を通知する。進捗`current/total`は従来どおりcompleted/skippedだけで進め、started/failedでは増加させない。Lifecycleはstarted時に`last_task`を更新し、failed時にRunを`failed`へ変更する。

失敗詳細はrootの`run.json`を肥大化させず、`.workspace/failure.json`へatomic publishする。schemaはrun ID、Task、page/group/target ID、例外型、redact済み原因および発生日時だけを許可し、本文・binary・raw exceptionを禁止する。CLIとStreamlitはこのArtifactを共通formatterで表示する。成功したResumeではfailure Artifactを履歴directoryへ移さず削除し、Run logには過去失敗が残る。

`last_task`だけを成功eventから更新する現方式は失敗Taskを表せず、ProgressEventへ失敗情報を混在させる案は単調進捗契約を曖昧にするため採用しない。

### 5. RedactionとRun warningを一つの実行Scopeへ束縛する

Lifecycleは実行開始時にCredential値、Run warning sinkおよび現在のTask contextを`contextvars`でscope化する。Langfuseの初期化、start、update、finish、flush失敗は、秘密を除いた定型warningをlogとRun warning sinkの両方へ送る。warning sink自体の失敗はlogだけに残し、本処理を妨げない。

CLIの各実行Commandは共通handlerで例外を捕捉し、failure Artifactまたは`safe_error()`の結果だけをstderrへ出して非0終了する。raw exceptionを再送出してTracebackを公開しない。FIX/VERIFYの`fix_error`はpageと対象IDを付けたredact済み定型Errorだけを保存する。開発Testで必要なcause chainはprocess内に留め、永続化しない。

### 6. 受入Evidenceを公開境界と対応Platformで取得する

- POSIX CIで標準libraryの`pty`を使い、実際の`stdin/stdout.isatty()`がtrueのCLI subprocessに`y/n`とrun ID選択を入力する。Windowsでは非対話subprocess Testを実行し、PTY Testは理由付きskipにする。
- `streamlit run main.py`をheadless subprocessで起動し、health endpoint応答後に正常終了させる。Widgetの詳細は既存`AppTest`で継続検証する。
- Python 3.12をWindowsとUbuntuの必須CI matrixにし、上位Versionは追加Jobに留める。
- 無効・空・暗号化・破損PDF、Directory登録、cross-Run revision、Qdrant一時障害、CLI stderr redaction、FIX/VERIFY Artifact redactionを障害注入する。
- 実Pandocを用いたfixtureで見出し、List、Code、Table、画像、Caption、FootnoteおよびLinkをDOCXから再抽出して検証する。atomic failureは既存Test doubleで継続する。

Test名だけで完了を推測せず、Requirement／Scenario／Test IDの対応表をverification Evidenceへ残す。

### 7. Run layout記述をroot `run.json`へ統一する

実装とTaskで採用済みの`runs/<run-id>/run.json`を正とし、旧Design図の`.workspace/run.json`表記を修正する。Workflow固有fingerprint Fileが必要な場合は`.workspace/workflow.json`と命名し、Lifecycle metadataとの同名衝突を避ける。

## Quality Attribute Design

| 品質ID | Design Approach | Trade-off | 検証Evidence |
| --- | --- | --- | --- |
| Q-FUNC | canonical input manifest、stable source key、参照DOCX input | 登録元IDの確認操作が増える | 公開CLI/UI Capability Test、全Scenario対応表 |
| Q-PERF | streaming hash/copy、path-only checkpoint | Directory走査I/Oが増える | memory上限Test、checkpoint内容検査 |
| Q-COMP | 共通InputSource、failure schema、fingerprint | version 1登録RunはResume不可 | v1読込みTest、CLI↔UI Resume Test |
| Q-USE | 失敗Taskと対象を共通formatterで表示 | 診断情報はredactionで限定される | CLI subprocess、Streamlit AppTest |
| Q-REL | preflight、atomic failure Artifact、cross-Run revision置換 | Qdrant delete確認が追加される | 障害注入、旧成果物保持、重複Chunk 0件 |
| Q-SEC | context-scoped redaction、path containment、raw traceback禁止 | Support用のraw Errorを永続化しない | sentinel Credential/body/binary Test |
| Q-MAIN | 進捗とTask statusの責務分離、Traceability表 | callbackが一つ増える | Ruff、Format、ty、pytest、OpenSpec strict validation |
| Q-PORT | Python 3.12 Windows/Ubuntu、POSIX PTY | WindowsでPTY Testを直接実行しない | CI matrixとskip理由検査 |

## Lifecycle, Migration and Operations

- **Transition**: version 2 readerを先に導入し、次に入力manifest、Qdrant、DOCX、Task status、UI/CLIの順に切り替える。version 1 Runは削除せず、対応可能な操作を維持する。
- **Rollback**: 新しいQdrant point metadataは旧codeから未知fieldとして無視できる。Rollback時も新RunとQdrant pointを自動削除せず、登録更新を停止してexport済み成果物を利用する。
- **Operation**: Run一覧と失敗表示からTask、対象、redact済み原因、warningおよびlog pathを確認できる。source key置換前には表示名とnamespaceを確認する。
- **Support**: raw Credential、本文または画像を収集せず、run ID、Task、対象ID、Error型、定型原因と外部Service healthを切り分ける。
- **Maintenance**: Traceability表とCI matrixをRequirement変更時に更新し、実施していないHarness名をTaskへ記載しない。
- **Disposal**: 既存の明示削除、lock、root containmentおよび外部export保持を変更しない。Qdrant登録内容の削除操作は本Changeの対象外とする。

## Risks / Trade-offs

- [Streamlit uploadは元の絶対pathを持たず、同名文書を自動識別できない] → 編集可能な登録元IDと置換前確認を必須にする。
- [source key規則変更で既存Qdrant pointと新pointが一時的に共存する] → 旧形式を自動削除せず、移行対象Collectionでは運用者が再登録後に件数を確認する。
- [failure Artifactからraw例外を除くため診断情報が減る] → Error型、Task、対象、定型原因、run IDおよび秘密を除いたlogでSupport可能にする。
- [実Pandocとsubprocess TestはCI時間を増やす] → 構造受入Testを小さいfixture一件へ集約し、Unit failure injectionはTest doubleを使う。
- [version 1登録RunをResumeできない] → 一覧、export、削除は維持し、新規version 2 Runによる再登録手順をErrorと運用文書へ示す。

## Migration Plan

1. version 1/2を読めるRun model、InputSource、failure schemaおよびredaction scopeを追加し、既存Run Testを維持する。
2. Directory収集とstable source keyをQdrant登録へ接続し、異なるRun間の置換をTestする。
3. 参照DOCX public inputとPandoc preflightを追加し、fingerprintとResume互換性をTestする。
4. Workflow nodeへTask status callbackを接続し、CLI/UIの安全な失敗表示とLangfuse Run warningを追加する。
5. 公開subprocess、Security、CapabilityおよびCI matrix Testを追加し、Requirement対応表を完成させる。
6. Run layout、移行、Supportおよび検証Evidenceを更新し、全GateとOpenSpec verifyを実行する。
7. Rollback時は登録更新と新規実行を停止し、Codeを戻してもversion 2 RunとQdrant pointを保持する。
