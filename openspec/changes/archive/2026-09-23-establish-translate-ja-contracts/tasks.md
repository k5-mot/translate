<!-- markdownlint-disable MD041 -->

## 1. 品質基盤と契約Model

- [x] 1.1 `pyproject.toml`で`langchain-core`と`langsmith`を直接Dependency化し、`langchain`/`langgraph`へ`<2`を設定して未使用の`openai`を削除し、`uv lock`と全Runtime importのsmoke testが成功することを確認する
- [x] 1.2 Ruffの個別`DOC201/DOC202/DOC501`選択と包括ignoreの矛盾を解消し、`.agents/`をProject所有codeの標準検査対象から除外して、`uv run ruff check .`と`uv run ruff format --check .`がerror 0件になることを確認する（Q-MAIN）
- [x] 1.3 `tests/`へUnit、Integration、CLI、Streamlit browser testの基盤と外部Service test doubleを追加し、最小smoke testが`uv run pytest`で成功することを確認する（Q-FUNC、Q-MAIN）
- [x] 1.4 `Finding`と関連する修正・検証状態を単一のInternal Document schemaへ統一し、旧形式の読込み拒否とCHECK/REVIEW/REPORT間のround-trip testが成功することを確認する
- [x] 1.5 `README.md`、`.env.sample`および`.gitignore`を現行の公開操作、`TRANSLATE_RUNS_DIR`、外部Service設定、`runs/`生成物および正式用語へ揃え、相対linkと設定名の文書検査を行う（ISO/IEC/IEEE 12207移行・運用Evidence）

## 2. 共通Run Repository

- [x] 2.1 設定Modelへ`TRANSLATE_RUNS_DIR`とretry/timeout/deadlineを追加し、未設定時にProject直下`runs/`へ解決され、Windows/POSIX path fixtureが成功することを確認する（Q-PORT）
- [x] 2.2 UUID4 run IDと`inputs/`、`outputs/`、`.workspace/`を持つRun作成・読込みModelを実装し、`run.json`がstatus、入力hash、設定snapshot、fingerprint、最後のTaskだけを保持することをTestする
- [x] 2.3 Run root直下の`run.json`を走査する一覧・同一入力SHA-256検索を実装し、破損Runを警告付きで隔離しながら更新日時順の候補を返すことをTestする（Q-USE）
- [x] 2.4 入力、Backend、Model、Rule、用語集、Template、split、Docling/OCR、Context/Token設定のcanonical fingerprintと項目差分を実装し、CredentialとQdrant状態を除外するUnit Testを通す
- [x] 2.5 fingerprint一致時だけResumeを許可する互換性判定を実装し、各設定差分で拒否理由が表示され、Qdrantだけの変更では許可されることをTestする（Q-REL）
- [x] 2.6 Run単位lock、root containmentおよび安全な削除を実装し、実行中Run、存在しないRun、symlink/junctionおよびroot外pathの削除を拒否し、外部exportを保持するTestを通す（Q-SEC、廃止Evidence）

## 3. Atomic ArtifactとCheckpoint

- [x] 3.1 Text、JSON、binaryおよびDirectory Artifact用のatomic publishを共通workspace機能へ追加し、書込み・flush・検証・replace各地点の障害注入で旧完全版または未作成状態だけが残ることをTestする（Q-REL）
- [x] 3.2 SPLITからREPORTまでの全Taskと各Adapterの直接書込みをatomic publishへ移行し、生成Artifactの形式検証後だけ最終pathが存在することをTask別Testで確認する
- [x] 3.3 翻訳Workflow stateをArtifact path、status、warning、現在位置および進捗だけへ変更し、SQLite checkpointに文書本文、Finding本文または画像binaryが存在しないことをTestする（Q-PERF）
- [x] 3.4 比較Workflow stateを英日それぞれのArtifact pathと小さいmetadataだけへ変更し、Alignmentおよび文書本体がcheckpointへ保存されないことをTestする（Q-PERF）

## 4. Workflow、Resumeおよび進捗

- [x] 4.1 翻訳Workflowの各Taskを独立nodeとしてArtifact pathで接続し、Backend分岐、FindingなしのFIX/VERIFY skip、COVER合流および失敗TaskからのResumeをIntegration Testで確認する
- [x] 4.2 比較Workflowの英日両branchをSPLIT、DOCLING、UNPACK、MERGE、POSITION、NORMALIZE、LOADの独立nodeへ分解し、両LOAD後のALIGN joinと片側失敗からのTask単位ResumeをTestする
- [x] 4.3 翻訳17 Task、比較18 Taskの`current/total`とskip eventを共通進捗層で生成し、分岐、失敗、Resumeの各caseで単調増加し、正常終了時に100%になることをTestする（Q-USE）
- [x] 4.4 各Taskの`run()`と`cli.py`/`main.py`の合計時間を`time.perf_counter()`で計測し、Task/page/group識別子を含む出力をTestし、計測専用stateまたはFileが増えていないことを確認する

