<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

既存のUnit／Integration Testは小さいfixtureと障害注入を中心としており、65 MB・358 pageの実文書がQdrant登録、英日翻訳、比較Reviewの公開CLIを連続して完了できることを立証していない。`inputs/sample.pdf`を固定入力とする受入検証を実行し、実データ固有の不具合、外部Service境界、長時間RunのResumeおよび成果物品質を追跡可能な証跡にする。

## What Changes

- 固定入力のpath、SHA-256、sizeおよびpage数を検証開始前に確認し、入力取り違えを防止する。
- 専用のQdrant source IDと検証用Collectionを使用してPDFを`register`し、検索可能なChunk数と登録Runを記録する。
- 同じPDFをLLM Backendの`translate`へ入力し、日本語DOCX、Run metadata、進捗、警告および主要な構造保持結果を検査する。
- 利用者が翻訳DOCXをMicrosoft Word等でPDF化する。Word→PDF変換は製品仕様、Project実装およびDependencyへ含めない。
- 利用者から受領した翻訳PDFと原文PDFを`review`へ入力し、比較report、Finding、対応GroupおよびRun Artifactを検査する。
- 各操作のcommand、実行環境、run ID、所要時間、成果物hash、外部Service状態および判定を検証Evidenceへ記録する。失敗時は同じrun IDからResumeし、成功済みTaskが再実行されないことを確認する。
- 受入検証で見つかった製品不具合は成功扱いにせず、再現条件と未実装修正を`tasks.md`へ残す。
- 公開interface、既存Requirement、出力契約および自動Testの合格基準は変更しない。

## Capabilities

### New Capabilities

なし。このChangeは既存Capabilityの実データ受入検証と証跡作成だけを行う。

### Modified Capabilities

なし。`pdf-translation`、`comparison-review`、`reference-registration`および`run-lifecycle`のRequirementは変更しないため、`.openspec.yaml`で`skip_specs: true`を宣言する。

## Impact

- 対象入力: `inputs/sample.pdf`（65,475,787 bytes、358 pages、SHA-256 `0185CD9631266FAD92FFCEDE31A447E51CFFA94EE572308310A490DC78A74182`）
- 対象公開interface: `cli.py register`、`cli.py translate`、`cli.py review`、`cli.py runs`、`cli.py export`
- 対象外部System: Docling Serve、OpenAI互換LLM／Embedding API、Qdrant、任意のLangfuse
- 対象永続状態: 共通Run root、検証用Qdrant Collection、利用者が明示したexport先
- 新規Python packageおよび製品Dependencyは追加しない。Word→PDF変換は利用者側の操作とし、Projectは変換方法を保証しない。
- 358 page分のOCR、LLM、Embedding、保存容量および実行時間を消費するため、実行前にService疎通、容量、Credentialおよび利用上限を確認する。

## Stakeholders and Lifecycle Impact

- 利用者: 翻訳DOCXを確認してPDF化し、review用PDFのpathを保守者へ引き渡す。PDF化によるlayout差分は製品不具合と区別する。
- 保守者: 事前条件、command、run ID、成果物、失敗TaskおよびResume結果を記録し、PASS／FAILを根拠付きで判定する。
- 取得: 新規製品Dependencyは取得しない。既存外部Serviceの利用権限と処理量だけを事前確認する。
- 供給: 配布物と公開APIは変更しない。検証EvidenceのみをChange Artifactとして供給する。
- 移行: schema、Run layoutおよび既存データの移行は発生しない。検証は新規Runとして開始する。
- 運用: Qdrantは本番Collectionと分離した検証用Collectionを使用し、長時間処理はRun IDを保持してResumeする。自動的な再利用や削除は行わない。
- 保守・Support: 不具合時は秘密や文書全文を含まないfailure情報、Task名、対象IDおよびrun IDで再現可能にする。
- 廃止: Run削除とQdrant Collection削除は別操作である。成果物確認後の削除対象を提示するが、利用者の明示確認なしに削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: 3操作のexit codeが0で、登録Chunk数が1以上、翻訳DOCXが構造検証に合格し、Review reportがFinding件数と対応Groupを含むことを確認する。
- Q-PERF（性能効率性）: 操作別のwall time、Run容量、page数、Chunk数および主要Task時間を記録する。外部呼出しが設定済みtimeout／有限retryを越えて無期限に待機しないことを確認する。
- Q-COMP（互換性）: register後の同じCollectionをtranslate／reviewが利用でき、利用者がPDF化した成果物を既存review interfaceが変更なしで受理することを確認する。
- Q-USE（使用性）: CLIがrun ID、進捗、成果物pathおよび失敗Taskを表示し、正常終了時に進捗100%となることを確認する。
- Q-REL（信頼性）: 失敗時に部分成果物を公開せずfailed Runを保持し、環境復旧後に同じrun IDから成功済みTaskを再実行せずResumeできることを確認する。
- Q-SEC（セキュリティ）: log、Error、Run metadataおよびEvidenceにCredential、文書全文または画像binaryが含まれないことを確認する。専用Collectionで既存Qdrantデータへの影響を0件にする。
- Q-MAIN（保守性）: 入力fingerprint、環境version、command、run IDおよび判定根拠を記録し、失敗を具体的な修正Taskへ追跡できるようにする。
- Q-PORT（移植性）: 製品処理は既存のWindows／Ubuntu契約を変更しない。利用者によるWord→PDF変換はWindows側の検証準備であり、製品の移植性評価から除外する。
