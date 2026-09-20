<!-- markdownlint-disable MD041 -->

## Context

動機は[proposal.md](proposal.md)のWhyを参照する。現実装はCLI、Streamlit、2つのWorkflow、20個のTaskおよび外部Adapterを持つが、Runの正本が呼出元の出力先に依存し、Streamlitは一時directoryを破棄している。比較Workflowは複数Taskを1 nodeへまとめ、両WorkflowのcheckpointはInternal Document全体を保持する。Artifactの大半は直接書込みであり、fingerprint、進捗、retryおよびtraceも不完全である。

移植元の`C:\Users\merry\Desktop\skills\SPEC.md`と`CONTEXT.md`は設計資料として参照するが、本Projectの正式仕様または既存Capabilityとは扱わない。利用者との設計確認で確定した内容と、このChangeの5 Specを正とする。

## Goals / Non-Goals

**Goals:**

- CLIとStreamlitが同じ永続Runを相互に列挙・Resume・削除できる共通基盤を作る。
- すべてのTaskを独立したArtifact契約とcheckpoint境界へ揃える。
- 入力・設定変更による誤Resume、部分Artifact、誤った進捗および無警告の外部障害を防ぐ。
- 表紙、POSITION、比較対応付けおよび最終出力の品質契約をTest可能にする。
- Project所有codeのDependency、Lint、型検査およびTestを一貫した完了条件にする。

**Non-Goals:**

- 旧`.work/` Runの自動移行または互換読込み。
- Qdrant Collection内容のsnapshot化、version固定または変更を理由とするResume拒否。
- 各Taskを製品向けの個別CLIとして公開すること。
- 新しいTask基底class、registry、DI container、event busまたは汎用retry framework。
- 独自OOXML後処理、Word入力翻訳、並列Reviewerまたは再帰的なFIX loopの復活。

## Decisions

### 1. Run RepositoryをCLIとStreamlitの唯一の正本にする

`TRANSLATE_RUNS_DIR`を共通rootとし、未設定時はProject直下の`runs/`を使う。Run IDには衝突回避だけを責務とするUUID4を使い、利用者が指定したFile名やpathをIDへ埋め込まない。

```text
runs/<run-id>/
├── inputs/                    # 入力の正本copy
├── outputs/                   # Run内の公開成果物
└── .workspace/
    ├── run.json               # status、input hash、設定snapshot、fingerprint
    ├── run.lock
    ├── checkpoints.sqlite
    ├── logs/run.log
    └── <task-name>/           # Task Artifact
```

CLIの`--output-dir`はRun正本の場所ではなく、完了成果物の任意export先とする。Streamlitのdownloadも`outputs/`の正本を読む。外部exportはRun削除の対象外とする。

代替案の「各CLI出力先をRun rootにする」は、Streamlitが未知のpathを安全に列挙できず相互Resumeを保証できないため採用しない。中央DBによるRun registryも、directoryとDBの二重正本になるため採用しない。Run一覧はroot直下の`run.json`を走査して構築する。

### 2. Resumeは明示を基本とし、同一入力だけ対話支援する

CLIは`--resume <run-id>`、StreamlitはRun一覧の選択でResumeする。指定がなければ新規Runを作る。ただし対話端末で入力SHA-256が一致するRunがある場合は、更新日時、status、run IDおよびfingerprint互換性を表示し、`y`で互換RunをResume、`n`で新規作成する。複数候補は新しい順に提示し、利用者がrun IDを選ぶ。

非対話CLIでは質問せず新規Runを作る。Automationで暗黙Resumeを起こす`--yes`は追加しない。Streamlitは選択と確認を別操作にし、rerunだけでResumeを開始しない。

### 3. Fingerprintは出力影響入力をCanonical JSON化する

`run.json`へ項目別snapshotと、そのUTF-8 canonical JSONのSHA-256を保存する。対象は次とする。

- 全入力FileのSHA-256と役割
- 操作種別と翻訳Backend
- split page数
- Docling/OCRのpreset、language、force OCR、table、imageおよびenrichment設定
- structure、translation、review、fix、embeddingのModel識別子
- context、token、batchおよびchunkに関する出力影響設定
- structure、translation、review Ruleの内容hash
- glossaryとDOCX templateの内容hash
- LibreTranslateの出力影響設定

Credential、timeout、retry回数、log level、Langfuse接続情報およびQdrantの内容・revisionは除外する。Resume時は項目単位の差分を表示し、一つでも異なれば拒否する。部分無効化ではなくRun単位拒否とすることで、どこから再計算すべきかという第二の状態機械を作らない。

Qdrantは可変である。完了済みTaskは保存済み検索Artifactを再利用し、未完了Taskは現在のCollectionを検索する。検索query、Collection名、検索日時、引用元および結果をTask Artifactへ保存するが、再現性情報であってResume gateにはしない。この選択により一つのResume Runに異なる時点の検索結果が混在し得ることを受容する。

### 4. 各Taskを独立nodeにし、Graph StateをPathだけにする

