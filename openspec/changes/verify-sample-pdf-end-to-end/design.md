<!-- markdownlint-disable MD041 -->

## Context

動機と対象範囲は[proposal.md](proposal.md)を参照する。現在の公開契約では`translate`はDOCXだけを生成し、`review`は英語PDFと日本語PDFを入力とする。固定入力は65 MB・358 pageであり、全処理は外部のDocling、LLM／EmbeddingおよびQdrantへ依存する。入力のpage 1はtext layerを持たず、page 3以降には英語text layerがあるため、表紙画像化と本文解析の両経路を通る。

検証はProject Codeを変更せず公開CLIを使用する。Word→PDF変換は利用者側の操作であり、変換実装、変換Toolの自動検出および変換品質保証をProjectへ追加しない。

## Goals / Non-Goals

**Goals:**

- 固定入力を用いて`register`、`translate`、`review`を実Service接続の公開CLI境界で検証する。
- 長時間処理のrun ID、進捗、failure、Resume、成果物および外部状態を追跡可能にする。
- 製品処理の失敗と、利用者が行うDOCX→PDF変換による差分を分離して判定する。
- 本番Qdrant Collectionと既存Runを変更せずに検証する。

**Non-Goals:**

- DOCX→PDF変換機能、CLI option、Python packageまたは外部変換Dependencyを追加しない。
- `translate`の公開成果物をPDFへ変更しない。
- 翻訳内容の専門的な軍事用語監修または原文自体の正確性評価を行わない。
- 358 pageの処理時間やLLM利用量を小規模fixtureの性能基準として一般化しない。
- 検証完了後にRun、export成果物またはQdrant Collectionを自動削除しない。

## Decisions

### 1. 二Phaseの受入検証にする

Phase Aはpreflight、`register`、`translate`および翻訳DOCXの検査までを行う。その後、利用者へDOCX pathとSHA-256を提示して停止する。利用者がPDF化したFileを指定した後、Phase BでPDFの読取り可能性とhashを確認し、原文PDFとともに`review`へ入力する。

一つの自動script内でWordを操作する案は、製品外Dependencyと対話Desktop Applicationの失敗を製品検証へ混入させるため採用しない。翻訳DOCXをreviewへ直接渡す案は、現在の`review`入力契約に反するため採用しない。

### 2. 固定入力identityをpreflight gateにする

Phase A開始前に、相対path、size `65475787` bytes、page数`358`およびSHA-256 `0185CD9631266FAD92FFCEDE31A447E51CFFA94EE572308310A490DC78A74182`を照合する。一つでも異なる場合は新規Runを作らず停止する。これにより同名差替えと途中更新を検出し、三操作が同一revisionを扱ったことを立証する。

### 3. 公開CLIを非対話で実行し、run IDを明示管理する

各初回操作は`cli.py`を非対話processで実行して必ず新規Runを作成し、stdoutの`run_id=`をEvidenceへ記録する。失敗時は`run.json`、`.workspace/failure.json`および安全な`run.log`を確認し、外部原因を修復した後だけ`--resume <run-id>`を明示する。入力やfingerprintが変わる場合はResumeせず新規Runにする。

内部関数を直接呼ぶ案は、CLIの設定読込み、Run共有、Error formatterおよびexport境界を検証できないため採用しない。

### 4. Qdrant状態を検証専用namespaceへ隔離する

実行processだけに`QDRANT_COLLECTION=translate-acceptance-sample-pdf`を設定し、`register`には`--source-id acceptance-sample-pdf`を渡す。`translate`と`review`も同じCollection設定を使用する。既存Collectionを再利用する案は、既存Chunkとの混在で件数・検索根拠・廃止範囲が曖昧になるため採用しない。

Collection作成または削除権限がない場合はpreflight失敗として記録し、本番Collectionへ切り替えない。Qdrant Collection削除は製品CLIの責務外なので、検証後も自動実行しない。

### 5. 成果物本体ではなく検証metadataをChangeへ記録する

入力PDF、DOCX、変換後PDF、画像およびRun directoryはOpenSpec Changeへ複製しない。`verification.md`には環境version、sanitized command、run ID、status、Task進捗、wall time、page／Chunk／Finding件数、成果物path・size・SHA-256および判定だけを記録する。Credential、原文全文、LLM応答全文および画像binaryは記録しない。

出力先は利用者が指定する絶対directoryとし、Projectの`runs/`およびGit管理対象directoryの外に置く。正本Runと明示export成果物を分けることで削除境界を維持する。

### 6. 操作ごとに独立したacceptance gateを設ける

