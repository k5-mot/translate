<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## Verification Scope

- Change: `harden-run-identity-and-reference-registration`
- Platform: Windows
- Python: 3.12
- Re-verified: `2026-09-21` against commit `b881365f13493fea74c76f50fb5150c5a79e1e5e`
- Fixed acceptance input: `inputs/sample.pdf`
- Acceptance collection: `translate-acceptance-sample-pdf`
- Acceptance source ID: `acceptance-sample-pdf`

Credential、文書本文、raw外部応答、Docling job IDおよび画像binaryはEvidenceへ記録しない。

## Capability and Scenario Traceability

| No. | Capability / Requirement | Scenario | Test ID | Result |
| ---: | --- | --- | --- | --- |
| 1 | run-lifecycle / RunをUUIDv7だけで識別する | CLIから新規Runを作成する | `tests/test_run_repository.py::test_create_and_load_run`; `tests/test_run_repository.py::test_uuid7_has_rfc_layout_and_injected_fields`; `tests/test_run_repository.py::test_uuid7_time_range_and_uniqueness` | PASS |
| 2 | run-lifecycle / RunをUUIDv7だけで識別する | Streamlitから新規Runを作成する | `tests/test_run_interoperability.py::test_cli_and_streamlit_resume_each_others_runs` | PASS |
| 3 | run-lifecycle / RunをUUIDv7だけで識別する | UUIDv7ではないRun IDを指定する | `tests/test_run_repository.py::test_uuid4_run_is_excluded_and_rejected_before_path_access`; `tests/test_run_interoperability.py::test_uuid4_run_is_excluded_and_all_public_operations_reject_it` | PASS |
| 4 | run-lifecycle / RunをUUIDv7だけで識別する | UUIDv4 metadataがRun rootに残っている | `tests/test_run_repository.py::test_uuid4_run_is_excluded_and_rejected_before_path_access`; `tests/test_run_interoperability.py::test_uuid4_run_is_excluded_and_all_public_operations_reject_it` | PASS |
| 5 | reference-registration / 大規模PDFを有界な処理単位で登録する | 大規模PDFを新規登録する | `tests/test_qdrant_registration.py::test_pdf_is_stream_hashed_split_once_and_reused_within_page_limit`; `tests/test_qdrant_registration.py::test_registration_batches_are_bounded_and_point_ids_are_deterministic`; 固定PDF受入は下記Acceptance Evidence | PASS |
| 6 | reference-registration / 大規模PDFを有界な処理単位で登録する | 大規模PDFの登録途中で外部Serviceが失敗する | `tests/test_qdrant_registration.py::test_failed_middle_batch_preserves_old_revision_and_resume_converges`; `tests/test_qdrant_registration.py::test_public_cli_resumes_failed_middle_batch_with_same_run_id`; `tests/test_qdrant_registration.py::test_registration_deadline_is_shared_by_extraction_and_qdrant_attempts` | PASS |
| 7 | reference-registration / 大規模PDFを有界な処理単位で登録する | 同じ大規模PDFを再登録する | `tests/test_qdrant_registration.py::test_reregistration_replaces_revision_without_duplicate_chunks`; `tests/test_qdrant_registration.py::test_registration_removes_legacy_and_changed_setting_revisions`; `tests/test_qdrant_registration.py::test_registration_revision_covers_schema_extraction_and_chunk_settings` | PASS |
| 8 | reference-registration / 登録失敗を安全なstage情報で診断できる | Docling抽出が失敗する | `tests/test_failure_contract.py::test_registration_error_exposes_only_allowlisted_stage_and_cause_type`; `tests/test_failure_contract.py::test_registration_stage_failure_is_public_safe_and_resumable[extract]` | PASS |
| 9 | reference-registration / 登録失敗を安全なstage情報で診断できる | Qdrant登録確認が失敗する | `tests/test_qdrant_registration.py::test_verification_partial_failure_never_reports_success`; `tests/test_failure_contract.py::test_registration_stage_failure_is_public_safe_and_resumable[verify]` | PASS |
| 10 | reference-registration / 登録失敗を安全なstage情報で診断できる | Revision置換が失敗する | `tests/test_qdrant_registration.py::test_registration_permanent_stage_failure_is_not_success[delete]`; `tests/test_failure_contract.py::test_registration_stage_failure_is_public_safe_and_resumable[replace]` | PASS |

Capability 2件、Requirement 3件、Scenario 10件をTest IDへ対応付けた。固定PDF受入を含めて未対応Scenarioは0件である。

## Bounded Pipeline Evidence

