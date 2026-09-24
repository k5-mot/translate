<!-- markdownlint-disable MD041 -->

## 1. Review chunking and recovery

- [ ] 1.1 page pairsを決定的chunkへ分割し、chunk ID・入力順・budget境界をunit testで検証する
- [ ] 1.2 `output-truncated`を有限retry後に二分splitし、最小chunkでは安全なFailureへ停止するunit testを追加する
- [ ] 1.3 chunkごとのReview Artifactをatomic保存し、Findingを重複なくページ順へ統合するunit testを追加する

## 2. Workflow, Resume and diagnostics

- [ ] 2.1 REVIEW失敗時に部分reportを公開せず、Failure Evidenceが本文・prompt・raw responseを含まないことを確認する（Q-SEC/Q-REL）
- [ ] 2.2 同じRunをREVIEWからResumeし、完了済みtranslate/Check Artifactを再実行せず、未完了chunkだけを処理するLifecycle testを確認する

## 3. sample3 end-to-end acceptance

- [ ] 3.1 Run `01a0d080-2c51-7da5-a91b-700b9a21e7a9`を明示Resumeし、REVIEWを完了させる（Q-FUNC/Q-REC）
- [ ] 3.2 translate PDFと入力PDFをComparison Reviewし、Finding report、保護対象、表紙一重出力、Markdown/DOCX成果物を検査する
- [ ] 3.3 source hash、checkpoint再利用、atomic cleanup、sequential call、Qdrant変更許容、Security sentinel scanをverification.mdへ記録する

## 4. Quality gates and archive

- [ ] 4.1 `uv run pytest -q`、Ruff、format、strict type validationを実行し、結果をEvidenceへ記録する
- [ ] 4.2 `openspec validate recover-review-output-budget --strict`を実行する
- [ ] 4.3 verification.mdの指摘を0件にし、Tasksを完了、Changeをarchive、Main Specを同期する

