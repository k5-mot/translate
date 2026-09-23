<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: 翻訳応答形状を固定causeへ分類する

Systemは、翻訳Modelの応答が対象Inline ID集合と一致しない場合、または保護対象fragmentを欠落させた場合、本文、prompt、raw responseおよびCredentialを保存せず、`TRANSLATE`、対象page／chunkを識別できる固定causeと`text-parse` stageをFailureへ記録しなければならない（MUST）。Failureは既存の有限retry設定を使って同一chunkを逐次再試行し、上限到達後はRunをResume可能な状態で停止しなければならない（MUST）。

#### Scenario: 応答ID集合が一時的に不一致になる

- **WHEN** 翻訳chunkのModel応答に対象Inline IDの欠落または余分なIDがあり、有限retry回数内の再試行で一致する
- **THEN** Systemは同一chunkだけを逐次再試行して後続Taskへ進み、部分Artifactを公開せず、Failureをcompleted状態へ残さない

#### Scenario: 有限retry後も応答ID集合が不一致である

- **WHEN** 翻訳chunkのModel応答が上限回数まで不一致である
- **THEN** Systemは`TRANSLATE`、page／chunk識別子、固定causeおよび`text-parse` stageを秘密非含有Failureへ保存し、Runを停止して同じRunの明示Resumeを可能にする

#### Scenario: 保護fragmentが応答から欠落する

- **WHEN** 翻訳応答が対象IDを含むが、protected fragmentを保持していない
- **THEN** SystemはID不一致とは異なる固定causeへ分類し、有限retry後に同じResume可能停止を行う

## MODIFIED Requirements

### Requirement: 外部障害を分類して処理する

Systemは、Network Error、408、429および5xxを設定可能な有限回数とbackoffでretryし、恒久的な4xxを即時失敗させなければならない（MUST）。Docling、LLM、LibreTranslate、翻訳応答検証およびQdrant検索が回復しない場合はResume可能な状態で停止し、Qdrant登録は失敗しなければならない（MUST）。Langfuse障害だけは警告を記録して本処理を継続しなければならない（MUST）。各FailureにはTask、対象PageまたはID、秘密を含まない固定causeを記録しなければならない（MUST）。

#### Scenario: Qdrant検索が回復しない

- **WHEN** Qdrant検索が有限retry後も失敗する
- **THEN** Systemは参照なしで継続せず、失敗Taskと原因を記録してRunを停止する

#### Scenario: Langfuseが利用できない

- **WHEN** Trace送信またはflushが失敗する
- **THEN** Systemは秘密を含まない警告を記録し、本来のTaskを継続する

#### Scenario: 翻訳応答検証が回復しない

- **WHEN** 翻訳応答のIDまたは保護fragment検証が有限retry後も失敗する
- **THEN** Systemは裸のValueErrorを公開せず、`TRANSLATE`と固定causeを記録したResume可能Failureで停止する

### Requirement: Run情報から秘密と本文を保護する

Systemは、log、Error、checkpoint、run metadataおよびTraceへCredential、原文全文または画像binaryを記録してはならない（MUST NOT）。ErrorにはTask、対象PageまたはIDおよび秘密を除いた固定causeを含めなければならない（MUST）。翻訳応答の不一致Failureにも同じ秘密非含有制約を適用しなければならない（MUST）。

#### Scenario: 外部Serviceが認証Errorを返す

- **WHEN** Credentialを含む設定で外部Service認証が失敗する
- **THEN** SystemはTaskと原因を示し、Credentialと本文全文をlogおよび画面へ表示しない

#### Scenario: 翻訳応答の本文が不正である

- **WHEN** Model応答がIDまたは保護fragment検証に失敗する
- **THEN** Systemはraw response、prompt、本文およびendpointを保存せず、固定cause、stageおよび対象識別子だけをFailureへ記録する
