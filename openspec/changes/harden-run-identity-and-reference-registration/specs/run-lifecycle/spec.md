<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: 新規RunをUUIDv7で識別する
Systemは、新しく作成するすべてのRunへcanonicalなRFC 9562 UUIDv7を割り当てなければならない（MUST）。IDは生成時刻とRFC variantを正しく符号化し、CLIとStreamlitで同じ形式を使用しなければならない（MUST）。Q-FUNCおよびQ-PORT（ISO/IEC 25010）として、生成したIDのversion、variant、canonical表現および時刻を自動Testし、不正IDと衝突を0件にしなければならない（MUST）。

#### Scenario: CLIから新規Runを作成する
- **WHEN** 利用者がResume IDを指定せずCLIからRunを開始する
- **THEN** Systemは実行開始時刻を含むcanonical UUIDv7をrun IDとして使用する

#### Scenario: Streamlitから新規Runを作成する
- **WHEN** 利用者が既存Runを選択せずStreamlitからRunを開始する
- **THEN** SystemはCLIと同じUUIDv7形式で新しいRunを作成する

#### Scenario: 不正なRun IDを指定する
- **WHEN** 利用者がcanonical UUIDv4またはUUIDv7ではない値をRun操作へ指定する
- **THEN** SystemはRun root内のpathへアクセスする前に指定を拒否する

### Requirement: 既存UUIDv4 Runを継続利用できる
Systemは、移行前に保存されたcanonical UUIDv4 RunをUUIDv7 Runと同じRepositoryで読込み、一覧、Resume、exportおよび明示削除できなければならない（MUST）。Systemは既存UUIDv4 Runのdirectory名またはmetadataを暗黙に書き換えてはならない（MUST NOT）。Q-COMP（ISO/IEC 25010）として、新旧両形式の全Lifecycle操作を自動Testし、互換性Errorを0件にしなければならない（MUST）。

#### Scenario: UUIDv4 RunをResumeする
- **WHEN** 利用者が入力とfingerprintに互換性のある既存UUIDv4 run IDを明示指定する
- **THEN** SystemはIDを変更せず、そのRunの完了済みTaskを再利用してResumeする

#### Scenario: 新旧Runを同じ一覧へ表示する
- **WHEN** 共通Run rootにUUIDv4 RunとUUIDv7 Runが存在する
- **THEN** CLIとStreamlitは両方を有効なRunとして列挙し、それぞれをexportまたは明示削除できる

