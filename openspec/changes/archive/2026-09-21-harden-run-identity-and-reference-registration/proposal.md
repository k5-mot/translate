<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

65 MB・358 pageの受入PDFを参照登録したところ、PDF全体を一つのDocling jobへ送る現在の実装は約25分後に失敗し、Runへ残った原因も`RegistrationError`だけで失敗stageを判別できなかった。大規模入力を有限の処理単位で登録し、安全な診断情報からResume後の復旧判断を行えるようにするとともに、新規Runの識別子を生成時刻を含むUUIDv7へ移行する。

## What Changes

- 新規Run IDをRFC 9562のUUIDv7として生成し、Python 3.12で追加Dependencyを導入せずにversion、variantおよび時刻fieldを検証する。
- **BREAKING**: 有効なrun IDをcanonical UUIDv7だけに限定する。既存UUIDv4 Runの一覧、Resume、export、削除および自動移行は提供しない。
- 参照登録の失敗を安全なstageと下位例外型で構造化し、Credential、原文、raw応答または外部job IDを含めずに`failure.json`、Run logおよび公開Errorへ伝える。
- PDFを既存の`PDF_SPLIT_PAGES`単位へ決定的に分割してDoclingへ順次送信し、source hashをstreaming計算して、ChunkのEmbedding、Qdrant書込みおよび確認を有限batchで実行する。
- 全新revisionの書込みと確認が完了した後だけ旧revisionを削除し、途中失敗を成功として報告しない既存の置換契約を維持する。
- 固定受入入力`inputs/sample.pdf`で登録を再実行し、Task deadline内の完了、重複Chunk 0件、誤成功0件および秘密漏えい0件を検証する。
- WordからPDFへの変換は製品Scopeへ追加せず、利用者側Operationのままとする。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: Run IDをUUIDv7だけに限定し、UUIDv4 Runを無効な既存dataとして拒否する。
- `reference-registration`: 大規模PDFを有界な処理単位で登録し、失敗stageと安全な下位例外型を保持する要件を追加する。

## Impact

- Run基盤: `translate/common/runs.py`のID生成・UUIDv7限定検証およびRun Repository Test。
- 登録基盤: `translate/adapters/qdrant.py`のhash、PDF分割、Docling抽出、Chunk batch、登録確認、revision置換および構造化例外。
- LifecycleとSecurity: `translate/common/lifecycle.py`、`redaction.py`、`.workspace/failure.json`およびRun logの安全な診断表示。
- 設定: 既存の`PDF_SPLIT_PAGES`を参照登録にも適用する。新規runtime Dependencyと公開Command optionは追加しない。
- Test/Evidence: UUIDv7 conformance、UUIDv4拒否、stage別障害注入、有界処理、再登録、公開CLIおよび固定受入PDFのEvidence。
- 既存のCLI／Streamlit Run共有、明示Resume、Qdrant状態をfingerprintへ含めない規則およびsource keyの意味は変更しない。Point IDは新しいChunk schemaを識別できる決定的な形式へversion upする。

## Stakeholders and Lifecycle Impact

- **取得・供給**: 新規library、外部Serviceおよび商用契約は追加しない。既存のPython 3.12、pypdfium2、Docling、Embedding APIおよびQdrantを使用する。
- **移行**: 破壊的切替として、必要なUUIDv4 Runの成果物を旧Versionの公開操作で事前にexportし、不要なRunを明示削除する。自動変換、directory改名およびUUIDv4読込みは追加しない。
- **運用**: 利用者は従来の公開CLI／Streamlit操作を維持し、登録失敗時はrun ID、`REGISTER` Task、stageおよび下位例外型から復旧対象を判断できる。
- **保守・Support**: stage別障害注入と固定受入PDF Evidenceにより、抽出、書込み、確認および置換のどこで失敗したかを秘密なしで再現できるようにする。
- **廃止**: Runの自動削除、既存Runの一括移行およびQdrant Collectionの自動削除は追加しない。UUIDv4 Runの廃止は切替前に旧Versionの明示削除を使用し、外部export済み成果物を保持する。
- **Safety**: 文書処理utilityであり、人身・設備・環境へ直接作用しないため非該当。情報漏えいと不完全登録はSecurityおよび信頼性で扱う。

## Quality Considerations

- **Q-FUNC（機能適合性）**: 新規RunのUUID version 7／RFC variant、UUIDv4の一貫した拒否、358 page PDFの登録およびrevision置換を検証し、未登録・重複Chunk・誤成功を0件にする。
- **Q-PERF（性能効率性）**: PDF全体の`read_bytes()`を0件にし、1回のDocling入力を`PDF_SPLIT_PAGES`以下、Qdrant書込み・確認を固定上限以下のbatchにする。固定受入PDFを設定済みTask deadline内に完了させる。
- **Q-COMP（互換性）**: CLIとStreamlitがUUIDv7だけを同じRun Repositoryで扱い、UUIDv4を一覧から除外してResume、exportおよび削除を同じErrorで拒否するTestを成功させる。
- **Q-USE（相互作用能力）**: 公開失敗表示へrun ID、Task、登録stageおよび下位例外型を表示し、原因stage不明の`RegistrationError`を0件にする。
- **Q-REL（信頼性）**: 各PDF partとQdrant batchの一時障害を有限retryし、回復不能時はRunをResume可能なfailed状態に保つ。全新revision確認前の旧revision削除と成功報告を0件にする。
- **Q-SEC（Security）**: `failure.json`、Run log、consoleおよびmetadataにCredential、本文全文、raw応答、外部job IDおよび画像binaryが残らないことをsentinel Testで確認する。
- **Q-MAIN（保守性）**: UUID生成と安全な登録診断を小さい共通関数へ分離し、stage別Unit Test、Ruff、Format、型検査、pytestおよびOpenSpec strict validationをerror 0件で完了する。
- **Q-PORT（柔軟性・移植性）**: Python 3.12標準libraryだけでUUIDv7を生成し、WindowsとPOSIXで同じcanonical文字列表現、Run path検証およびUUIDv4拒否Testを成功させる。
