<!-- markdownlint-disable MD013 MD033 MD041 -->

# Verification: recover-review-output-budget

## 実Run

- Input: `inputs/sample3.pdf`
- Run: `01a0d080-2c51-7da5-a91b-700b9a21e7a9`
- Source SHA-256: `5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`
- 明示Resumeで前段のtranslate/Check Artifactを再実行せず、REVIEWから再開した。
- 前回のREVIEW `LLMOutputTruncatedError`を再現せず、Review chunk cacheを逐次生成し、REVIEWを完了した。
- Reviewは約2,100秒、FIXは約1,117秒、VERIFYは約705秒。外部LLM/Embedding呼出しは逐次のみ。
- Qdrantの状態変更はResume拒否判定に使用していない。

## Artifact検査

- `review`, `fix`, `verify`, `cover` Artifactはatomic完了済み。
- `validate/report.json` は `valid: true`。旧checkpointの `structured/assets/...` は `assets/...` へ正規化された。
- Markdownは表紙画像を先頭に一度だけ出力し、本文は改ページ後に開始する。
- DOCXは `outputs/sample3-translated/document.ja.docx` に出力された。
- PDF変換は仕様上ユーザー操作のため、本環境では変換済みPDFがなく、PDF同士のComparison Reviewは未実施。

## Quality gates

- `uv run pytest -q`: 255 passed, 1 skipped
- `uv run pytest -q tests/test_terminal_evidence.py`: 11 passed
- `uv run ruff check translate tests --exclude tests/manual_detached_historical_gate.py`: passed
- `uv run ruff format --check translate tests --exclude tests/manual_detached_historical_gate.py`: passed
- `uv run ty check translate/tasks/review.py translate/tasks/load.py translate/tasks/validate.py translate/workflows/translation.py`: passed
- `openspec validate recover-review-output-budget --strict`: passed

## Security / cleanup

- Failure Evidenceはtask/stage/cause/token usageのみで、prompt・原文・raw responseを含まない。
- `output-truncated`停止時はpublic Review reportを公開せず、private chunk cacheだけを保持する。
- 成功後はprivate chunk cacheを削除し、明示export先以外のサンプルPDF/DOCXをcommit対象にしていない。

## 指摘

- 実装上の指摘は0件。
- **保留（外部操作）**: ユーザーが `outputs/sample3-translated/document.ja.docx` をPDFへ変換した成果物が未提供のため、入力PDFとのComparison Reviewは未実施。これを完了するまでChangeはarchiveしない。
