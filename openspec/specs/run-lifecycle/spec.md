<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

# run-lifecycle Specification

## Purpose

CLIとStreamlitで共通のRunを作成、保存、再開、exportおよび削除できるよう、Run識別子とLifecycleの公開契約を定義する。誤ったRunの再利用を防ぎながら、失敗後の復旧と成果物の一貫した管理を可能にする。

## Requirements

### Requirement: RunをUUIDv7だけで識別する
Systemは、新しく作成するすべてのRunへcanonicalなRFC 9562 UUIDv7を割り当て、UUIDv7だけを有効なrun IDとして扱わなければならない（MUST）。IDは生成時刻とRFC variantを正しく符号化し、CLIとStreamlitで同じ形式と検証規則を使用しなければならない（MUST）。Q-FUNCおよびQ-PORT（ISO/IEC 25010）として、生成したIDのversion、variant、canonical表現および時刻を自動Testし、不正IDと衝突を0件にしなければならない（MUST）。

#### Scenario: CLIから新規Runを作成する
- **WHEN** 利用者がResume IDを指定せずCLIからRunを開始する
- **THEN** Systemは実行開始時刻を含むcanonical UUIDv7をrun IDとして使用する

#### Scenario: Streamlitから新規Runを作成する
- **WHEN** 利用者が既存Runを選択せずStreamlitからRunを開始する
- **THEN** SystemはCLIと同じUUIDv7形式で新しいRunを作成する

#### Scenario: UUIDv7ではないRun IDを指定する
- **WHEN** 利用者がUUIDv4を含むcanonical UUIDv7ではない値をRun操作へ指定する
- **THEN** SystemはRun root内のpathへアクセスする前に指定を拒否する

#### Scenario: UUIDv4 metadataがRun rootに残っている
- **WHEN** 共通Run rootの走査中にUUIDv4 run IDを持つmetadataを検出する
- **THEN** Systemはそのdirectoryを有効なRun一覧から除外し、秘密を含まないinvalid metadata警告を返す

### Requirement: 共通Runを永続化する
Systemは、`TRANSLATE_RUNS_DIR`で指定された共通rootを使用し、未設定時はProject直下の`runs/`を使用しなければならない（SHALL）。各Runは一意なrun IDを持ち、`inputs/`、`outputs/`および内部状態を格納する`.workspace/`を保持しなければならない（MUST）。CLIとStreamlitは同じRun layoutを使用しなければならない（MUST）。

#### Scenario: CLIで作成したRunをStreamlitから列挙する
- **WHEN** CLIとStreamlitが同じ`TRANSLATE_RUNS_DIR`を参照する
- **THEN** StreamlitはCLIで作成されたRunと状態を一覧へ表示できる

#### Scenario: Run rootが未設定である
- **WHEN** `TRANSLATE_RUNS_DIR`が設定されていない
- **THEN** SystemはProject直下の`runs/`へ新しいRunを作成する

### Requirement: 新規Runと既存Runを安全に選択する
Systemは、run IDの明示指定がない場合、原則として新規Runを作成しなければならない（SHALL）。入力SHA-256が一致する既存Runがある対話CLIでは、run IDと互換性を提示して`y/n`を確認し、`y`の場合だけ互換RunをResumeしなければならない（MUST）。非対話CLIは既存Runを暗黙にResumeしてはならない（MUST NOT）。

#### Scenario: 対話CLIで同一入力を検出する
- **WHEN** 対話CLIにrun IDを指定せず、入力SHA-256が一致する既存Runが存在する
- **THEN** Systemは候補run IDと互換性を表示し、`y`でResume、`n`で新規Runを作成する

#### Scenario: 非対話CLIで同一入力を検出する
- **WHEN** 非対話CLIにrun IDを指定せず、同一入力の既存Runが存在する
- **THEN** Systemは質問で停止せず新規Runを作成する

#### Scenario: Streamlitで既存Runを選択する
- **WHEN** 利用者がStreamlitのRun一覧から互換Runを選択する
- **THEN** Systemは選択内容を確認後、そのrun IDをResumeする

### Requirement: Resume互換性をFingerprintで判定する
Systemは、入力内容、Backend、出力へ影響するModel、Rule、用語集、Template、分割、Docling、OCR、ContextおよびToken設定をcanonical fingerprintへ含めなければならない（MUST）。CredentialおよびQdrantの状態はfingerprintへ含めてはならない（MUST NOT）。fingerprintが異なるRunのResumeは、相違項目を表示して拒否しなければならない（MUST）。

#### Scenario: 互換RunをResumeする
- **WHEN** 利用者が入力と出力影響設定のfingerprintが一致するrun IDを指定する
- **THEN** Systemは完了済みTaskを再利用して未完了Taskから再開する

#### Scenario: 設定が異なるRunを指定する
- **WHEN** 利用者がModel、Rule、用語集、Template、Docling、OCRまたはContext設定の異なるrun IDを指定する
- **THEN** Systemは相違項目を表示してResumeを拒否する

