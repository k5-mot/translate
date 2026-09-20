<!-- markdownlint-disable MD013 MD033 MD041 -->

## Verification Scope

- Change: `verify-sample-pdf-end-to-end`
- Started (UTC): `2026-09-20T11:36:25.298Z`
- Project revision: `62cabfbfbc93fa13abeff75bc0e8bf1ea2616001`（working treeは既存変更を含む）
- Platform: Microsoft Windows 11 Home `10.0.26200`
- Python: `3.12.9`
- Pandoc: `3.11`
- Run root: `C:\Users\merry\Desktop\translate\runs`
- External export root: `C:\Users\merry\Desktop\translate-acceptance-output\verify-sample-pdf-end-to-end`
- Qdrant Collection: `translate-acceptance-sample-pdf`
- Qdrant source ID: `acceptance-sample-pdf`

## Fixed Input Identity

| Field | Expected | Actual | Result |
|---|---:|---:|---|
| Path | `inputs/sample.pdf` | `inputs/sample.pdf` | PASS |
| Size | 65,475,787 bytes | 65,475,787 bytes | PASS |
| Pages | 358 | 358 | PASS |
| SHA-256 | `0185CD9631266FAD92FFCEDE31A447E51CFFA94EE572308310A490DC78A74182` | `0185CD9631266FAD92FFCEDE31A447E51CFFA94EE572308310A490DC78A74182` | PASS |

入力Fileは旧名称から`sample.pdf`へ改名されているが、sizeとSHA-256はProposal作成時の固定入力と一致する。

## Preflight

| Check | Result | Evidence |
|---|---|---|
| Docling Serve | PASS | Sanitized endpoint `http://192.168.1.100:31100`、`GET /health` = 200 |
| OpenAI互換API | PASS | Sanitized endpoint `http://192.168.1.100:31000`、model一覧 = 200、設定済み4 modelを確認 |
| Embedding利用 | PASS | `Qwen/Qwen3-Embedding:0.6B`へ短いprobeを送信し、HTTP 200、vector 1件 |
| LLM利用 | PASS | `google/gemma4:12b`へ短いprobeを送信し、HTTP 200、choice 1件 |
| Qdrant | PASS | Sanitized endpoint `http://192.168.1.100:31101`、Collection一覧取得成功、既存5件 |
| Dedicated Collection isolation | PASS | `translate-acceptance-sample-pdf`は実行前に存在しない |
| Credential presence | PASS | Docling、OpenAI、Qdrantの必要値あり。値自体は記録しない |
| Pandoc | PASS | version 3.11、必要機能は既存preflightで検査 |
| Disk | PASS | C: 空き容量 90,570,461,184 bytes |
| Operational limits | PASS | request timeout 300秒、Task deadline 21,600秒、retry 3回。hard quotaはAPI非公開だが実Embedding／Chat probe成功 |

設定ModelはSTRUCTURE／TRANSLATE／REVIEWとも`google/gemma4:12b`、Embeddingは`Qwen/Qwen3-Embedding:0.6B`。Credential、API key、raw応答本文は記録していない。

## Canonical Fingerprints

| Operation | Fingerprint |
|---|---|
| register | `f9f7e22e68a2715318c56814613e6e5a3369e38761fe034207e64f267b5a9fef` |
| translate | `4b41528d1e8b2af06b8154aeaf111f12f525e36d95888d5d2d7ba20bed366265` |
| review | Phase Bで翻訳PDF受領後に記録 |

## Acceptance Gates

| Gate | Status | Notes |
|---|---|---|
| Preflight | PASS | 固定入力、Service、Model、容量および隔離先を確認 |
| Register | PASS | hardening Change適用後、公開CLI Resumeがexit code 0。1079 Point、重複0件、revision 1種類 |
| Translate | PENDING | 未実行 |
| User conversion | PENDING | DOCX生成後に利用者へ引渡し |
| Review | PENDING | 翻訳PDF受領後に実行 |
| Lifecycle | PENDING | 各Runと必要なResumeを検査 |
| Security | PENDING | Evidence完成時にsecret／本文sentinelを検査 |
| Quality gates | PENDING | 受入検証後に実行 |