翻訳Workflowは移植元のTask順を維持し、Backend選択とFinding有無だけをconditional edgeにする。比較Workflowは英語側と日本語側それぞれのSPLIT、DOCLING、UNPACK、MERGE、POSITION、NORMALIZE、LOADを独立nodeにし、両LOAD後にALIGNへjoinする。

各nodeは入力Artifactをpathから読み、出力Artifactをpathへ保存し、stateにはpath、status、warning、現在のpage/groupおよび進捗だけを返す。Internal Document、Finding集合、Alignment本文および画像binaryはstateへ入れない。これによりSQLite checkpointの反復複製と肥大化を止め、Task単位の失敗位置を保持する。

### 5. Artifact publishを共通のAtomic規則へ統一する

Text、JSON、PDF、ZIP、画像および最終成果物は、最終pathと同じvolumeのsibling temporary fileへ書き、flush、必要な`fsync`および形式検証後にreplaceする。Directory Artifactはtemporary directoryを完成させ、manifestを最後にpublishする。nodeはpublish成功後だけ完了を返す。

失敗時のtemporary fileはcleanup対象だが、cleanup失敗を元のErrorより優先しない。既存の完全版を部分版で置換しない。Pandoc Adapterの既存temp→replaceも同じ契約へ揃える。

### 6. 進捗は固定の論理Task単位で数える

翻訳は17論理Task、比較は左右7 TaskずつとALIGN、CHECK、REVIEW、REPORTの計18 Taskをtotalとする。選択されなかった翻訳Backend、Findingなしで省略するFIX/VERIFYなどは`skipped` eventを出し、currentを進める。これにより分岐の有無に関係なくtotalを開始時に確定できる。

各eventは`task/current/total/message/level`を持ち、Workflowの共通変換層だけがcurrentを更新する。CLIとStreamlitは再計算せず値を表示する。Resume開始時はcheckpointから完了・skip済み数をcurrentへ反映する。

### 7. 外部ServiceごとにRetryと停止境界を固定する

Docling、LLM、LibreTranslateおよびQdrantは、Network Error、408、429、5xxだけを指数backoffとjitter付きで既定3回retryする。timeout、deadline、最大試行回数およびbackoff上限は設定可能にする。認証、入力不正などの恒久4xxは即時失敗する。

- Docling、LLM、LibreTranslate、Qdrant検索: 回復しなければ現在Taskを失敗させ、RunをResume可能に停止する。
- Qdrant登録: 操作全体を失敗とし、成功件数を返さない。
- Langfuse: 警告をRunへ記録し、観測なしで本処理を継続する。
- FIX/VERIFY: 外部呼出し失敗を対象翻訳単位の`skipped`として扱い、修正前訳で継続するというCapability固有規則を維持する。

Retry判断は各Adapterに置き、TaskとWorkflowにHTTP status判定を重複させない。例外を空結果へ変換しない。

### 8. 表紙の対象Pageを明示してMarkdownから除外する

COVER Artifactは画像pathだけでなく、除外対象の原本page番号をmanifestとして返す。MARKDOWNはmanifestにあるpageを本文走査から除外し、表紙画像を先頭へ一度だけ置く。Backend側の「第1ページを翻訳しない」という暗黙規則だけには依存しない。

COVER失敗は出力欠損になるため停止する。第1ページが実際に表紙かを推測する分類は行わず、現契約どおり常に第1ページを表紙として扱う。

### 9. POSITIONを決定的なLayout補正として完成させる

Page単位で要素を分類し、座標がある本文要素からcolumn帯を推定する。英語文書を前提にcolumnを左から右、各column内を上から下へ並べる。Header、Footer、欄外要素は本文帯との位置関係を使い、重なりはvertical center、left、元indexの安定tie-breakで決める。座標がない要素は元順を維持する。

隣接するparagraph/code fragmentはlabel、幾何的連続性および参照関係が一致する場合だけ結合する。Table fragmentはrow/column/spanと参照を再構成できる場合だけ結合し、曖昧な場合は別Tableのままreportへ警告する。全補正をbefore/after IDと理由付きreportへ残す。

### 10. Dependency、LintおよびStreamlitをProject規約へ揃える

- 直接importする`langchain-core`と運用上必要な`langsmith`を直接Dependencyへ追加する。
- `langchain`と`langgraph`へ`<2`の上限を付け、直接利用しない`openai`は削除する。`typing-extensions`はRuntimeで直接必要かを確認してから削除する。
- Ruffの意図した`DOC` ignoreと矛盾する個別`DOC201/DOC202/DOC501` selectを除き、Project外toolingである`.agents/`を標準`ruff check .`の対象外へ明示する。
- Streamlit upload型を公開型へ置換し、2択Backendはsegmented controlにする。`main()`と描画関数は製品entry point規則およびTest容易性のため維持する。
- `Finding`の二重定義をInternal Document側の一形式へ統一し、VALIDATEへ`skipped`警告を伝播する。

### 11. 製品Entry PointとDebug Entry Pointを分離する

製品として保証する直接実行は`cli.py`と`main.py`だけとする。内部moduleはdebug上有用な場合だけ`main()`とguardを持てるが、公開interfaceとして文書化せず、既存関数へ委譲し、製品処理を複製しない。全Python Fileへ形式的なguardを置かない。