## 5. PDF翻訳と比較品質

- [x] 5.1 COVERが画像と除外page manifestをatomicに生成するよう変更し、MARKDOWNが対象page本文を除外して表紙を一度だけ出力し、COVER失敗時に成果物を公開せずResume可能に停止するTestを通す
- [x] 5.2 POSITIONへmulti-column、欄外、重なり、座標なし要素の安定順、paragraph/code fragment結合を実装し、layout fixtureごとの期待順と補正reportをTestする（Q-FUNC）
- [x] 5.3 POSITIONへtable fragmentのrow/column/spanおよび参照再構成を追加し、結合可能fixtureと曖昧な非結合fixtureで構造・警告が期待どおりになることをTestする
- [x] 5.4 VALIDATEがFIX/VERIFYの`skipped`を警告として保持し、訳文欠落や参照不整合をErrorにするよう変更して、警告通過とError停止のTestを通す
- [x] 5.5 ALIGNの1対1、1対多、多対1、`source_only`、`target_only` fixtureを整備し、全IDが重複なく一度だけ分類されることをTestする（Q-FUNC）
- [x] 5.6 MARKDOWNとDOCXの構造保持およびatomic公開をfixtureで検証し、Pandoc欠落、変換失敗、不正DOCXで既存完全版を保持するTestを通す（Q-REL）

## 6. 外部Serviceと観測

- [x] 6.1 Docling、LLMおよびLibreTranslate AdapterへNetwork/408/429/5xx限定の指数backoff+jitter、既定3回、設定可能timeout/deadlineを追加し、恒久4xx即時失敗とretry exhaustionからのResumeをTestする
- [x] 6.2 Qdrant検索の例外握り潰しを廃止して同じ有限retry後にTaskを失敗させ、query、Collection、検索日時、引用元および結果をTask Artifactへ保存するTestを通す
- [x] 6.3 Qdrant登録を対応形式の収集、revision置換、登録確認および部分失敗時の失敗報告へ揃え、再登録で重複Chunk 0件、恒久障害で誤成功0件になることをTestする（Q-REL）
- [x] 6.4 Workflow、TaskおよびLLM呼出しをLangfuse traceへ接続し、成功・失敗時にflushしつつ、観測障害では秘密を含まない警告だけを残して本処理を継続するTestを通す
- [x] 6.5 Error、log、run metadata、checkpointおよびtraceのredactionを実装し、Credential、本文全文および画像binaryが出力されないSecurity Testを通す（Q-SEC）

## 7. CLIとStreamlit

- [x] 7.1 CLIへ`--resume <run-id>`、Run一覧、成果物exportおよび確認付きRun削除を追加し、明示Resume、新規Run、互換性拒否およびexport保持をCLI Testで確認する
- [x] 7.2 対話CLIの同一入力候補提示と`y/n`確認を追加し、`y`で互換Run、`n`で新規Run、複数候補選択が動作することをPTY Testで確認する（Q-USE）
- [x] 7.3 非対話CLIでは同一入力があっても質問せず新規Runを作り、明示`--resume`だけが再開することをredirect/CI相当のTestで確認する
- [x] 7.4 StreamlitへRun一覧、状態・互換性表示、選択後の確認、Resume、Download、exportおよび確認付き削除を追加し、rerunだけでは処理開始・削除されないことをbrowser Testで確認する
- [x] 7.5 Streamlitのupload型を`UploadedFile`へ変更し、Backend選択をsegmented controlへ変更して、`main()`/描画関数を維持したまま`streamlit run main.py`の起動Testを通す
- [x] 7.6 CLI作成RunをStreamlitでResumeし、Streamlit作成RunをCLIでResumeする相互運用Testを実施して、同じArtifactと最終成果物へ到達することを確認する（Q-COMP）

## 8. Capability検証と移行Evidence

- [x] 8.1 LLM/LibreTranslate両Backendについて、表紙、構造、保護対象、検査、FIX/VERIFY fallbackを含むPDF翻訳Scenarioを自動化し、全caseが成功することを確認する（Q-FUNC）
- [x] 8.2 独立英日PDFの比較、Finding集計、Finding 0件および入力非変更をEnd-to-End Testし、comparison-reviewの全Scenarioが成功することを確認する（Q-FUNC）
- [x] 8.3 Run Artifact書込み中断、各外部Service障害、Task途中Resume、進捗、Qdrant変更後Resumeおよび削除境界を障害注入Testし、部分Artifact・誤Resume・root外削除を0件にする（Q-REL、Q-SEC）
- [x] 8.4 `uv sync --dev`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`、`uv run pytest`を実行し、すべて成功したlogをQ-MAINの検証Evidenceとして残す
- [x] 8.5 新Run layout、旧`.work/`非互換、Rollback、容量監視、Support情報および明示削除を運用文書へ反映し、ISO/IEC/IEEE 12207の移行・運用・保守・廃止checklistをReviewする
