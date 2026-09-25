<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: 検証用にLLM推論を明示的に無効化できる
Systemは、CLIとStreamlit共通の環境設定`LLM_REASONING_MODE`に`task-default`または`off`を受け付け、未指定時は`task-default`としなければならない（MUST）。`task-default`では従来のTask別推論指定を維持し、`off`ではすべてのLLM要求についてTaskの指定より優先して推論とProviderのthinkingを無効化する指定を送らなければならない（MUST）。Embedding、モデル、token予算、timeout、逐次実行および有限retryは変更してはならない（MUST NOT）。不正値は外部要求前に拒否し、設定名と許容値だけを通知しなければならない（MUST）。Q-FUNC/Q-USEとして、全対象Taskの要求境界TestでOFF指定漏れと不正設定での外部呼出しを0件にしなければならない（MUST）。

#### Scenario: 推論設定を省略する
- **WHEN** 利用者が推論設定を省略または`task-default`を指定する
- **THEN** Systemは従来のTask別推論指定と出力切断回復を維持する

#### Scenario: OFFで検証する
- **WHEN** 利用者が`off`を指定して新規Runを開始する
- **THEN** STRUCTURE、TRANSLATE、ALIGN、REVIEW、VERIFY、FIXの各LLM要求は、初回と再試行を含め推論・thinkingの無効化指定で逐次送信される

#### Scenario: 不正な推論設定を指定する
- **WHEN** 許容値以外の`LLM_REASONING_MODE`が指定される
- **THEN** Systemは外部要求を開始せず、元入力を含めない設定Errorを返す

#### Scenario: OFFでも出力が切断される
- **WHEN** 推論無効化済みの翻訳要求が生成上限で切断される
- **THEN** Systemは推論の無効化だけを理由に同じ要求を再送せず、既存の有限な分割回復または失敗停止を適用し、部分応答を成功成果物にしない

### Requirement: 推論設定の実効値と検証結果を区別する
Systemは、LLM要求の観測を記録する場合、Taskの元指定ではなく適用済みの推論・thinking指定を記録しなければならない（MUST）。無効化指定を送信したことだけをProviderの推論tokenが0である証拠や、成果物品質の合格とみなしてはならない（MUST NOT）。Q-SEC/Q-RELとして、実効値の観測Testで不一致と新規metadataへの本文・Credential混入を0件にしなければならない（MUST）。Langfuse障害は従来どおり警告して処理を継続しなければならない（MUST）。

#### Scenario: Taskがhighを指定したが全体設定はOFFである
- **WHEN** 観測可能なLLM要求にOFF設定が適用される
- **THEN** 観測は推論none・thinking disabledを記録し、highの実行とは表示しない

#### Scenario: Providerの推論tokenが取得できない
- **WHEN** OFF要求の応答は成功したが推論tokenの内訳が得られない
- **THEN** 無効化指定の適用と応答成功だけを確認済みとし、推論tokenの実測は未確認として扱う

## MODIFIED Requirements

### Requirement: Resume互換性をFingerprintで判定する
Systemは、入力内容、Backend、出力へ影響するModel、Rule、用語集、Template、分割、Docling、OCR、Context、TokenおよびLLM推論設定をcanonical fingerprintによる互換性判定へ含めなければならない（MUST）。CredentialおよびQdrantの状態はfingerprintへ含めてはならない（MUST NOT）。fingerprintが異なるRunのResumeは、相違項目を表示して拒否しなければならない（MUST）。新設定導入前の推論設定記録がないRunは`task-default`として扱い、その他の入力・設定が等しい場合に新設定追加だけを理由としてResumeを拒否してはならない（MUST NOT）。Q-COMP/Q-RELとして、default/OFF間の誤Resumeを双方向で0件にする自動Testを備えなければならない（MUST）。

#### Scenario: 互換RunをResumeする
- **WHEN** 利用者が入力と出力影響設定のfingerprintが一致するrun IDを指定する
- **THEN** Systemは完了済みTaskを再利用して未完了Taskから再開する

#### Scenario: 設定が異なるRunを指定する
- **WHEN** 利用者がModel、Rule、用語集、Template、Docling、OCR、ContextまたはLLM推論設定の異なるrun IDを指定する
- **THEN** Systemは相違項目を表示してResumeを拒否する

#### Scenario: Qdrantだけが変更される
- **WHEN** 入力とfingerprint対象設定は同じでQdrant内容だけが変更される
- **THEN** SystemはResumeを拒否せず、完了済みTaskを再利用し、未完了Taskの検索結果を新しいArtifactへ保存する

#### Scenario: 新設定導入前のRunを通常設定でResumeする
- **WHEN** 保存済みRunに推論設定がなく、現在は`task-default`でその他の入力・設定が一致する
- **THEN** Systemは新設定の欠落だけで拒否せず、従来のCheckpoint識別を維持する

#### Scenario: OFFの新規検証で既存入力を指定する
- **WHEN** 非対話CLIでResumeを指定せず、旧通常設定Runと同じ入力をOFFで指定する
- **THEN** Systemは別IDの新規Runを作り、旧RunのCheckpointと成果物を再利用も上書きもしない