Taskの`run()`と製品entry pointは`time.perf_counter()`で経過時間を出力する。計測用Decorator、stateまたは集計Fileは追加しない。

### 12. Langfuseを任意の観測境界として接続する

Workflow Run、TaskおよびLLM呼出しへ相関可能なtrace/spanを作り、成功・失敗の終了状態を記録してflushする。Credential、本文全文および画像をattributeへ入れない。Langfuseが無効なら追加処理をせず、有効で送信失敗した場合だけRun警告を残す。

## Quality Attribute Design

| 品質ID | Design Approach | Trade-off | 検証Evidence |
| --- | --- | --- | --- |
| Q-FUNC | 5 CapabilityのScenarioをfixtureとE2Eへ対応付ける | 外部ServiceはTest doubleが必要 | Requirement単位のpytest、Streamlit browser test |
| Q-PERF | path-only state、Task Artifact、固定Task進捗 | Artifact read/writeは増える | checkpointに本文・binaryがないこと、代表文書のsize計測 |
| Q-COMP | 共通Run Repositoryと共通callback | filesystem共有がないHost間Resumeは対象外 | CLI作成→UI Resume、UI作成→CLI ResumeのIntegration Test |
| Q-USE | 明示Resume、候補提示、差分表示、正確なcurrent/total | 対話が1段増える | TTY/non-TTY Test、完了時100%のUI Test |
| Q-REL | atomic publish、Task node、有限retry | temporary容量とretry時間が増える | 各Task境界の障害注入Test、旧完全版保持Test |
| Q-SEC | root containment、秘密redaction、安全なZIP展開 | 診断情報を意図的に制限する | traversal、root外削除、credential redaction Test |
| Q-MAIN | 単一Finding、責務境界、直接Dependency、品質gate | 初回にTest整備costがかかる | Ruff/Format/ty/pytestの成功log |
| Q-PORT | `pathlib`と設定可能なroot | 外部Tool差異は残る | Windows/POSIX path fixture、Python 3.12 CI |

## Lifecycle, Migration and Operations

- **Transition**: 新しいRun Repository、Artifact writer、state schemaを先に導入し、その後Workflow、CLI、Streamlitを切り替える。旧`.work/`は読まず、利用者には新Run作成を案内する。
- **Rollback**: Codeを旧版へ戻しても旧出力先は上書きしない。新しい`runs/`は削除せず、再適用時の診断資料として保持する。
- **Operation**: Run一覧にstatus、操作、入力名、作成・更新日時、fingerprint互換性および最後のTaskを表示する。Run root容量は運用者が監視し、削除は明示操作とする。
- **Support**: Errorにはrun ID、Task、page/group、対象IDおよびredact済み原因を含め、log pathを案内する。外部Serviceのhealth自体は本Projectの管理外とする。
- **Maintenance**: Capability ScenarioとTask Testをtraceableに保ち、Dependency更新時はlock、import smoke test、全品質gateを再実行する。
- **Disposal**: Run削除はresolved absolute pathが`TRANSLATE_RUNS_DIR`直下の対象run IDに一致し、lockされていないことを検証してから行う。Export先は触らない。

## Risks / Trade-offs

- [Qdrantをfingerprintから除外するためResume Run内で検索時点が混在する] → 各検索結果と日時をArtifactへ保存し、完了Taskを再検索しないことを明示する。
- [Project直下`runs/`が大容量化する] → 自動削除は行わず、一覧にsizeを表示し、安全な明示削除を提供する。
- [固定Task進捗はPage数やTask時間を反映しない] → 正確な完了率を優先し、messageでpage/group進捗を補足する。
- [旧`.work/`をResumeできない] → 自動変換の複雑性と誤Resume Riskを避け、新Run作成を案内する。
- [外部Service retryにより失敗確定が遅れる] → deadlineと最大試行を設定可能にし、恒久4xxは即時失敗させる。
- [CLIとStreamlitの同時操作が競合する] → Run単位lockを共通化し、二重実行と実行中削除を拒否する。

## Migration Plan

1. `CODING_RULES.md`、Dependency、Ruff対象およびTest基盤を整え、Project所有codeの品質gateを安定させる。
2. 共通Run Repositoryと`runs/<run-id>/{inputs,outputs,.workspace}` layout、atomic writer、fingerprintおよびlockを実装する。
3. Task Artifact形式と単一Finding schemaを確定し、既存Taskの直接書込みをatomic publishへ移行する。
4. 翻訳・比較WorkflowをTask nodeとpath-only stateへ移行し、progress、retry、traceおよびResumeを接続する。
5. CLIとStreamlitを共通Run Repositoryへ切り替え、同一入力確認、明示Resume、一覧、Exportおよび削除を追加する。
6. Capability Scenario、障害注入、CLI/UI相互Resumeおよびbrowser Testを完了し、全品質gateを通す。
7. 旧`.work/`は移行せず、Rollback期間後も利用者の明示操作なしには削除しない。
