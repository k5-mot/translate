<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

先行Change `verify-sample-pdf-end-to-end`は固定入力のPreflightとReference Registrationまでを完了したが、実PDFのTranslation、利用者によるPDF化、Comparison Reviewおよび最終受入判定の17 Taskが未完了である。完了済み証跡を保持したまま後続検証の責務を独立させ、製品修正と受入検証を混在させずにarchive可否まで判定する。

## What Changes

- 先行Changeで合格済みの固定入力identity、専用Qdrant CollectionおよびRegister Run Evidenceを前提条件として参照し、Registrationを再実行せずTranslationから検証を再開する。
- 公開CLIで`inputs/sample.pdf`をTranslationし、local LLM／EmbeddingのHardware制約に合わせて全処理を逐次実行する。Run、進捗、retry、warning、検索ArtifactおよびDOCXの完全性・構造を検査する。
- 翻訳DOCXの絶対path、sizeおよびSHA-256を利用者へ提示して停止する。利用者がMicrosoft Word等でPDF化した成果物を受領し、製品へWord→PDF変換機能またはDependencyを追加せず、原文との目視比較を行う。
- 公開CLIで原文PDFと利用者変換PDFをComparison Reviewし、Run、進捗、report、Finding、対応Group、入力hashおよび代表Findingの由来を検査する。
- 最終Quality gate、Security scan、Run lifecycle、廃止対象一覧およびarchive可否をEvidenceへ記録する。Run、export成果物およびQdrant Collectionは自動削除しない。
- 検証中に製品不具合を発見した場合は該当gateをFAILのまま保持し、再現情報を記録して別の修正Changeを提案する。このChange内で未提案の製品Code修正を行わない。
- 公開interface、既存Requirement、出力契約、Run schemaおよび製品Dependencyは変更しない。

## Capabilities

### New Capabilities

なし。このChangeは既存Capabilityに対する実データ受入検証とEvidence作成だけを行う。

### Modified Capabilities

なし。`pdf-translation`、`comparison-review`、`reference-registration`および`run-lifecycle`のRequirementを変更しないため、`.openspec.yaml`で`skip_specs: true`を宣言する。

## Impact

- 対象入力: `inputs/sample.pdf`（65,475,787 bytes、358 pages、SHA-256 `0185CD9631266FAD92FFCEDE31A447E51CFFA94EE572308310A490DC78A74182`）
- 前提Evidence: 先行ChangeのRegister Run `01a0bf06-60d8-7446-a63c-7f22e8ee698a`、専用Collection `translate-acceptance-sample-pdf`、source ID `acceptance-sample-pdf`
- 対象公開interface: `cli.py translate`、`cli.py review`、`cli.py runs`、`cli.py export`
- 対象外部System: Docling Serve、OpenAI互換LLM／Embedding API、Qdrant、任意のLangfuse、利用者のPDF変換Application
- 対象永続状態: 共通Run root、検証用Qdrant Collection、Git管理外の明示export先および利用者変換PDF
- 新規Python package、製品Dependency、公開APIおよびData migrationは追加しない。長時間のOCR、LLMおよびEmbedding処理はすべて逐次実行する。

## Stakeholders and Lifecycle Impact

- 利用者: DOCXをPDF化して絶対pathを引き渡し、目視比較で変換由来のlayout差分を確認する。製品は変換方法を保証しない。
- 保守者: 先行Evidenceとの連続性、sanitized command、run ID、成果物hash、失敗Task、Resume結果およびgate判定を記録する。
- 取得・供給: 新規製品Dependencyを取得せず、既存外部Serviceと利用者所有Applicationだけを使用する。供給物は検証Evidenceであり、実成果物をGitへ格納しない。
- 移行: schema、Run layoutおよび既存Runの移行はない。TranslationとReviewは新規UUIDv7 Runとして開始し、Resume時だけ同じrun IDを明示する。
- 運用・保守: local Modelへ並行Requestを送らない。有限retry後の失敗はResume可能なRunとして保持し、Langfuse障害だけはwarningで継続する。Qdrant状態はResume fingerprintへ含めない。
- 廃止: 正本Run、外部exportおよび専用Collectionを個別に列挙する。自動削除は行わず、archiveも全gate判定後にだけ許可する。

## Quality Considerations

- Q-FUNC（機能適合性）: TranslationとReviewがexit code 0、最終進捗100%、Run status `completed`となり、DOCXとreportが各成果物gateを満たすことを確認する。
- Q-PERF（性能効率性）: 操作別wall time、Run容量、retryおよび主要Task時間を記録し、設定済みtimeoutを越える無期限待機とModel並行実行が0件であることを確認する。
- Q-COMP（互換性）: 先行Registerと同じ専用Collectionを使用し、利用者変換PDFを既存Review interfaceが変更なしで受理することを確認する。
- Q-USE（使用性）: CLIがrun ID、進捗、成果物pathおよび安全な失敗情報を表示し、DOCX引渡し情報が利用者に一意であることを確認する。
- Q-REL（信頼性）: 失敗時に不完全成果物を公開せず、Runを保持する。Resumeした場合は成功済みTask Artifactのhash／mtimeが不変であることを確認する。
- Q-SEC（セキュリティ）: console、Run metadata、log、failureおよびEvidenceへのCredential、文書全文、raw LLM応答、画像binaryの漏えいを0件とする。
- Q-MAIN（保守性）: 入力・成果物hash、環境version、command、run ID、判定根拠および不具合の移管先を追跡可能にする。
- Q-PORT（移植性）: 製品の既存Platform契約とDependencyを変更しない。利用者のWord→PDF操作は製品検証境界外として明示する。
- Performance efficiency以外のInteraction capability、SafetyおよびFlexibilityは、このChangeが公開interfaceや製品機能を変更しないため新規評価対象としない。既存契約への回帰は最終Quality gateで確認する。