- Register gate: exit code 0、Run status `completed`、`registration.json`が有効、登録Chunk数1以上、対象source IDだけが記録される。
- Translate gate: exit code 0、進捗最終値100%、Run status `completed`、DOCX ZIP／必須entry／CRC検証成功、成果物size 0より大、表紙重複なし、page 2以降の代表見出し・表・図・番号・URLのspot checkを記録する。
- User conversion gate: 利用者がPDF pathを明示し、Fileが読取り可能、1 page以上、SHA-256を取得可能である。DOCXとPDFの見た目差分は利用者側変換注記として残す。
- Review gate: exit code 0、進捗最終値100%、Run status `completed`、reportが空でなく、Finding集計と対応Groupが存在し、原文・訳文入力のhashがRun metadataと一致する。
- Lifecycle gate: 各失敗で公開中間成果物がなく、failureにTaskと安全な原因があり、Resumeを行った場合は完了済みTaskのArtifact hash／mtimeが不変である。

## Quality Attribute Design

| ID | Design approach | Trade-off | Verification evidence |
|---|---|---|---|
| Q-FUNC | 公開CLIと実Serviceで三操作を順に実行し、操作別gateを独立判定する | 全文の専門家Reviewは行わず、構造と機械的成果物を中心に判定する | exit code、Run status、Chunk／Finding／Group件数、DOCX／Markdown検査 |
| Q-PERF | 358 pageのwall time、Task時間、Run容量および外部retryを計測する | 固定入力一件の値であり一般的benchmarkにはしない | timing、size、retry／timeout記録 |
| Q-COMP | 同じQdrant Collectionと固定入力identityを三操作で共有する | 変換後PDFは利用者操作のためbyte-level再現性を要求しない | Collection名、source ID、入力／成果物hash |
| Q-USE | CLI表示のrun ID、進捗、Errorおよび成果物pathをそのまま検査する | 非対話実行なので対話候補選択は対象外 | sanitized console summary、最終進捗 |
| Q-REL | operation別Runを保持し、失敗後は明示`--resume`だけを使う | 外部障害を意図的には発生させない | failure Artifact、Resume前後のTask Artifact hash／mtime |
| Q-SEC | 専用Collectionとmetadata限定Evidenceを使う | 原文本文をEvidenceから直接確認できない | secret scan、Collection隔離、Evidence review |
| Q-MAIN | 再実行可能なcommand、環境version、identityおよび判定理由を残す | 外部Serviceの同一応答までは保証できない | `verification.md`と未完了Task |
| Q-PORT | 製品の既存Platform契約を変更せず、利用者変換を境界外にする | この受入実行自体は利用者のWord環境を含む | 製品Dependency差分0、変換処理のProject Code差分0 |

## Lifecycle, Migration and Operations

- 移行: schema、設定形式、公開interfaceおよび既存Runに変更はない。常に固定入力から新規acceptance Runを作成する。
- 運用: 実行前にDocling、LLM／Embedding、Qdrant、Pandoc、Credential、disk容量および利用上限をpreflightする。任意のLangfuse障害はwarningとして記録し、他Service障害は既存契約どおり停止する。
- Support: failure発生時はrun ID、Task、対象ID、redact済み原因、Service疎通およびretry回数を記録する。修正が必要な製品不具合は`tasks.md`へ未完了Taskとして追加してからApplyを停止する。
- 保守: 再検証では同じ入力hashとcommandを用いる。設定変更時はfingerprint差分を記録し、旧RunをResumeしない。
- 廃止: Run、export成果物およびQdrant Collectionを個別に一覧化する。利用者の明示確認後に各管理interfaceで削除し、自動cleanupは行わない。

## Risks / Trade-offs

- [Risk] 358 pageのLLM／OCR処理が長時間・高利用量になる → 実行前に容量と利用上限を確認し、操作ごとのRun IDと経過時間を定期記録してResume可能性を維持する。
- [Risk] ユーザ変換PDFの改ページやfont置換がReview Findingへ混入する → DOCX hash、PDF hash、変換日時および既知の変換差分を記録し、製品翻訳と変換由来を区別する。
- [Risk] registerが既存Qdrantデータを変更する → 専用Collectionとsource ID以外では実行せず、作成権限がない場合は停止する。
- [Risk] 実Service応答の非決定性で再実行結果が変わる → Model名、設定fingerprint、実行日時および検索Artifactを保存し、完全なbyte一致ではなく既存契約gateで判定する。
- [Risk] Evidenceへ秘密または本文が混入する → raw responseを転記せず、metadataとredact済みsummaryだけを記録してsecret scanを行う。

## Migration Plan

DeployおよびData migrationはない。Applyではpreflight後にPhase Aを実行し、利用者へDOCXを引き渡した時点で待機する。翻訳PDFのpathが提供されたらPhase Bを実行し、Evidenceと未完了Taskを更新する。Rollbackは新規Runの利用停止と専用Collectionの隔離で行い、削除は利用者の明示指示がある場合だけ実施する。
