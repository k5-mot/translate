<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

PDF翻訳ユーティリティは実装が先行し、公開操作、Runの寿命、Resume、成果物および外部障害時の契約を示すProject内仕様が存在しない。現状の実装と移植元の設計資料の差を解消し、CLIとStreamlitが同じ検証可能な契約に従うため、望ましい状態を初回のOpenSpec Capabilityとして定義する。

## What Changes

- PDF翻訳、英日PDF比較Review、参照文書登録およびMarkdownからDOCXへの変換について、入力、出力、失敗および品質の契約を定義する。
- CLIとStreamlitで共有する永続Runを導入し、明示的なResume、互換性判定、進捗、削除およびatomicなArtifact公開を定義する。
- 表紙画像を採用したPDFの第1ページ本文を成果物から除外し、表紙の二重出力を禁止する。
- 比較WorkflowをTask単位で再開可能にし、文書本体ではなくArtifact pathをcheckpointへ保持する。
- 出力へ影響する入力と設定をfingerprintへ含める。ただし変更され得るQdrantの状態はResume拒否条件に含めない。
- 外部サービスを有限回retryし、Docling、LLM、LibreTranslateおよびQdrant検索の回復不能な障害ではResume可能な状態で停止する。Langfuse障害だけは警告して継続する。
- Ruff対象とDependency宣言を整合させ、Project所有codeのLint、Format、型検査およびTestを完了条件にする。
- `CODING_RULES.md`を更新し、製品として保証する直接実行entry pointを`cli.py`と`main.py`に限定する。内部moduleのdebug entry pointは任意かつ非公開とする。
- **BREAKING**: Runの正本を`TRANSLATE_RUNS_DIR/<run-id>/`へ統一し、内部作業directoryを`.work/`から`.workspace/`へ変更する。
- **BREAKING**: Resumeはrun IDの明示指定または対話確認を必要とし、fingerprint非互換のRunを拒否する。
- **BREAKING**: Qdrant検索が有限retry後も失敗した場合、参照なしで継続せずWorkflowを停止する。

## Capabilities

### New Capabilities

- `pdf-translation`: 英語PDFを、文書構造と表紙を保持した日本語DOCXへ変換する契約。
- `comparison-review`: 独立した英日PDFを対応付け、入力を変更せずReview reportを生成する契約。
- `reference-registration`: 対応形式の参照文書をQdrantへ登録し、検索可能にする契約。
- `markdown-docx-conversion`: Markdownと参照templateから検証済みDOCXを生成する契約。
- `run-lifecycle`: CLIとStreamlitが共有するRunの作成、Resume、進捗、Artifact、障害および削除の契約。

### Modified Capabilities

なし。`openspec/specs/`に既存Capabilityは存在しない。

## Impact

- 公開interface: `cli.py`のRun選択・Resume・削除操作、`main.py`のRun一覧・確認・削除操作、成果物path。
- Workflow: `translate/workflows/translation.py`、`translate/workflows/comparison_review.py`のnode構成、stateおよびfingerprint。
- 共通基盤: `translate/common/workspace.py`、`progress.py`、`settings.py`、`logger.py`。
- TaskとAdapter: 表紙、Markdown、POSITION、Artifact書込み、Docling、LLM、LibreTranslate、Qdrant、Langfuse、Pandoc。
- Packageと品質設定: `pyproject.toml`、lock file、Ruff対象、直接Dependency、Test suite。
- 文書と規約: `CODING_RULES.md`、`CONTEXT.md`、ADR、`TODO.md`。

## Stakeholders and Lifecycle Impact

- **取得・供給**: 外部のDocling、OpenAI互換endpoint、LibreTranslate、Qdrant、LangfuseおよびPandocの前提条件と障害契約を明示する。新しい商用調達手続きは対象外であり、既存接続先を継続利用する。
- **開発・移行**: 既存`.work/`は自動移行せず、新形式のRunとして作り直す。実装前にTest fixtureを整備し、CapabilityとTaskを対応付ける。
- **運用**: 利用者は同一filesystem上のRunをCLIとStreamlitから列挙・再開・削除できる。非対話CLIは既存Runを暗黙に再開しない。
- **保守**: Task境界、Artifact契約、fingerprint項目およびDependencyを明示し、変更影響を追跡可能にする。
- **廃止**: Runの自動削除は行わない。明示削除は正本Runだけを対象とし、外部へexport済みの成果物を保持する。

## Quality Considerations

- **Q-FUNC（機能適合性）**: 各Requirementの正常系・異常系Scenarioを自動Testで100%実行し、表紙、Resume、比較対応付け、登録およびDOCX出力の期待結果を満たす。
- **Q-PERF（性能効率性）**: checkpointには文書本体や画像binaryを格納せず、Task Artifactのpathと小さい状態だけを保持する。外部待機のtimeout、deadlineおよびretry回数を設定可能にする。
- **Q-COMP（互換性）**: CLIとStreamlitが同じRun layoutとfingerprint判定を使用し、双方で作成した互換Runを相互にResumeできることをIntegration Testで確認する。
- **Q-USE（相互作用能力・使用性）**: すべての進捗eventが有効な`current/total`を持ち、正常終了時に100%になる。同一入力候補、非互換理由、失敗Taskおよび削除対象を利用者へ表示する。
- **Q-REL（信頼性）**: 各TaskのArtifactをatomicに公開し、障害注入後のResumeで完了済みTaskを再実行せず、不完全Artifactを正本として扱わないことを確認する。
- **Q-SEC（Security）**: log、error、checkpointおよびtraceへcredential、本文全文、画像binaryを出力しない。ZIP path traversalとRun root外の削除をTestで拒否する。
- **Q-MAIN（保守性）**: Project所有codeに対するRuff Lint/Format、`ty check`および`pytest`をすべてerror 0件で完了させ、Taskと外部I/Oの責務を分離する。
- **Q-PORT（柔軟性・移植性）**: Python 3.12以上と`pathlib`を前提に、WindowsとPOSIXのpathをfixtureで検証する。外部service自体の移植性は本Projectの管理外とする。
- **Safety**: 人身、設備または環境へ直接作用しない文書処理utilityであるため非該当。誤った成果物による情報品質RiskはQ-FUNC、Q-RELおよびQ-SECで扱う。
