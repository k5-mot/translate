<!-- markdownlint-disable MD041 -->

## 1. PreflightとEvidence準備

- [x] 1.1 `verification.md`を作成し、OS、Python、Pandoc、Project revision、実行日時、外部Service名、Model名およびCredentialを除いた設定fingerprintを記録できることを確認する（Q-MAIN、ISO/IEC/IEEE 12207運用・Support Evidence）
- [x] 1.2 `inputs/sample.pdf`の存在、65,475,787 bytes、358 pagesおよびSHA-256 `0185CD9631266FAD92FFCEDE31A447E51CFFA94EE572308310A490DC78A74182`を照合し、不一致時はRunを作成せずTaskを未完了にする（Q-FUNC、Q-REL）
- [x] 1.3 Docling、OpenAI互換LLM／Embedding、Qdrant、Pandoc、Credential、disk空き容量および利用上限をread-onlyでpreflightし、必須Serviceが利用不能なら秘密を記録せず停止する（Q-REL、Q-SEC）
- [x] 1.4 利用者指定の絶対export directoryがProjectの`runs/`およびGit管理対象外であることを確認し、検証専用`QDRANT_COLLECTION=translate-acceptance-sample-pdf`とsource ID `acceptance-sample-pdf`をEvidenceへ記録する（Q-SEC、廃止Evidence）

## 2. 実PDFのReference Registration

- [ ] 2.1 検証専用Collection設定で公開CLI `register inputs/sample.pdf --source-id acceptance-sample-pdf`を非対話実行し、exit code 0、run IDおよび1件以上の登録Chunk数を`verification.md`へ記録する（Q-FUNC、Q-USE）
- [ ] 2.2 Register Runの`run.json`、`registration.json`、status、入力hash、source key、warningおよび容量を検査し、原文全文・Credential・画像binaryがmetadataへ含まれず、公開成功前に登録確認が完了していることを確認する（Q-REL、Q-SEC）
- [ ] 2.3 Qdrantをread-only検索して対象source IDのPointだけが検証用Collectionへ存在し、Chunk重複、別source IDおよび既存Collectionへの変更が0件であることを確認する（Q-COMP、Q-REL）
- [ ] 2.4 固定入力のRegisterが約25分後に`RegistrationError`となった原因を特定できるよう、Credential・本文・raw応答を含めずregistration stageと下位例外型を`failure.json`およびRun logへ保持し、extract／write／verify／replaceの障害注入Testで診断可能性を確認する（Q-USE、Q-SEC、Q-MAIN）
- [ ] 2.5 Task 2.4のEvidenceから65 MB・358 page PDFの登録失敗原因を修正し、同じ入力と専用CollectionでTask 2.1〜2.3を再実行して、有限時間内の登録完了、Chunk重複0件および誤成功0件を確認する（Q-FUNC、Q-PERF、Q-REL）

## 3. 実PDFのTranslation

- [ ] 3.1 Registerと同じ検証用Collection設定で公開CLI `translate inputs/sample.pdf --backend llm --output-dir <export-dir>`を非対話実行し、run ID、Task進捗、wall time、retryおよびwarningを記録する（Q-FUNC、Q-PERF、Q-USE）
- [ ] 3.2 Translationが失敗した場合は公開途中DOCXがないこと、`failure.json`がTask・対象・redact済み原因を持つことを確認し、外部原因の修復後だけ同じrun IDを`--resume`して成功済みTask Artifactのhash／mtimeが変わらないことを確認する（Q-REL、Q-SEC、Support Evidence）
- [ ] 3.3 Translation成功時にexit code 0、最終進捗100%、Run status `completed`およびexport済み日本語DOCXの存在を確認し、DOCXのsize、SHA-256、ZIP必須entryおよびCRC検査結果を記録する（Q-FUNC、Q-REL）
- [ ] 3.4 翻訳DOCXの表紙が一度だけ存在して第1 page本文が重複しないこと、代表的な見出し、番号、Table、Figure、Caption、URLおよび保護対象が保持されていることをspot checkし、page／対象IDと判定だけを記録する（Q-FUNC）
- [ ] 3.5 Translation Runの検索Artifactを検査し、検証用Collection名、検索日時、引用元および取得記録が存在し、Qdrantの状態がfingerprintへ含まれていないことを確認する（Q-COMP、Q-MAIN）

