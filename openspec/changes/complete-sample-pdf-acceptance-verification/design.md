<!-- markdownlint-disable MD041 -->

## Context

動機と対象範囲は[proposal.md](proposal.md)を参照する。先行Change `verify-sample-pdf-end-to-end`には固定入力のPreflightとReference Registrationの合格Evidenceがあり、専用Qdrant Collectionには対象source IDの1079 Pointが登録済みである。一方、Translation以降は未実行である。

公開契約では`translate`がDOCXを生成し、`review`が原文PDFと訳文PDFを比較する。利用者によるDOCX→PDF変換が両操作の間に必要であり、local LLM／Embedding Serverは並行Requestに耐えるHardware構成ではない。実行Artifactは共通Run root、明示export先、Qdrantおよび利用者変換先に分散するため、二Phaseの実行境界とEvidence連鎖を事前に固定する。

## Goals / Non-Goals

**Goals:**

- 先行Register Evidenceを改変せず、Translationからarchive判定までを独立したChangeで完遂する。
- 固定入力、Qdrant検索、DOCX、利用者変換PDF、Review reportおよびRunをhashとidentifierで追跡する。
- Model／Embeddingを含む全Workflow処理を逐次実行し、長時間Runの失敗とResumeを公開CLI境界で判定する。
- 製品翻訳、利用者変換およびComparison Reviewに由来する差分を分離する。

**Non-Goals:**

- Reference Registrationを再実行しない。
- DOCX→PDF変換機能、変換Tool自動化、Python packageまたは公開CLI optionを追加しない。
- 受入中に発見した製品不具合を、この検証Changeの未提案実装として修正しない。
- 専門家による軍事用語監修、原文自体の妥当性評価または358 page全文の人手校正を行わない。
- Run、外部export、利用者成果物またはQdrant Collectionを自動削除しない。

## Decisions

### 1. 先行Register Evidenceを不変の前提条件にする

Apply開始時に、先行Evidenceの固定入力hash、Register run ID、専用Collection、source ID、Point数および重複0件をread-onlyで再確認する。値が欠落または矛盾する場合はTranslation Runを作らず停止する。Qdrantは変更可能な外部状態であるため、現在のPoint状態は前提検査に使うがResume fingerprintには含めない。

Registrationを再実行する案は、合格済みEvidenceを重複させ、Qdrant revisionと廃止対象を曖昧にするため採用しない。再登録が必要な状態なら、このChangeをFAILとして別のRegistration Changeへ移管する。

### 2. TranslationとReviewを逐次実行する

TranslationとReviewは同時に起動せず、各Workflow内もModel、Embedding、page、groupおよびbranchの実行を同時実行数1に保つ。開始前に他のlocal Model workloadがないことを確認し、実行中に並列化optionや複数processを使用しない。各操作を新規UUIDv7 Runとして公開`cli.py`から開始し、失敗後だけ明示的な`--resume <run-id>`を使う。

並列化による時間短縮はlocal Hardwareの安定性と再現性を損なうため採用しない。内部関数の直接呼出しもCLI設定、Run lifecycle、Error表示およびexport境界を検証できないため採用しない。

### 3. Translationを独立した成果物gateで判定する

同じ専用Collectionを設定し、Git管理外の絶対export先へDOCXを出力する。成功条件はexit code 0、最終進捗100%、Run status `completed`、UUIDv7、DOCX size 0より大、ZIP必須entryおよびCRC成功とする。表紙画像は一度だけ存在し、対応する第1 page本文がMarkdown／DOCXに重複しないことを確認する。代表見出し、番号、Table、Figure、Caption、URLおよび保護対象はpage／対象IDと判定だけを記録する。

検索ArtifactではCollection名、検索日時、引用元と取得記録を確認し、Qdrant状態がfingerprintへ含まれないことを検査する。COVER、Docling、LLM、LibreTranslateまたはQdrant検索が有限retry後に失敗した場合はWorkflowを停止し、公開途中DOCXを残さず失敗TaskからResume可能な状態を保持する。Langfuse障害だけはwarningを記録して継続する。

### 4. 利用者引渡しを強制停止点にする

Translation gate合格後、DOCXの絶対path、sizeおよびSHA-256を提示してApplyを停止する。利用者から変換PDFの絶対pathを受領するまでReviewを開始しない。受領時にPDFの読取り可能性、page数、size、SHA-256およびmtimeを記録し、原文PDFとの表紙、最初の本文、代表見出し、Table／Figureおよび末尾pageを目視比較する。

製品がWordを操作する案は、未保証DependencyとDesktop対話を製品境界へ持ち込むため採用しない。変換後PDFのbyte一致も変換Applicationとfont環境で変わるため要求しない。

### 5. Reviewは原文PDFと利用者変換PDFを比較する

`review <original-pdf> <translated-pdf> --output <report>`を同じ専用Collection設定で逐次実行する。DOCXを直接Reviewへ渡さない。成功条件はexit code 0、最終進捗100%、Run status `completed`、空でないMarkdown report、Finding集計、対応Groupおよび両入力hash一致とする。

代表Findingを原文、DOCXおよび変換PDFと照合し、翻訳由来、利用者変換由来または誤検出へ分類する。Review失敗時はbranch別failureが対象IDとredact済み原因を持ち、公開途中reportがないことを確認する。Resumeした場合は成功済みbranch Artifactのhash／mtime不変を確認する。

