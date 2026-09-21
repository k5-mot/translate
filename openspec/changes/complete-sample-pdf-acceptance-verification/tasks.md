<!-- markdownlint-disable MD041 -->

## 3. 実PDFのTranslationとDOCX検査

- [x] 3.1 先行Changeの固定入力identity、Register Run `01a0bf06-60d8-7446-a63c-7f22e8ee698a`、専用Collection、source ID、1079 Point、重複0件をread-onlyで再確認し、他のlocal Model workloadがない状態で公開CLI `translate inputs/sample.pdf --backend llm --output-dir <external-export-dir>`を同時実行数1で開始する。新規UUIDv7 run ID、sanitized command、設定fingerprint、Model、進捗、wall time、retry、warningおよびRun容量を新Changeの`verification.md`へ記録する（Q-FUNC、Q-PERF、Q-COMP、Q-MAIN、運用Evidence）
- [ ] 3.2 Translationが失敗した場合は公開途中DOCXが0件で、`failure.json`がTask、stage、対象IDおよびredact済み原因を持つことを確認し、外部原因の修復後だけ同じrun IDを明示`--resume`して成功済みTask Artifactのhash／mtime不変を記録する。失敗しなかった場合は障害注入を行わず、Resume検査を`NOT EXERCISED`として理由を記録する（Q-REL、Q-SEC、Support Evidence）
- [ ] 3.3 Translation成功時にexit code 0、最終進捗100%、Run status `completed`およびUUIDv7を確認し、export済み日本語DOCXの絶対path、size、SHA-256、ZIP必須entryおよびCRC検査結果を記録する。COVER失敗時にはCOVERからResume可能であり、不完全DOCXが公開されていないことを確認する（Q-FUNC、Q-REL）
- [ ] 3.4 翻訳DOCXの表紙画像が一度だけ存在して対応する第1 page本文がMarkdown／DOCXに重複しないこと、および代表的な見出し、番号、Table、Figure、Caption、URL、保護対象が保持されていることをspot checkし、page／対象IDと判定だけを記録する（Q-FUNC、Q-SEC）
- [ ] 3.5 Translation Runの検索Artifactを検査し、専用Collection名、検索日時、引用元および取得記録が存在すること、Qdrant状態がfingerprintへ含まれないこと、Model／Embedding／page／groupの並行実行が0件であることを確認する（Q-COMP、Q-PERF、Q-MAIN）

## 4. 利用者によるPDF変換と目視比較

- [ ] 4.1 Translation gate合格後、DOCXの絶対path、sizeおよびSHA-256を利用者へ提示してApplyを停止する。ProjectがWord→PDF変換を実行しておらず、製品Code、Dependencyおよび公開interfaceの変換関連差分が0件であることを確認する（Q-USE、Q-PORT、供給Evidence）
- [ ] 4.2 利用者がMicrosoft Word等で変換したPDFの絶対pathを受領し、読取り可能、1 page以上、size 0より大であることを確認して、page数、size、SHA-256、mtimeおよび利用者申告の変換Applicationを`verification.md`へ記録する（Q-FUNC、Q-MAIN、運用Evidence）
- [ ] 4.3 原文PDFと利用者変換PDFの表紙、最初の本文、代表見出し、Table／Figureおよび末尾pageを目視比較し、欠落・重複・改ページ・font・画像差分をTranslation由来または利用者変換由来へ分類して、本文を転記せずpage／対象IDと判定を記録する（Q-FUNC、Q-USE、Q-SEC）

## 5. 実成果物のComparison Review

- [ ] 5.1 Translationと同時実行せず、同じ専用Collection設定で公開CLI `review inputs/sample.pdf <user-converted-pdf> --output <external-report-path>`を同時実行数1で開始し、新規UUIDv7 run ID、sanitized command、両入力hash、進捗、wall time、retry、warningおよびRun容量を記録する（Q-FUNC、Q-PERF、Q-COMP、Q-USE）
- [ ] 5.2 Reviewが失敗した場合は公開途中reportが0件で、branch別failureがTask、対象ID、stageおよびredact済み原因を持つことを確認し、外部原因の修復後だけ同じrun IDを明示`--resume`して成功済みbranch Artifactのhash／mtime不変を記録する。失敗しなかった場合は障害注入を行わず、Resume検査を`NOT EXERCISED`として理由を記録する（Q-REL、Q-SEC、Support Evidence）
- [ ] 5.3 Review成功時にexit code 0、最終進捗100%、Run status `completed`およびUUIDv7を確認し、空でないMarkdown reportの絶対path、size、SHA-256、Finding集計、対応Group、原文hashおよび訳文hashがRun Artifactと一致することを記録する（Q-FUNC、Q-REL、Q-MAIN）
- [ ] 5.4 代表Findingを原文PDF、翻訳DOCXおよび利用者変換PDFと照合し、翻訳由来、利用者変換由来または誤検出へ分類する。対象page／ID、severity、分類および判定根拠だけを`verification.md`へ記録する（Q-FUNC、Q-SEC、保守Evidence）

## 6. 最終品質・Security・Lifecycle・廃止・archive判定

- [ ] 6.1 全受入Operation完了後に`uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest`を実行し、各exit code、Test件数および既知skipを記録する。受入前の結果を最終Evidenceへ流用しない（Q-FUNC、Q-MAIN、保守Evidence）
- [ ] 6.2 Translation／Reviewのconsole、`run.json`、`failure.json`、`run.log`、warningおよび`verification.md`をscanし、Credential、文書全文、raw LLM応答、外部job IDおよび画像binaryの漏えい0件を確認する。検出時は秘密値を出力せず種類と対象Fileだけを記録する（Q-SEC、Support Evidence）
- [ ] 6.3 Translate、User conversion、Review、Lifecycle、SecurityおよびQuality gateを個別にPASS／FAIL／`NOT EXERCISED`で判定し、未判定を0件にする。製品不具合によるFAILは再現条件と影響を記録し、別のOpenSpec修正Changeへ移管して本Changeを未完了のまま保持する（Q-REL、Q-MAIN、保守Evidence）
- [ ] 6.4 Translation／Reviewの正本Run、先行Register Run、外部DOCX／report、利用者変換PDFおよび専用Qdrant Collectionについてidentifier、絶対pathまたはCollection名、sizeおよび所有者を廃止候補一覧へ記録し、自動削除0件と明示export成果物がRun削除対象外であることを確認する（Q-SEC、廃止Evidence）
- [ ] 6.5 `npx --yes @fission-ai/openspec validate complete-sample-pdf-acceptance-verification --strict`と`openspec-verify-change`による最終検証を実施し、未完了Task、PENDING gateおよびCRITICAL findingが0件の場合だけarchive可と記録する。いずれかが残る場合はarchive不可と理由を記録する（Q-FUNC、Q-MAIN、移行・廃止Evidence）