## 4. 利用者によるPDF変換と引渡し

- [ ] 4.1 翻訳DOCXの絶対path、sizeおよびSHA-256を利用者へ提示して処理を停止し、ProjectがWord→PDF変換を実行せず、新規Dependencyまたは公開interface変更が0件であることを確認する（Q-PORT、供給Evidence）
- [ ] 4.2 利用者がMicrosoft Word等でPDF化した翻訳成果物の絶対pathを受領し、読取り可能、1 page以上、size 0より大であることを確認して、PDFのpage数、size、SHA-256および変換日時を`verification.md`へ記録する（Q-COMP、Q-MAIN）
- [ ] 4.3 原文PDFと利用者変換PDFの表紙、先頭本文、代表見出しおよび末尾pageを目視比較し、既知の変換差分を製品翻訳由来の差分と分けて記録する（Q-FUNC、Q-USE）

## 5. 実成果物のComparison Review

- [ ] 5.1 Register／Translateと同じ検証用Collection設定で公開CLI `review inputs/sample.pdf <translated-pdf> --output <review.md>`を非対話実行し、run ID、Task進捗、wall time、retryおよびwarningを記録する（Q-FUNC、Q-PERF、Q-USE）
- [ ] 5.2 Reviewが失敗した場合は公開途中reportがないこと、英語側と日本語側の失敗Taskが区別されることを確認し、外部原因の修復後だけ同じrun IDを`--resume`して成功済みbranch Artifactのhash／mtimeが変わらないことを確認する（Q-REL、Q-SEC、Support Evidence）
- [ ] 5.3 Review成功時にexit code 0、最終進捗100%、Run status `completed`、空でないMarkdown report、Finding集計および対応Groupの存在を確認し、原文・訳文hashがRun入力と一致することを記録する（Q-FUNC、Q-COMP）
- [ ] 5.4 Review reportの代表Findingを原文PDF、翻訳DOCXおよび利用者変換PDFと照合し、製品翻訳、PDF変換または誤検出のいずれに由来するかを分類して件数を記録する（Q-FUNC、Q-MAIN）

## 6. 品質GateとLifecycle Evidence

- [ ] 6.1 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest`を実行し、受入検証前後で既存自動Testのerrorが0件であることを記録する（Q-MAIN、Q-PORT）
- [ ] 6.2 `run.json`、`failure.json`、`run.log`、console summaryおよび`verification.md`をsecret／本文sentinelで検査し、Credential、原文全文、LLM応答全文および画像binaryの漏えいが0件であることを確認する（Q-SEC）
- [ ] 6.3 Register、Translate、User conversion、ReviewおよびLifecycle gateを個別にPASS／FAIL判定し、FAILした製品挙動は成功扱いにせず、再現条件、期待結果、実結果および修正確認方法を持つ未完了Taskとして本Fileへ追加する（Q-FUNC、Q-REL、保守Evidence）
- [ ] 6.4 正本Run、外部export成果物および検証用Qdrant Collectionのpath／identifier／sizeを削除候補として一覧化し、利用者の明示確認なしに削除されていないことを確認する（ISO/IEC/IEEE 12207運用・廃止Evidence）
- [ ] 6.5 `npx --yes @fission-ai/openspec validate verify-sample-pdf-end-to-end --type change --strict --json`を実行し、Change error 0件、Evidenceの未判定gate 0件およびArchive可否を`verification.md`へ記録する（Q-MAIN）
