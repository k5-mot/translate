<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

`establish-translate-ja-contracts`のArchive前検証で、自動品質Gateは成功した一方、参照登録、DOCX変換、失敗記録および秘密情報保護の公開経路が既に定義したRequirementを満たさないことが判明した。Taskの完了表記と実際の受入Evidenceも一致していないため、契約を変更せず実装と検証を正本仕様へ一致させる。

## What Changes

- FileとDirectoryの参照入力を共通Runへ安全にcopyし、公開CLIからDirectoryを登録可能にする。
- run IDに依存しない登録元IDを導入し、異なるRun間でも同じ登録元の旧Qdrant revisionを置換する。
- Markdown→DOCXのCLIとStreamlitで参照DOCXを指定可能にし、Markdown、参照DOCX、Pandoc機能および出力先を変換開始前に検証する。
- WorkflowのTask開始・失敗境界をRun Lifecycleへ伝え、失敗Task、page/group/対象IDおよびredact済み原因を保存・表示する。
- CLI、FIX/VERIFY ArtifactおよびLangfuse障害warningを共通redactionとRun warningへ接続する。
- 実PTY、`streamlit run main.py` subprocess、無効PDF、文書構造、公開登録Lifecycle、Python 3.12およびPOSIXを含む不足Test Evidenceを追加する。
- Run layoutの設計図と検証Evidenceを実装へ揃え、完了条件を実際に実施したTest方式で判定する。
- 公開契約、Run layoutおよび既存成果物形式は変更しない。既存Runの自動移行や自動削除も追加しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`establish-translate-ja-contracts`で定義した`pdf-translation`、`comparison-review`、`reference-registration`、`markdown-docx-conversion`および`run-lifecycle`のRequirementは変更しない。本Changeはその未達実装と受入Evidenceを補完するため、delta Specを作成しない。

## Impact

- 公開interface: `cli.py`の`register`と`convert` option、`main.py`の参照文書・参照DOCX入力および失敗表示。
- Run基盤: `translate/common/runs.py`、`lifecycle.py`、`redaction.py`、入力manifest、warningおよび失敗metadata。
- 外部Adapter: Qdrantの登録元ID・revision置換、Pandocの前提条件検証、Langfuse warning通知。
- TaskとWorkflow: FIX/VERIFYのError保存、翻訳・比較nodeの開始／失敗通知。
- Test/CI: CLI、Streamlit、Capability、Security、Windows/POSIXおよびPython 3.12の検証Matrix。
- 文書: Run layout図、検証Evidence、運用時の失敗診断情報。

## Stakeholders and Lifecycle Impact

- **取得・供給**: 新規外部Serviceや商用Dependencyは導入しない。既存のQdrant、Pandoc、LangfuseおよびPython Runtimeの契約をTest doubleとsubprocess Testで検証する。
- **移行**: Run schemaを変更する場合はschema versionと旧Run読込み方針を明示する。既存`.work/`の移行と既存Runの一括書換えは行わない。
- **運用**: 利用者はDirectory登録、参照DOCX指定、失敗Task確認およびCLI/UI Resumeを公開操作だけで実行できる。Langfuse障害はRun warningとlogの両方から診断できる。
- **保守**: Requirement、公開経路、Test Harnessをtraceableにし、checkboxは対応する自動Testが成功した後だけ完了にする。
- **廃止**: Runの自動削除は追加せず、既存の明示削除と外部export保持を維持する。
- **Safety**: 文書処理utilityであり、人身・設備・環境へ直接作用しないため非該当。情報品質と秘密漏えいRiskは機能適合性、信頼性およびSecurityで扱う。

## Quality Considerations

- **Q-FUNC（機能適合性）**: 参照Directory、異なるRun間のrevision置換、利用者指定参照DOCX、無効PDFおよび全文書要素Scenarioを自動Testし、未実行Scenarioを0件にする。
- **Q-PERF（性能効率性）**: Directory入力はstreaming hash/copyを使用し、文書本文やbinaryをcheckpointとrun metadataへ追加しない。代表Directoryで入力sizeを超える重複memory保持を0件にする。
- **Q-COMP（互換性）**: CLIとStreamlitが同じ入力manifest、登録元ID、fingerprintおよびError schemaを使用し、相互Resume Testを両方向で成功させる。
- **Q-USE（相互作用能力）**: 失敗画面へrun ID、失敗Task、対象識別子および安全な原因を表示し、秘密値と本文全文の表示を0件にする。
- **Q-REL（信頼性）**: 異なるRunからの再登録で重複旧Chunkを0件にし、前提条件失敗時のDOCX上書きと失敗Task誤記録を0件にする。
- **Q-SEC（Security）**: CLI stderr、Run warning、Task Artifact、log、checkpointおよびtraceへCredential、本文全文、画像binaryが出ないことを障害注入Testで確認する。
- **Q-MAIN（保守性）**: RequirementごとのTest対応表を整備し、Ruff、Format、型検査、pytest、OpenSpec strict validationをerror 0件で完了する。
- **Q-PORT（柔軟性・移植性）**: Python 3.12を最低VersionとしてWindowsとPOSIXのCIを成功させ、PTY非対応環境では明示的なplatform条件を記録する。
