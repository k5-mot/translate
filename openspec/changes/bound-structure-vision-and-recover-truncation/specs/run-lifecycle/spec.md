<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: STRUCTUREのvision出力枯渇を異なる入力でだけ回復する
Systemは、STRUCTUREのvision応答が出力上限で切れた場合、その応答をparseまたは成果物へ採用せず、同じ画像・同じtoken予算によるretryをしてはならない（MUST NOT）。Systemは異なるtext-only入力による有限・逐次の回復を一度だけ開始でき、完全でschema適合する応答を得た場合だけTaskを継続しなければならない（MUST）。text-onlyも失敗または出力枯渇した場合は、Task、page、target、最終stage、終了理由および取得できた数値usageだけをFailureへ記録し、途中Artifactを公開せず同じRunをResume可能な状態で停止しなければならない（MUST）。Q-RELおよびQ-SEC（ISO/IEC 25010）として、truncated response採用0件、同条件vision retry 0件、同時Model／Embedding request最大1件、秘密・文書内容のFailure漏えい0件を境界Testで検証しなければならない（MUST）。

#### Scenario: vision出力が切れtext-onlyが完了する
- **WHEN** STRUCTUREのvision応答が出力上限で切れ、後続のtext-only応答が完全でschemaに適合する
- **THEN** Systemは切れたvision応答を捨て、text-only結果だけでTaskを継続し、active failureを残さない

#### Scenario: visionとtext-onlyの両方が失敗する
- **WHEN** STRUCTUREのvisionが出力枯渇し、text-onlyが有限retry後も完全なschema適合応答を返さない
- **THEN** Systemは最終失敗を安全な型付きFailureとして保存し、途中Artifactを公開せず同じRunの明示Resumeを可能にする

#### Scenario: 構造補正以外の出力が切れる
- **WHEN** TranslationまたはReviewなどSTRUCTURE以外のLLM応答が出力上限で切れる
- **THEN** Systemは同条件retryや途中応答の採用を行わず、従来どおりWorkflowをResume可能な状態で停止する

### Requirement: STRUCTUREの検証済みpageをResume時に再利用する
Systemは、STRUCTURE中に完全なschema適合応答で補正済みとなった各pageをRun内の非公開checkpointとして原子的に保存し、同じ入力および互換なfingerprintでの明示Resume時に整合性を検証してから再利用しなければならない（MUST）。不完全、破損または非互換なpage checkpointは採用せず、そのpageを再処理しなければならない（MUST）。Task全体が成功するまで公開STRUCTURE Artifactを作ってはならない（MUST NOT）。Q-RELおよびQ-COMP（ISO/IEC 25010）として、互換な完了pageの再推論0件、破損checkpoint採用0件、失敗時の公開途中Artifact 0件を中断・Resume Testで確認しなければならない（MUST）。

#### Scenario: 長いSTRUCTUREを途中から再開する
- **WHEN** page 2からpage Nまでが検証済みで、後続pageの失敗後に同じRunを明示Resumeする
- **THEN** Systemは検証済みpageを再推論せず、最初の未完了または無効なpageから逐次処理する

#### Scenario: page checkpointが破損している
- **WHEN** page checkpointの内容または整合性検証が失敗する
- **THEN** Systemはそのcheckpointを成果物へ採用せず、対象pageを再処理してからTaskを継続する

#### Scenario: STRUCTURE Taskが失敗する
- **WHEN** いずれかのpageが完全なschema適合応答を得られない
- **THEN** Systemは完了済みの非公開page checkpointを保持し、公開STRUCTURE Artifactと最終DOCXを作らずRunをfailedとして保持する
