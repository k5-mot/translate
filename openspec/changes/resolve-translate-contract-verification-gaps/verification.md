<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## Capability Traceability

検証日: 2026-09-20

| Capability | Requirement | Scenario数 | 状態 |
| --- | ---: | ---: | --- |
| pdf-translation | 6 | 11 | 全Scenarioに実行Test IDあり |
| comparison-review | 5 | 8 | 全Scenarioに実行Test IDあり |
| reference-registration | 5 | 6 | 全Scenarioに実行Test IDあり |
| markdown-docx-conversion | 4 | 4 | 全Scenarioに実行Test IDあり |
| run-lifecycle | 10 | 19 | 全Scenarioに実行Test IDあり |
| 合計 | 30 | 48 | 未対応0、未実行0 |

以下のTest IDはpytest collection名と一致する。複数Testを記載したScenarioは、公開境界と下位契約を組み合わせて検証する。

| No. | Capability / Requirement | Scenario | Test ID | Result |
| ---: | --- | --- | --- | --- |
| 1 | pdf-translation / PDFを日本語DOCXへ変換できる | PDF翻訳に成功する | `tests/test_pdf_translation_capability.py::test_translation_capability_preserves_contract_with_fix_fallback`; `tests/test_translation_workflow.py::test_translation_branches_skip_and_resume_from_cover` | PASS |
| 2 | pdf-translation / PDFを日本語DOCXへ変換できる | 読取り不能なPDFを拒否する | `tests/test_invalid_pdf_lifecycle.py::test_invalid_pdf_creates_resumable_failed_run_without_output` | PASS |
| 3 | pdf-translation / 文書構造と保護対象を保持する | 複数列と図表を含む文書を変換する | `tests/test_position_layout.py::test_multi_column_marginalia_overlap_and_missing_coordinates_are_stable`; `tests/test_position_tables.py::test_compatible_table_fragments_reconstruct_rows_spans_and_references` | PASS |
| 4 | pdf-translation / 文書構造と保護対象を保持する | 保護対象を維持する | `tests/test_pdf_translation_capability.py::test_translation_capability_preserves_contract_with_fix_fallback` | PASS |
| 5 | pdf-translation / 翻訳Backendを選択できる | LLM Backendを使用する | `tests/test_pdf_translation_capability.py::test_translation_capability_preserves_contract_with_fix_fallback[llm]` | PASS |
| 6 | pdf-translation / 翻訳Backendを選択できる | LibreTranslate Backendを使用する | `tests/test_pdf_translation_capability.py::test_translation_capability_preserves_contract_with_fix_fallback[libretranslate]` | PASS |
| 7 | pdf-translation / 表紙を一度だけ出力する | 表紙を画像として出力する | `tests/test_cover_contract.py::test_cover_manifest_excludes_first_page_from_markdown` | PASS |
| 8 | pdf-translation / 表紙を一度だけ出力する | 表紙生成に失敗する | `tests/test_cover_contract.py::test_cover_failure_preserves_previous_artifact_and_can_resume`; `tests/test_translation_workflow.py::test_translation_branches_skip_and_resume_from_cover` | PASS |
| 9 | pdf-translation / 翻訳結果を検査してから公開する | 修正候補を採用する | `tests/test_pdf_translation_capability.py::test_fix_and_verify_adopt_valid_candidate` | PASS |
| 10 | pdf-translation / 翻訳結果を検査してから公開する | 修正または検証に失敗する | `tests/test_pdf_translation_capability.py::test_translation_capability_preserves_contract_with_fix_fallback`; `tests/test_validate_contract.py::test_skipped_fix_is_preserved_as_warning` | PASS |
| 11 | pdf-translation / 翻訳の機能品質を検証できる | Capability Testを実行する | `tests/test_pdf_translation_capability.py`; `tests/test_cover_contract.py`; `tests/test_invalid_pdf_lifecycle.py` | PASS |
| 12 | comparison-review / 任意の英日PDFを比較できる | 独立した英日PDFを比較する | `tests/test_comparison_capability.py::test_comparison_capability_reports_findings_or_explicit_zero_without_mutation` | PASS |
| 13 | comparison-review / 任意の英日PDFを比較できる | 一方のPDFが無効である | `tests/test_invalid_pdf_lifecycle.py::test_invalid_pdf_creates_resumable_failed_run_without_output[review-unreadable-translation_ja]` | PASS |
| 14 | comparison-review / 文書要素を多対多で対応付ける | 一段落が複数段落に翻訳されている | `tests/test_align_contract.py::test_model_alignment_accepts_valid_multi_block_partition[one-to-many]` | PASS |
| 15 | comparison-review / 文書要素を多対多で対応付ける | 対応する要素が存在しない | `tests/test_align_contract.py::test_one_to_one_and_unmatched_blocks_are_partitioned` | PASS |
| 16 | comparison-review / 問題と根拠をReportする | Findingを集計する | `tests/test_comparison_capability.py::test_comparison_capability_reports_findings_or_explicit_zero_without_mutation[findings]` | PASS |
| 17 | comparison-review / 問題と根拠をReportする | Findingがない | `tests/test_comparison_capability.py::test_comparison_capability_reports_findings_or_explicit_zero_without_mutation[clean]` | PASS |
| 18 | comparison-review / 比較処理をTask単位で再開できる | 日本語側解析の途中で失敗する | `tests/test_comparison_workflow.py::test_comparison_resumes_only_failed_side_task` | PASS |
| 19 | comparison-review / 比較Reviewの機能品質を検証できる | 対応fixtureを検証する | `tests/test_align_contract.py::test_model_alignment_accepts_valid_multi_block_partition`; `tests/test_align_contract.py::test_one_to_one_and_unmatched_blocks_are_partitioned` | PASS |
| 20 | reference-registration / 対応文書を登録できる | 複数形式を登録する | `tests/test_run_input_manifest.py::test_directory_manifest_is_canonical_and_rejects_empty_or_duplicate`; `tests/test_qdrant_registration.py::test_public_cli_directory_reregistration_replaces_across_runs` | PASS |
| 21 | reference-registration / 対応文書を登録できる | 未対応形式だけが指定される | `tests/test_run_input_manifest.py::test_directory_manifest_is_canonical_and_rejects_empty_or_duplicate` | PASS |
| 22 | reference-registration / 登録単位を置換できる | 更新文書を再登録する | `tests/test_qdrant_registration.py::test_public_cli_directory_reregistration_replaces_across_runs`; `tests/test_qdrant_registration.py::test_reregistration_replaces_revision_without_duplicate_chunks` | PASS |
| 23 | reference-registration / 登録障害を失敗として返す | Qdrantへの書込みが回復しない | `tests/test_qdrant_registration.py::test_registration_permanent_stage_failure_is_not_success`; `tests/test_qdrant_registration.py::test_verification_partial_failure_never_reports_success` | PASS |
| 24 | reference-registration / 検索結果を追跡できる | Qdrant変更後にRunをResumeする | `tests/test_qdrant_search.py::test_search_retries_and_records_reproducible_artifact`; `tests/test_run_failure_resume.py::test_external_failure_stops_run_and_resumes_after_qdrant_change` | PASS |
| 25 | reference-registration / 参照登録の品質を検証できる | 登録信頼性Testを実行する | `tests/test_qdrant_registration.py::test_registration_retries_write_verify_and_revision_delete`; `tests/test_qdrant_registration.py::test_registration_permanent_stage_failure_is_not_success` | PASS |
| 26 | markdown-docx-conversion / MarkdownをDOCXへ変換できる | Markdown変換に成功する | `tests/test_output_contract.py::test_real_pandoc_preserves_required_document_structures` | PASS |
| 27 | markdown-docx-conversion / 変換前提条件を検証する | 外部Toolが利用できない | `tests/test_output_contract.py::test_preflight_rejects_before_pandoc_conversion` | PASS |
| 28 | markdown-docx-conversion / 完全なDOCXだけを公開する | 変換処理が途中で失敗する | `tests/test_output_contract.py::test_conversion_and_replace_failure_clean_temporary_and_preserve_output`; `tests/test_output_contract.py::test_docx_failure_preserves_existing_complete_output` | PASS |
| 29 | markdown-docx-conversion / DOCX変換の品質を検証できる | Atomic公開Testを実行する | `tests/test_output_contract.py::test_valid_docx_is_structurally_verified_before_publish`; `tests/test_output_contract.py::test_conversion_and_replace_failure_clean_temporary_and_preserve_output` | PASS |
| 30 | run-lifecycle / 共通Runを永続化する | CLIで作成したRunをStreamlitから列挙する | `tests/test_run_interoperability.py::test_cli_and_streamlit_resume_each_others_runs`; `tests/test_streamlit_ui.py::test_streamlit_lists_downloads_and_deletes_only_after_explicit_confirmation` | PASS |
| 31 | run-lifecycle / 共通Runを永続化する | Run rootが未設定である | `tests/test_settings.py::test_default_runs_dir_is_project_runs` | PASS |
| 32 | run-lifecycle / 新規Runと既存Runを安全に選択する | 対話CLIで同一入力を検出する | `tests/test_cli_process.py::test_posix_pty_selects_candidate_then_answers_yes_or_no` | PASS (POSIX)、理由付きSKIP (Windows) |
| 33 | run-lifecycle / 新規Runと既存Runを安全に選択する | 非対話CLIで同一入力を検出する | `tests/test_cli_process.py::test_noninteractive_cli_always_creates_new_run_for_same_input` | PASS |
| 34 | run-lifecycle / 新規Runと既存Runを安全に選択する | Streamlitで既存Runを選択する | `tests/test_streamlit_ui.py::test_streamlit_apptest_requires_resume_confirmation`; `tests/test_run_interoperability.py::test_cli_and_streamlit_resume_each_others_runs` | PASS |
| 35 | run-lifecycle / Resume互換性をFingerprintで判定する | 互換RunをResumeする | `tests/test_run_interoperability.py::test_cli_and_streamlit_resume_each_others_runs`; `tests/test_fingerprint.py::test_resume_accepts_equal_fingerprint_and_qdrant_change` | PASS |
| 36 | run-lifecycle / Resume互換性をFingerprintで判定する | 設定が異なるRunを指定する | `tests/test_fingerprint.py::test_resume_rejects_changed_settings_with_itemized_reason`; `tests/test_cli_runs.py::test_cli_explicit_resume_compatibility_export_and_delete` | PASS |
| 37 | run-lifecycle / Resume互換性をFingerprintで判定する | Qdrantだけが変更される | `tests/test_run_failure_resume.py::test_external_failure_stops_run_and_resumes_after_qdrant_change`; `tests/test_run_input_manifest.py::test_registration_fingerprint_tracks_manifest_but_not_qdrant` | PASS |
| 38 | run-lifecycle / Task単位のCheckpointを保持する | Task完了後に障害が発生する | `tests/test_translation_workflow.py::test_translation_branches_skip_and_resume_from_cover`; `tests/test_comparison_workflow.py::test_comparison_resumes_only_failed_side_task` | PASS |
| 39 | run-lifecycle / Task単位のCheckpointを保持する | Checkpointを検査する | `tests/test_workflow_state.py::test_translation_checkpoint_contains_paths_not_document_bodies`; `tests/test_workflow_state.py::test_comparison_checkpoint_contains_paths_not_alignment_or_documents` | PASS |
| 40 | run-lifecycle / ArtifactをAtomicに公開する | Artifact書込み中に中断する | `tests/test_atomic_artifacts.py::test_file_publish_preserves_old_complete_artifact_on_failure`; `tests/test_atomic_artifacts.py::test_directory_publish_preserves_old_complete_artifact_on_failure` | PASS |
| 41 | run-lifecycle / 正確な進捗を通知する | 分岐を含む翻訳が完了する | `tests/test_translation_workflow.py::test_translation_branches_skip_and_resume_from_cover` | PASS |
| 42 | run-lifecycle / 正確な進捗を通知する | 比較Reviewが完了する | `tests/test_comparison_workflow.py::test_comparison_resumes_only_failed_side_task` | PASS |
| 43 | run-lifecycle / 外部障害を分類して処理する | Qdrant検索が回復しない | `tests/test_qdrant_search.py::test_search_exhaustion_propagates_and_does_not_publish_artifact`; `tests/test_failure_contract.py::test_failure_record_is_safe_and_removed_after_resume` | PASS |
| 44 | run-lifecycle / 外部障害を分類して処理する | Langfuseが利用できない | `tests/test_langfuse.py::test_each_langfuse_failure_stage_reaches_context_warning_sink_once`; `tests/test_langfuse.py::test_lifecycle_persists_duplicate_langfuse_warning_once` | PASS |
| 45 | run-lifecycle / Runを明示的に削除できる | 停止済みRunを削除する | `tests/test_run_repository.py::test_delete_removes_only_run_and_preserves_export`; `tests/test_streamlit_ui.py::test_streamlit_lists_downloads_and_deletes_only_after_explicit_confirmation` | PASS |
| 46 | run-lifecycle / Runを明示的に削除できる | 実行中Runを削除しようとする | `tests/test_run_repository.py::test_delete_rejects_running_locked_missing_and_outside_runs` | PASS |
| 47 | run-lifecycle / Run情報から秘密と本文を保護する | 外部Serviceが認証Errorを返す | `tests/test_failure_contract.py::test_cli_process_failure_is_safe_and_nonzero`; `tests/test_streamlit_ui.py::test_streamlit_apptest_renders_structured_failure`; `tests/test_redaction.py::test_log_and_error_redact_credentials_bodies_and_binary` | PASS |
| 48 | run-lifecycle / Run Lifecycle品質を検証できる | Lifecycle Test suiteを実行する | `tests/test_run_repository.py`; `tests/test_run_interoperability.py`; `tests/test_failure_contract.py`; `tests/test_streamlit_ui.py` | PASS |