| Contract | Automated evidence | Result |
| --- | --- | --- |
| 原PDF全量読込み0件 | `test_pdf_is_stream_hashed_split_once_and_reused_within_page_limit` | PASS |
| Docling入力が`PDF_SPLIT_PAGES`以下 | 同Testで23 pageを10、10、3 pageへ分割 | PASS |
| Qdrant write／retrieveが16件以下 | `test_registration_batches_are_bounded_and_point_ids_are_deterministic`で最大16件、外部model request同時数1 | PASS |
| 一つの絶対deadline | `test_registration_deadline_is_shared_by_extraction_and_qdrant_attempts`; `test_docling_and_qdrant_clients_receive_only_remaining_deadline` | PASS |
| Model呼出し同時数1・write境界の有限retry | Workflow `max_concurrency=1`; `test_only_registration_write_boundary_retries_transient_type_error` | PASS |
| 全新Point確認後だけ旧revision削除 | `test_verification_partial_failure_never_reports_success`; `test_failed_middle_batch_preserves_old_revision_and_resume_converges` | PASS |
| Legacy／設定違い／失敗済みrevision cleanup | `test_registration_removes_legacy_and_changed_setting_revisions`; `test_failed_middle_batch_preserves_old_revision_and_resume_converges` | PASS |

## Public Diagnostic Evidence

`failure.json`、Run logおよび公開Errorは`task=REGISTER stage=<stage> cause=<type>`を共有する。`test_registration_stage_failure_is_public_safe_and_resumable`は`extract`、`write`、`verify`、`replace`について非0終了、failed status、成果0件、同じrun IDのResume可能性およびCredential／本文／raw応答／job ID sentinel漏えい0件を検証した。`test_legacy_failure_json_remains_readable`はoptional field追加前のfailure JSONを検証した。

## Quality Gates

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | PASS: error 0件 |
| `uv run ruff format --check .` | PASS: 123 files formatted |
| `uv run ty check` | PASS: error 0件 |
| `uv run pytest` | PASS: 151 passed、1 skipped |
| OpenSpec strict validation | PASS: 本Change 1 passed／0 failed、`verify-sample-pdf-end-to-end` 1 passed／0 failed |

再検証時にも`uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`、`uv run pytest`および本ChangeのOpenSpec strict validationを順次実行し、同じ結果を確認した。

## Fixed PDF Acceptance Evidence

| Field | Result |
| --- | --- |
| Public CLI exit code | PASS: `0` |
| UUIDv7 run ID | PASS: `01a0bf06-60d8-7446-a63c-7f22e8ee698a`（version 7、RFC variant、時刻`2026-09-20T13:34:21.400Z`） |
| Wall time within configured Task deadline | PASS: 公開CLI Resume `1709.313 s` < `21600 s` |
| Registered chunks greater than 0 | PASS: `1079` |
| Maximum Docling part pages | PASS: 36 parts、358 pages、最大10 pages |
| Duplicate Point IDs | PASS: `0`（Point 1079件、chunk 0〜1078） |
| Old or foreign registration revision | PASS: revision 1種類、revision欠落0件、対象source key 1079件、別source key 0件 |
| False success | PASS: 先行するwrite失敗は非0終了・failed Runを保持し、確認済み1079件へのResume完了後だけ`completed`と`registration.json`を確定 |
| Secret leakage | PASS: console、`run.json`、`run.log`および公開warningはstage／cause typeだけを記録し、Credential、本文、raw応答、job ID、画像binary 0件 |

入力は65,475,787 bytes、SHA-256 `0185cd9631266fad92ffcede31a447e51cffa94ee572308310a490dc78a74182`。Runは`status=completed`、`last_task=REGISTER`、`failure.json`なし、`registration.json`は1079件、Run全体は130,994,938 bytesである。Qdrant read-only scrollでPoint 1079件、重複ID 0件、revision 1種類、revision欠落0件、source 1種類を確認した。受入CollectionとRunは自動削除していない。

## Handoff to `verify-sample-pdf-end-to-end`

`verify-sample-pdf-end-to-end`へrun ID `01a0bf06-60d8-7446-a63c-7f22e8ee698a`、wall time `1709.313 s`、登録Chunk 1079件、最大part 10 pages、Qdrant read-only確認結果および安全な診断結果を引き継いだ。Word→PDF変換は製品Scope外であり、利用者側Operationのままとする。

## Verification Report: harden-run-identity-and-reference-registration

| Dimension | Status |
| --- | --- |
| Completeness | 17/17 tasks、3/3 Requirements |
| Correctness | 3/3 Requirements、10/10 Scenariosを実装・Test・受入Evidenceへ対応 |
| Coherence | UUIDv7限定、安全なstage診断、16件の逐次batch、共通deadline、revision置換の設計に準拠 |

- CRITICAL: 0件
- WARNING: 0件
- SUGGESTION: 0件
- 未判定Requirement: 0件

本Changeは全確認を完了し、archive可能である。`verify-sample-pdf-end-to-end`は影響範囲であるRegister gateをPASSへ更新した。Translate、利用者によるPDF変換、Reviewおよび同Change全体のLifecycle gateは本ChangeのScope外として引き続き未完了である。
