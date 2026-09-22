<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: LLM token予算を実Modelのcontextへ整合させる
Systemは、対象Modelのcontext windowを30,208 tokensとして扱い、既定のcontext、最大出力、画像予約および安全余白をそれぞれ30,208、16,384、2,048および1,024 tokensにしなければならない（MUST）。Systemは、最大出力、画像予約、安全余白およびrequest入力の合計を有効context以内に保ち、明示されたcontextがModel上限を超える場合は30,208へ制限し、予約値の合計によって1,024 tokens以上の入力領域を確保できない設定は外部Serviceを呼ぶ前に拒否しなければならない（MUST）。Q-FUNCおよびQ-PERF（ISO/IEC 25010）として、30,208の設定保持、10,752 tokens以上の既定入力領域、context超過request 0件および同時Model request 1件以下を、設定境界Test、request構築Testおよび逐次実Model probeで検証しなければならない（MUST）。

#### Scenario: 実Modelのcontextを明示する
- **WHEN** 利用者がcontextを30,208 tokensに設定する
- **THEN** Systemは16,384へ切り下げず30,208を有効contextとして使用する

#### Scenario: 既定token予算を使用する
- **WHEN** 利用者がcontext、最大出力および画像予約を明示せずLLM処理を開始する
- **THEN** Systemは30,208 tokensのcontext内に最大出力16,384、画像予約2,048、安全余白1,024および入力領域10,752以上を確保する

#### Scenario: Model上限を超えるcontextを指定する
- **WHEN** 利用者が30,208 tokensを超えるcontextを設定する
- **THEN** Systemは有効contextを30,208へ制限し、その値をRun fingerprintへ記録する

#### Scenario: 予約値が入力領域を使い切る
- **WHEN** 最大出力と画像予約の合計が有効contextから1,024 tokensの入力領域を確保できない値である
- **THEN** Systemは値を暗黙変更せず設定ErrorとしてModel request前に拒否する

### Requirement: LLM出力枯渇を安全に分類し未回復時に停止する
Systemは、LLM応答をparseする前に終了理由と数値token usageを検査し、出力上限到達を`output-truncated`として分類しなければならない（MUST）。出力枯渇は同じrequestおよびtoken予算によるretry対象にせず、truncated responseを採用してはならない（MUST NOT）。STRUCTUREのvision出力枯渇後に異なるtext-only入力で完全なschema適合応答を得た場合だけTaskを継続し、それ以外ではTask、page、target、mode、stage、終了理由ならびにinput、outputおよびtotal token数だけをFailureへ保存して、途中成果物を公開せずWorkflowをResume可能な状態で停止しなければならない（MUST）。Q-REL、Q-USEおよびQ-SEC（ISO/IEC 25010）として、同条件retry 0件、truncated response採用0件、秘密または文書内容の診断漏えい0件をAdapter、Failure contract、redactionおよびAtomic Artifact Testで検証しなければならない（MUST）。

#### Scenario: 出力上限で空応答が返る
- **WHEN** LLMが`finish_reason=length`と空の応答本文を返す
- **THEN** Systemはparse Errorではなく`output-truncated`として一回で失敗させ、終了理由と数値token usageを記録する

#### Scenario: 出力上限で不完全な応答が返る
- **WHEN** LLMが`finish_reason=length`とschema不適合な途中本文を返す
- **THEN** Systemは本文をparseまたは成果物へ採用せず、同じtoken予算でretryしない

#### Scenario: 出力枯渇でWorkflowが停止する
- **WHEN** page処理で`output-truncated`が発生し、STRUCTUREの異なるtext-only入力でも完全なschema適合応答を得られない
- **THEN** Systemは失敗したTaskとpageから再開できるcheckpointを保持し、対応する途中Artifactを公開しない

#### Scenario: STRUCTUREのvision出力枯渇から回復する
- **WHEN** STRUCTUREのvision応答が出力枯渇し、異なるtext-only入力が完全なschema適合応答を返す
- **THEN** Systemは切れたvision応答を採用せず、text-onlyの結果だけでTaskを継続する

#### Scenario: 安全な診断を保存する
- **WHEN** Systemが出力枯渇のFailureと運用logを生成する
- **THEN** Systemはprompt、文書本文、reasoning content、raw応答、Credential、endpointおよび画像binaryを含めない

### Requirement: Token設定変更をRun境界として扱う
Systemは、context、最大出力および画像予約をRun fingerprintへ含め、いずれかが現在の設定と異なるRunのResumeを拒否しなければならない（MUST）。Systemは既存Runのmetadata、checkpoint、Failure、入力copyおよび成果物を書き換えず、変更後のtoken設定では新しいUUIDv7 Runを作成しなければならない（MUST）。Q-COMPおよびQ-REL（ISO/IEC 25010）として、token設定が異なる旧Runの誤Resume 0件、旧Runの変更0件および新規Run IDのUUIDv7適合をfingerprint、Resume拒否およびrepository差分Testで検証しなければならない（MUST）。

#### Scenario: 旧token予算のRunを再開する
- **WHEN** 現在のtoken設定とfingerprintが異なるRun IDを利用者が明示してResumeする
- **THEN** Systemは不一致のtoken fieldを示してResumeを拒否し、旧Runを変更しない

#### Scenario: 新token予算で同じ入力を処理する
- **WHEN** 同じ入力に互換なtoken fingerprintを持つ既存Runがない状態で利用者が処理を開始する
- **THEN** Systemは新しいUUIDv7 Runを作成し、すべてのModel requestを逐次実行する

#### Scenario: 旧形式のFailureを読む
- **WHEN** token usage診断fieldを持たない既存Failureを一覧または詳細表示する
- **THEN** Systemは既存fieldを失わずFailureを読取り、存在しない診断fieldを任意項目として扱う