#### Scenario: Qdrantだけが変更される
- **WHEN** 入力とfingerprint対象設定は同じでQdrant内容だけが変更される
- **THEN** SystemはResumeを拒否せず、完了済みTaskを再利用し、未完了Taskの検索結果を新しいArtifactへ保存する

### Requirement: Task単位のCheckpointを保持する
Systemは、各Taskの成功、失敗および現在位置を独立して保持し、checkpointにはArtifact path、状態、警告および小さい進捗metadataだけを保存しなければならない（MUST）。文書本体と画像binaryをcheckpointへ保存してはならない（MUST NOT）。

#### Scenario: Task完了後に障害が発生する
- **WHEN** あるTaskのArtifact公開後、次のTaskでRunが失敗する
- **THEN** Resumeは公開済みArtifactをpathから読取り、成功済みTaskを再実行しない

#### Scenario: Checkpointを検査する
- **WHEN** 保守者が文書処理中のcheckpointを検査する
- **THEN** checkpointはArtifact pathと小さいmetadataだけを含み、文書本文と画像binaryを含まない

### Requirement: ArtifactをAtomicに公開する
Systemは、各Resume対象Artifactを同一volumeの一時Fileへ完全に書込み、形式検証後に原子的に最終pathへ置換し、公開後だけTask完了をcheckpointへ記録しなければならない（MUST）。

#### Scenario: Artifact書込み中に中断する
- **WHEN** Artifactの書込みまたは検証中にprocessが中断する
- **THEN** 利用者とResume処理は旧完全版または未作成状態だけを観測し、部分Artifactを正本として扱わない

### Requirement: 正確な進捗を通知する
Systemは、すべての進捗eventへ有効な`current`と`total`を設定し、値を単調増加させ、正常終了時に`current == total`としなければならない（MUST）。CLIとStreamlitはeventの値を直接表示しなければならない（MUST）。

#### Scenario: 分岐を含む翻訳が完了する
- **WHEN** 翻訳Workflowが修正Taskを実行または省略して正常終了する
- **THEN** 表示進捗は後退せず最終的に100%になる

#### Scenario: 比較Reviewが完了する
- **WHEN** 英語側と日本語側の独立Taskを含む比較Workflowが正常終了する
- **THEN** 各Taskの進捗が通知され、最終的に100%になる

### Requirement: 外部障害を分類して処理する
Systemは、Network Error、408、429および5xxを設定可能な有限回数とbackoffでretryし、恒久的な4xxを即時失敗させなければならない（MUST）。Docling、LLM、LibreTranslateおよびQdrant検索が回復しない場合はResume可能な状態で停止し、Qdrant登録は失敗しなければならない（MUST）。Langfuse障害だけは警告を記録して本処理を継続しなければならない（MUST）。

#### Scenario: Qdrant検索が回復しない
- **WHEN** Qdrant検索が有限retry後も失敗する
- **THEN** Systemは参照なしで継続せず、失敗Taskと原因を記録してRunを停止する

#### Scenario: Langfuseが利用できない
- **WHEN** Trace送信またはflushが失敗する
- **THEN** Systemは秘密を含まない警告を記録し、本来のTaskを継続する

### Requirement: Runを明示的に削除できる
Systemは、利用者の明示操作と再確認後に限り、対象`runs/<run-id>/`の入力、出力および`.workspace/`を削除しなければならない（MUST）。実行中、lock取得中、存在しない、または共通Run root外のpathは削除してはならない（MUST NOT）。外部へExport済みの成果物は削除してはならない（MUST NOT）。

#### Scenario: 停止済みRunを削除する
- **WHEN** 利用者が表示されたrun IDとpathを確認して削除を確定する
- **THEN** Systemは正本Run directoryを削除し、外部Export成果物を保持する

#### Scenario: 実行中Runを削除しようとする
- **WHEN** 利用者がlock取得中のRunを削除しようとする
- **THEN** Systemは削除を拒否し、Runと全Artifactを保持する

### Requirement: Run情報から秘密と本文を保護する
Systemは、log、Error、checkpoint、run metadataおよびTraceへCredential、原文全文または画像binaryを記録してはならない（MUST NOT）。ErrorにはTask、対象PageまたはIDおよび秘密を除いた原因を含めなければならない（MUST）。

#### Scenario: 外部Serviceが認証Errorを返す
- **WHEN** Credentialを含む設定で外部Service認証が失敗する
- **THEN** SystemはTaskと原因を示し、Credentialと本文全文をlogおよび画面へ表示しない

### Requirement: Run Lifecycle品質を検証できる
Q-REL、Q-COMP、Q-USEおよびQ-SEC（ISO/IEC 25010）として、Systemは障害注入、CLI/UI相互Resume、進捗、削除境界および秘密非出力の自動Testを実行可能にし、部分Artifact、誤Resume、root外削除および秘密漏えいを0件にしなければならない（MUST）。

#### Scenario: Lifecycle Test suiteを実行する
- **WHEN** 保守者がRun LifecycleのUnit、IntegrationおよびUI Testを実行する
- **THEN** 全Scenarioが成功し、部分Artifact、誤Resume、root外削除および秘密漏えいが0件になる