## Run Evidence

### Register

- Command: `QDRANT_COLLECTION=translate-acceptance-sample-pdf uv run python cli.py register inputs/sample.pdf --source-id acceptance-sample-pdf`
- Run ID: `b30c9463-811d-4bfa-af6f-82c0ad31cad4`
- Started: `2026-09-20T11:37:22.979581Z`
- Failed: `2026-09-20T12:02:41.659478Z`
- Wall time: `1518.854 s`
- Status: `failed`
- Last task: `REGISTER`
- Failure: `RegistrationError`（page、group、target IDなし）
- Run size: 65,478,044 bytes
- Public output files: 0
- Dedicated Qdrant Collection: 未作成
- Registered Point count: 0
- Input hash／source key／canonical fingerprint: 期待値と一致
- Security: console、`run.json`、`failure.json`、`run.log`にCredentialまたはraw外部応答なし

初回Registerは部分成功を報告せずResume可能なfailed Runを保持したため、atomicityと失敗契約はPASSだった。一方、当時の公開failureは`RegistrationError`だけでextract／write／verifyのstageと安全な下位例外型を保持せず、根本原因を判別できなかった。その時点では固定入力の登録完了条件をFAILとし、製品Codeの診断性改善と大規模PDF登録修正を`harden-run-identity-and-reference-registration`へ移管して本ChangeのApplyを停止した。以下はhardening適用後の再検証結果である。

#### Hardening適用後のRegister再検証

- Command: `QDRANT_COLLECTION=translate-acceptance-sample-pdf uv run python cli.py register inputs/sample.pdf --source-id acceptance-sample-pdf --resume 01a0bf06-60d8-7446-a63c-7f22e8ee698a`
- Run ID: `01a0bf06-60d8-7446-a63c-7f22e8ee698a`（UUIDv7、RFC variant）
- Resume wall time: `1709.313 s`（Task deadline 21,600秒以内）
- Exit code／status／last task: `0`／`completed`／`REGISTER`
- Input: 65,475,787 bytes、358 pages、SHA-256は固定入力と一致
- PDF parts: 36件、最大10 pages、合計358 pages
- Registered chunks: 1079件、chunk 0〜1078
- Qdrant read-only check: Point 1079件、重複ID 0件、revision 1種類、revision欠落0件、対象source key 1079件、別source key 0件
- Run artifacts: `registration.json`あり、`failure.json`なし、Run size 130,994,938 bytes
- Diagnostics: 先行失敗は`task=REGISTER stage=write cause=TypeError`だけを公開し、同じrun IDでResume可能。成功確認前の誤成功0件
- Security: console、`run.json`、`run.log`およびwarningにCredential、原文全文、raw外部応答、Docling job ID、画像binaryなし

登録用Embedding、Docling抽出およびWorkflowのmodel呼出しは同時実行数1で実施した。登録済みの決定的Point IDはResume時にbatch単位で照合し、確認済みbatchのEmbeddingを繰り返さない。Register gateはPASSへ更新し、Translate以降を再開可能と判定する。

### Translate

PENDING

### User conversion

PENDING

### Review

PENDING

## Disposal Candidates

- Run directories: `runs/01a0bf06-60d8-7446-a63c-7f22e8ee698a/`（130,994,938 bytes）。旧UUIDv4失敗RunはUUIDv7切替により製品操作対象外。
- External exports: `C:\Users\merry\Desktop\translate-acceptance-output\verify-sample-pdf-end-to-end`
- Qdrant Collection: `translate-acceptance-sample-pdf`

自動削除は行わない。利用者が対象を確認して明示指示した場合だけ削除する。