## Quality Gate Evidence

| Gate | Windows 11 / Python 3.12.9 / Pandoc 3.11 | Ubuntu 24.04 WSL / Python 3.12.3 / Pandoc 3.8.3 |
| --- | --- | --- |
| `uv sync --dev`（CIは`--locked`） | PASS、117 resolved／115 installed | PASS、117 resolved／112 installed |
| `uv run ruff check .` | PASS | PASS |
| `uv run ruff format --check .` | PASS、112 files | PASS、112 files |
| `uv run ty check` | PASS | PASS |
| `uv run pytest` | PASS、132 passed／1 POSIX PTY skip | PASS、133 passed |
| 公開process Test | PASS | PASS（実PTYを含む） |

Ubuntu標準のPandoc 3.1.3では要求optionが不足することを実行時に検出したため、CIはWindows／Ubuntu共通で`r-lib/actions/setup-pandoc@v2`を使用し、Pandoc 3.8.3を固定する。両Platformとも同じlocked Dependency、Ruff、Format、ty、pytest Gateを必須実行する。

| OpenSpec strict validation | Result |
| --- | --- |
| `npx --yes @fission-ai/openspec validate establish-translate-ja-contracts --type change --strict --json` | PASS、1/1、issue 0 |
| `npx --yes @fission-ai/openspec validate resolve-translate-contract-verification-gaps --type change --strict --json` | PASS、1/1、`skip_specs`のINFOだけ |
| `git diff --check` | PASS、error 0 |

## OpenSpec Verify Report

| Change | Completeness | Correctness | Coherence |
| --- | --- | --- | --- |
| `establish-translate-ja-contracts` | 41/41 tasks、30 Requirements | 48/48 Scenariosを実行Testへ対応 | Designに沿う |
| `resolve-translate-contract-verification-gaps` | 30/30 tasks、spec deltaは宣言どおりskip | gap Taskと30/48 TraceabilityをTestで検証 | Designのmanifest、failure、redaction、CI、layout判断に沿う |

### CRITICAL

0件。

### WARNING

0件。

### SUGGESTION

0件。

Requirement未対応0件、Scenario未対応0件、Harness名不一致0件である。両Changeともstrict validationに合格し、Archive可能と判定する。