### 6. Evidenceをmetadataに限定し、gateを独立判定する

新Changeの`verification.md`へ先行Evidence参照、sanitized command、環境version、run ID、status、進捗、wall time、retry、warning、件数、path、size、hashおよび判定を記録する。原文・訳文全文、raw LLM応答、Credential、画像binaryおよび外部job IDは記録しない。

Translate、User conversion、Review、Lifecycle、SecurityおよびQualityを個別にPASS／FAIL判定する。該当する障害が発生しなかったResume検査は、未検証をPASSと偽装せず`NOT EXERCISED`として理由を残す。製品不具合がgateを阻害した場合はFAIL Evidenceと再現条件を残し、別のOpenSpec Changeへ移管して本Changeのarchiveを許可しない。

## Quality Attribute Design

| ID | Design approach | Trade-off | Verification evidence |
|---|---|---|---|
| Q-FUNC | 公開CLI、固定入力および実ServiceでTranslationとReviewを順に実行し、成果物gateを分離する | 全文の専門家Reviewは行わず、構造と代表Findingを検査する | exit code、進捗、Run status、DOCX検査、Finding／Group件数 |
| Q-PERF | 全呼出しを逐次化し、wall time、Task時間、retry、Run容量を記録する | 長時間化を受容してlocal Hardwareの安定性を優先する | timing、retry、同時実行数1の設定／log |
| Q-COMP | 先行Registerと同じCollectionを使用し、既存Review interfaceへ利用者PDFを渡す | Qdrantの可変状態を再現性fingerprintには使わない | Collection、source ID、検索Artifact、入力hash |
| Q-USE | DOCX引渡しを明示停止点にし、path・size・hashを一意に提示する | 利用者操作が完了するまでApplyを完了できない | handoff記録、利用者指定PDF metadata |
| Q-REL | operation別UUIDv7 Run、有限retry、失敗Artifactおよび明示Resumeを用いる | 障害を意図的に注入しない場合はResume経路が`NOT EXERCISED`になる | `run.json`、`failure.json`、Artifact hash／mtime |
| Q-SEC | 専用Collectionとmetadata限定Evidenceを使い、最終secret／content scanを行う | 本文をEvidenceから直接再評価できない | scan結果、redact済みfailure、隔離確認 |
| Q-MAIN | 先行Evidenceから最終gateまでidentifierとhashで連鎖させる | 外部Model応答のbyte-level再現性は保証しない | `verification.md`、command、version、判定根拠 |
| Q-PORT | 製品Dependencyを変えず、利用者変換を明確な境界外にする | 受入のPhase Bは利用者環境に依存する | Project差分、Dependency差分、変換注記 |

## Lifecycle, Migration and Operations

- 移行: schema、設定、Run layoutおよび既存Dataに変更はない。先行Register Evidenceを参照し、TranslationとReviewだけ新規Runを作る。
- 運用: 実行前に固定入力、先行Evidence、Service疎通、disk、export先および他local workload不在を確認する。各Operationは逐次完了させてから次へ進む。
- Support: failure時はrun ID、Task、対象ID、stage、redact済み原因、retry回数および安全なService状態を記録する。修復後だけ同じrun IDを明示Resumeする。
- 保守: 現在のProject revision、設定fingerprintおよびModel名を記録する。Qdrant変更だけではResumeを拒否せず、それ以外のfingerprint不一致では新規Runを使う。
- 廃止: Translation／Review Run、外部DOCX／report、利用者PDFおよび専用Collectionを個別に一覧化する。利用者の明示削除指示なしに削除しない。

## Risks / Trade-offs

- [Risk] 358 pageの逐次OCR／LLM処理が長時間化する → Operationごとのrun ID、wall time、進捗およびdisk使用量を記録し、有限timeout後もResume可能なRunを保持する。
- [Risk] local Modelへ別processが接続してHardware capacityを超える → 開始前に他workload不在を確認し、TranslationとReviewを重ねず、内部同時実行数を1に固定する。
- [Risk] 先行Register後にQdrant内容が変更されている → Translation前に専用sourceのPoint状態をread-only確認し、欠落や混在はFAILとする。ただし状態revisionをResume fingerprintへ含めない。
- [Risk] 利用者変換で改ページ、fontまたは画像品質が変わる → DOCX／PDF hashと変換時刻を記録し、代表箇所の目視比較で変換由来をReview Findingから分離する。
- [Risk] 実Serviceの非決定性により再実行結果が変わる → Model、設定fingerprint、実行日時および検索Artifactを保存し、byte一致ではなく契約gateで判定する。
- [Risk] Evidenceへ秘密または文書内容が混入する → raw responseや本文を転記せず、最終Security scanで該当情報0件を確認する。
- [Risk] 製品不具合修正が検証範囲へ混入する → gateをFAILのまま止め、再現Evidenceを別ChangeのProposalへ渡す。

## Migration Plan

DeployおよびData migrationはない。Applyは、先行Evidence確認、Translation、DOCX検査、利用者引渡しの順に進めて停止する。利用者から変換PDFを受領した後、PDF検査、目視比較、Reviewおよび最終gateを順に実行する。Rollbackは新規Runの利用停止と専用Collectionの隔離であり、削除は利用者の明示指示がある場合だけ別操作で行う。
