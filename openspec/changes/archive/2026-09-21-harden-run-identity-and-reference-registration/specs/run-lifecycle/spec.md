<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

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
