<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: 大規模PDFを有界な処理単位で登録する
Systemは、PDFを設定済みpage上限以下の順序付きpartとして抽出し、source hashを入力sizeに比例するmemoryへ全量保持せず計算し、ChunkのEmbedding、書込みおよび確認を有限件数のbatchで実行しなければならない（MUST）。同じ入力、登録元IDおよび分割設定からは同じChunk順序とPoint IDを生成し、すべての新revisionを確認した後だけ旧revisionを削除しなければならない（MUST）。Q-PERFおよびQ-REL（ISO/IEC 25010）として、1回のDocling入力を`PDF_SPLIT_PAGES`以下にし、Qdrant batchを設計上の固定上限以下に保ち、65 MB・358 pageの固定受入PDFを設定済みTask deadline内に登録完了させなければならない（MUST）。

#### Scenario: 大規模PDFを新規登録する
- **WHEN** 利用者がpage数の多いPDFを公開CLIまたはStreamlitから登録する
- **THEN** Systemはpage上限以下のpartを元page順に処理し、全Chunkの登録確認後に成功件数を返す

#### Scenario: 大規模PDFの登録途中で外部Serviceが失敗する
- **WHEN** Docling、EmbeddingまたはQdrantの有限retryが回復せず、partまたはbatchの処理が完了しない
- **THEN** Systemは登録成功を報告せず、旧revisionを保持し、同じrun IDから再実行可能なfailed Runを保存する

#### Scenario: 同じ大規模PDFを再登録する
- **WHEN** 同じ登録元ID、入力内容および分割設定のPDFを再登録する
- **THEN** Systemは決定的なPoint IDを再利用し、確認済みChunkの重複と旧revisionの残存を0件にする

### Requirement: 登録失敗を安全なstage情報で診断できる
Systemは、登録失敗時に`REGISTER` Task、失敗stageおよび下位例外型を`failure.json`、Run logならびに公開Errorへ保持しなければならない（MUST）。stageは収集、hash、分割、抽出、書込み、確認およびrevision置換を区別しなければならない（MUST）。Credential、文書本文、raw外部応答、外部job IDおよび画像binaryを診断情報へ含めてはならない（MUST NOT）。Q-USEおよびQ-SEC（ISO/IEC 25010）として、stage別障害注入Testで原因stage不明と秘密漏えいを0件にしなければならない（MUST）。

#### Scenario: Docling抽出が失敗する
- **WHEN** PDF partのDocling抽出が有限retry後も失敗する
- **THEN** Systemは`REGISTER`、抽出stageおよび安全な下位例外型を記録し、raw応答と外部job IDを記録しない

#### Scenario: Qdrant登録確認が失敗する
- **WHEN** 書込み済みPointの確認が有限retry後も完了しない
- **THEN** Systemは確認stageと安全な下位例外型を記録し、登録成功件数を報告せず旧revisionを削除しない

#### Scenario: Revision置換が失敗する
- **WHEN** 新revision確認後の旧revision削除が有限retry後も失敗する
- **THEN** Systemはrevision置換stageと安全な下位例外型を記録し、登録操作全体を失敗として返す
