<!-- markdownlint-disable MD013 MD041 -->

# 関数説明・既存依存再利用・再開正本の追加監査

## 範囲と判定

2026-09-25の作業ツリーをASTで監査した。追跡Python 90 files、def/async def（method・入れ子を含む）912件、docstringなし474件。docstringありも内容の十分性を別途確認する。以下は欠落候補の全件一覧であり、コメントの代替可否を未審査のまま合格にしない。

対象はgit ls-filesのPython。未追跡の診断probe、.agents、.venv、生成成果物はこの集計に含めない。通常ASTのlambdaと文字列内Pythonも別枠。別の読取り監査では、修正前の908関数中481件にdocstringがなく、うち3件に先頭bodyコメントがあった。lambda145件、実行用文字列内の説明なしdef 3件も確認した。今回のDOCX修正で既存7関数に説明を追加し、新規Test helper/関数には説明を付けたため、以前の集計と区別する。

最新利用者要求③-1に従い、通常/非公開/入れ子/特殊method/Test関数を対象に目的を説明する。名前の言換えだけの説明で件数を埋めない。lambdaのためだけの無意味なdef化は行わず、複雑なlambdaと実行文字列は個別点検する。CODING_RULESへの明文化と再発防止検査は未実装。

## docstring欠落候補の全一覧

### cli.py

- `31:_progress`
- `35:_is_interactive`
- `39:_candidate_resume`
- `79:_prepare`

### main.py

- `35:_save`
- `42:_progress_callback`
- `46:_progress_callback.callback`
- `53:_resume_choice`
- `80:_execute_ui`
- `151:_downloads`
- `161:_translation`
- `188:_review`
- `209:_register`
- `247:_convert`
- `268:_run_management`

### tests/conftest.py

- `19:FakeHttpResponse.__init__`
- `47:settings_factory.create`

### tests/test_adapter_retry.py

- `22:_response`
- `39:test_libretranslate_retries_5xx_and_stops_on_permanent_4xx.post`
- `54:test_libretranslate_retries_5xx_and_stops_on_permanent_4xx.permanent`
- `72:test_docling_retries_submit_and_uses_configured_timeout.post`
- `78:test_docling_retries_submit_and_uses_configured_timeout.get`
- `117:test_llm_model_applies_zero_budget_only_when_thinking_is_disabled.client`
- `147:test_llm_schema_mode_binds_strict_response_format_without_prompt_duplication.Client.bind`
- `151:test_llm_schema_mode_binds_strict_response_format_without_prompt_duplication.Client.invoke`
- `155:test_llm_schema_mode_binds_strict_response_format_without_prompt_duplication.model`
- `163:test_llm_schema_mode_binds_strict_response_format_without_prompt_duplication.format_instructions`
- `215:test_llm_schema_mode_preserves_retry_and_parse_contracts.Client.bind`
- `220:test_llm_schema_mode_preserves_retry_and_parse_contracts.Client.invoke`
- `257:test_llm_schema_mode_classifies_length_before_parse.Client.bind`
- `260:test_llm_schema_mode_classifies_length_before_parse.Client.invoke`
- `317:test_llm_schema_mode_normalizes_sdk_length_error_without_raw_completion.Client.bind`
- `320:test_llm_schema_mode_normalizes_sdk_length_error_without_raw_completion.Client.invoke`
- `360:test_llm_schema_mode_does_not_retry_permanent_400.Client.bind`
- `363:test_llm_schema_mode_does_not_retry_permanent_400.Client.invoke`
- `399:test_llm_context_exceeded_is_safe_non_retryable_diagnostic.Client.bind`
- `402:test_llm_context_exceeded_is_safe_non_retryable_diagnostic.Client.invoke`
- `499:test_llm_retries_network_errors_and_exhausts_at_configured_limit.Client.invoke`
- `526:test_llm_retries_network_errors_and_exhausts_at_configured_limit.FailingClient.invoke`
- `560:test_llm_retries_provider_timeout_by_type_name.Client.invoke`
- `594:test_llm_retries_boundary_type_and_parse_errors_without_leaking_content.BrokenResponse.content`
- `598:test_llm_retries_boundary_type_and_parse_errors_without_leaking_content.Client.invoke`
- `630:test_llm_retries_boundary_type_and_parse_errors_without_leaking_content.MalformedClient.invoke`
- `663:test_llm_does_not_retry_permanent_or_outside_boundary_errors.Client.invoke`
- `690:test_llm_does_not_retry_permanent_or_outside_boundary_errors.invalid_model`
- `710:test_llm_does_not_retry_permanent_or_outside_boundary_errors.invalid_prompt`
- `773:test_llm_classifies_length_before_parse_without_retry_or_leak.Client.invoke`
- `816:test_llm_token_usage_rejects_non_integer_or_negative_values.Client.invoke`

### tests/test_align_contract.py

- `19:_document`
- `38:_assert_partition`

### tests/test_atomic_artifacts.py

- `21:_publish_file`
- `43:test_file_publish_preserves_old_complete_artifact_on_failure.fail`
- `69:test_directory_publish_preserves_old_complete_artifact_on_failure.build`
- `72:test_directory_publish_preserves_old_complete_artifact_on_failure.validate`
- `75:test_directory_publish_preserves_old_complete_artifact_on_failure.fail`

### tests/test_cli_process.py

- `17:_command`
- `28:_environment`
- `34:_run_noninteractive`
- `48:_run_ids`
- `93:test_posix_pty_selects_candidate_then_answers_yes_or_no.interact`

### tests/test_cli_runs.py

- `24:_templates`
- `35:_fake_translation`

### tests/test_comparison_capability.py

- `22:_document`

### tests/test_comparison_workflow.py

- `68:test_comparison_split_failure_defaults_to_its_input_role.fake_split`
- `115:test_comparison_resumes_only_failed_side_task.fake_observe`
- `125:test_comparison_resumes_only_failed_side_task.side`
- `128:test_comparison_resumes_only_failed_side_task.fake_split`
- `138:test_comparison_resumes_only_failed_side_task.fake_docling`
- `147:test_comparison_resumes_only_failed_side_task.fake_unpack`
- `154:test_comparison_resumes_only_failed_side_task.passthrough`
- `155:test_comparison_resumes_only_failed_side_task.passthrough.task`
- `169:test_comparison_resumes_only_failed_side_task.fake_merge`
- `176:test_comparison_resumes_only_failed_side_task.fake_load`
- `185:test_comparison_resumes_only_failed_side_task.fake_align`
- `192:test_comparison_resumes_only_failed_side_task.fake_check`
- `198:test_comparison_resumes_only_failed_side_task.fake_review`
- `202:test_comparison_resumes_only_failed_side_task.fake_report`

### tests/test_cover_contract.py

- `17:_fake_render`
- `76:test_cover_failure_preserves_previous_artifact_and_can_resume.fail`

### tests/test_failure_contract.py

- `42:_templates`
- `77:test_failure_record_is_safe_and_removed_after_resume.workflow`
- `166:test_cli_failure_boundary_does_not_render_traceback.fail`
- `286:test_output_truncation_is_safe_atomic_and_backward_compatible.workflow`
- `359:test_context_exceeded_diagnostics_are_safe_and_resumable.workflow`
- `413:test_structure_diagnostics_reach_failure_log_and_public_error.workflow`
- `470:test_failure_diagnostics_reject_values_outside_allowlist.workflow`
- `521:test_registration_stage_failure_is_public_safe_and_resumable.fail_registration`

### tests/test_fingerprint.py

- `26:_fingerprint`

### tests/test_historical_resume.py

- `82:_reject_link`
- `137:_verify_database`
- `190:_table_counts`
- `202:_workflow_config`
- `241:_ensure_pending_structure`
- `247:_page`
- `337:_offline_model.handler`
- `380:_offline_model.BoundModel.__init__`
- `383:_offline_model.BoundModel.invoke`
- `390:_offline_model.Model.bind`
- `397:_render_page`
- `443:historical_settings`
- `498:_set_outside`
- `502:_set_unknown_body`
- `506:_set_binary`
- `557:test_historical_clone_removes_partial_copy_on_link_or_copy_failure.fail_copy`
- `598:test_fresh_full_document_reuses_page_checkpoint_and_sdk_once.model_factory`
- `605:test_fresh_full_document_reuses_page_checkpoint_and_sdk_once.parse_once`
- `658:test_historical_resume_crosses_full_document_and_wrappers_once.model_factory`
- `665:test_historical_resume_crosses_full_document_and_wrappers_once.parse_once`
- `745:test_public_lifecycle_reaches_post_structure_boundary_without_typeerror.run_to_boundary`

### tests/test_invalid_pdf_lifecycle.py

- `26:_templates`
- `35:_valid_pdf`
- `94:test_invalid_pdf_creates_resumable_failed_run_without_output.injected_validate`

### tests/test_langfuse.py

- `56:_offline_chat_model.handler`
- `123:test_workflow_flushes_after_success_and_failure.fake_observe`
- `128:test_workflow_flushes_after_success_and_failure.fake_run`
- `165:test_llm_call_is_observed_without_sending_prompt_body.fake_observe`
- `170:test_llm_call_is_observed_without_sending_prompt_body.Client.invoke`
- `240:test_actual_openai_response_stack_distinguishes_observation_context.Observation.update`
- `243:test_actual_openai_response_stack_distinguishes_observation_context.Observation.end`
- `249:test_actual_openai_response_stack_distinguishes_observation_context.Manager.__enter__`
- `253:test_actual_openai_response_stack_distinguishes_observation_context.Manager.__exit__`
- `258:test_actual_openai_response_stack_distinguishes_observation_context.LangfuseClient.start_as_current_observation`
- `261:test_actual_openai_response_stack_distinguishes_observation_context.LangfuseClient.start_observation`
- `324:test_translation_workflow_keeps_model_outside_real_langfuse_current_span.model_run`
- `434:test_pending_structure_resume_crosses_real_graph_and_sdk_once.handler`
- `478:test_pending_structure_resume_crosses_real_graph_and_sdk_once.BoundModelProbe.__init__`
- `481:test_pending_structure_resume_crosses_real_graph_and_sdk_once.BoundModelProbe.invoke`
- `490:test_pending_structure_resume_crosses_real_graph_and_sdk_once.ModelProbe.bind`
- `494:test_pending_structure_resume_crosses_real_graph_and_sdk_once.model_factory`
- `500:test_pending_structure_resume_crosses_real_graph_and_sdk_once.parse_once`
- `504:test_pending_structure_resume_crosses_real_graph_and_sdk_once.render_page`
- `510:test_pending_structure_resume_crosses_real_graph_and_sdk_once.unexpected`
- `670:test_detached_child_failure_resets_parent_before_next_root.Observation.__init__`
- `673:test_detached_child_failure_resets_parent_before_next_root.Observation.start_observation`
- `680:test_detached_child_failure_resets_parent_before_next_root.Observation.update`
- `684:test_detached_child_failure_resets_parent_before_next_root.Observation.end`
- `690:test_detached_child_failure_resets_parent_before_next_root.Client.start_observation`
- `702:test_detached_child_failure_resets_parent_before_next_root.business_failure`
- `754:test_llm_detached_finish_failure_keeps_success_without_retry_or_leak.Observation.end`
- `758:test_llm_detached_finish_failure_keeps_success_without_retry_or_leak.Observation.update`
- `762:test_llm_detached_finish_failure_keeps_success_without_retry_or_leak.LangfuseClient.start_observation`
- `766:test_llm_detached_finish_failure_keeps_success_without_retry_or_leak.LangfuseClient.start_as_current_observation`
- `772:test_llm_detached_finish_failure_keeps_success_without_retry_or_leak.ModelClient.bind`
- `775:test_llm_detached_finish_failure_keeps_success_without_retry_or_leak.ModelClient.invoke`
- `818:test_detached_observation_boundary_failures_preserve_success.Observation.end`
- `822:test_detached_observation_boundary_failures_preserve_success.Observation.update`
- `826:test_detached_observation_boundary_failures_preserve_success.Client.start_observation`
- `863:test_detached_update_failure_preserves_business_error.Observation.update`
- `866:test_detached_update_failure_preserves_business_error.Observation.end`
- `870:test_detached_update_failure_preserves_business_error.Client.start_observation`
- `880:test_detached_update_failure_preserves_business_error.processing_failure`
- `907:test_observation_and_flush_failures_warn_without_blocking_or_leaking.Client.start_as_current_observation`
- `911:test_observation_and_flush_failures_warn_without_blocking_or_leaking.Client.flush`
- `944:test_each_langfuse_failure_stage_reaches_context_warning_sink_once.Observation.update`
- `949:test_each_langfuse_failure_stage_reaches_context_warning_sink_once.Manager.__enter__`
- `952:test_each_langfuse_failure_stage_reaches_context_warning_sink_once.Manager.__exit__`
- `957:test_each_langfuse_failure_stage_reaches_context_warning_sink_once.Client.start_as_current_observation`
- `960:test_each_langfuse_failure_stage_reaches_context_warning_sink_once.Client.flush`
- `971:test_each_langfuse_failure_stage_reaches_context_warning_sink_once.processing_failure`
- `997:test_initialization_and_warning_sink_failures_are_non_blocking.client_failure`
- `1001:test_initialization_and_warning_sink_failures_are_non_blocking.sink_failure`
- `1048:test_lifecycle_persists_duplicate_langfuse_warning_once.Client.start_as_current_observation`
- `1054:test_lifecycle_persists_duplicate_langfuse_warning_once.workflow`

### tests/test_pdf_translation_capability.py

- `140:test_translation_capability_preserves_contract_with_fix_fallback.render_page`
- `165:test_translation_capability_preserves_contract_with_fix_fallback.translate_response`
- `211:test_translation_capability_preserves_contract_with_fix_fallback.service_failure`

### tests/test_position_layout.py

- `14:_item`

### tests/test_position_tables.py

- `14:_table`
- `49:_run`

### tests/test_qdrant_registration.py

- `45:_FakeClient.__init__`
- `51:_FakeClient.reset`
- `63:_FakeClient.collection_exists`
- `66:_FakeClient.retrieve`
- `77:_FakeClient.delete`
- `97:_FakeStore.__init__`
- `100:_FakeStore.add_documents`
- `114:_FakeStore.from_documents`
- `132:_qdrant_double`
- `366:test_registration_batches_are_bounded_and_point_ids_are_deterministic.ManyChunks.__init__`
- `369:test_registration_batches_are_bounded_and_point_ids_are_deterministic.ManyChunks.split_text`
- `420:test_pdf_is_stream_hashed_split_once_and_reused_within_page_limit.split_spy`
- `425:test_pdf_is_stream_hashed_split_once_and_reused_within_page_limit.reject_original_read_bytes`
- `430:test_pdf_is_stream_hashed_split_once_and_reused_within_page_limit.extract_spy`
- `457:test_failed_middle_batch_preserves_old_revision_and_resume_converges.ManyChunks.__init__`
- `460:test_failed_middle_batch_preserves_old_revision_and_resume_converges.ManyChunks.split_text`
- `515:test_registration_deadline_is_shared_by_extraction_and_qdrant_attempts.ExpiringSplitter.__init__`
- `518:test_registration_deadline_is_shared_by_extraction_and_qdrant_attempts.ExpiringSplitter.split_text`
- `555:test_docling_and_qdrant_clients_receive_only_remaining_deadline.FakeDocling.__init__`
- `559:test_docling_and_qdrant_clients_receive_only_remaining_deadline.FakeDocling.convert`
- `592:test_only_registration_write_boundary_retries_transient_type_error.flaky`
- `600:test_only_registration_write_boundary_retries_transient_type_error.programming_error`
- `626:test_public_cli_resumes_failed_middle_batch_with_same_run_id.ManyChunks.__init__`
- `629:test_public_cli_resumes_failed_middle_batch_with_same_run_id.ManyChunks.split_text`

### tests/test_qdrant_search.py

- `30:test_search_retries_and_records_reproducible_artifact.Store.similarity_search_with_score`
- `90:test_search_exhaustion_propagates_and_does_not_publish_artifact.Store.similarity_search_with_score`

### tests/test_redaction.py

- `24:_Observation.update`
- `29:_Manager.__enter__`
- `32:_Manager.__exit__`
- `115:test_trace_metadata_is_redacted_before_sdk_call.Client.start_as_current_observation`

### tests/test_review_output_recovery.py

- `22:_pairs`
- `29:_document`
- `51:_finding`
- `55:_truncated`
- `71:_timed_out`
- `75:_context_exceeded`
- `84:test_review_chunks_are_deterministic_and_budget_bounded`
- `97:test_review_partitions_findings_once_across_chunks`
- `116:test_review_context_exceeded_splits_without_public_report`
- `122:test_review_context_exceeded_splits_without_public_report.fake_structured`
- `143:test_review_truncation_retries_then_splits`
- `148:test_review_truncation_retries_then_splits.fake_search`
- `151:test_review_truncation_retries_then_splits.fake_structured`
- `178:test_review_timeout_splits_without_publishing_partial_report`
- `185:test_review_timeout_splits_without_publishing_partial_report.fake_structured`
- `206:test_review_timeout_at_minimum_chunk_stops_without_public_report`
- `228:test_review_cache_reuses_completed_chunk_without_public_partial_artifact`
- `236:test_review_cache_reuses_completed_chunk_without_public_partial_artifact.fake_structured`

### tests/test_run_failure_resume.py

- `22:_templates`
- `54:test_external_failure_stops_run_and_resumes_after_qdrant_change.workflow`

### tests/test_run_input_manifest.py

- `29:_templates`
- `156:test_copy_hashes_in_chunks_without_read_bytes.guarded`

### tests/test_run_interoperability.py

- `25:_templates`
- `49:test_cli_and_streamlit_resume_each_others_runs.fake_translation`
- `138:test_cli_and_streamlit_build_the_same_registration_source_key.fake_register`
- `192:test_custom_reference_docx_is_shared_between_cli_and_streamlit_runs.fake_docx`

### tests/test_streamlit_process.py

- `18:_free_port`

### tests/test_streamlit_ui.py

- `20:_completed_run`
- `92:test_streamlit_registration_requires_confirmed_source_id.Upload.getvalue`
- `105:test_streamlit_registration_requires_confirmed_source_id.capture`
- `143:test_streamlit_failure_boundary_displays_only_safe_run_context.fail`

### tests/test_structure_checkpoints.py

- `21:_document`
- `40:_render`
- `45:_page_from_user`
- `119:test_structure_resume_reuses_only_completed_page_checkpoints.respond`
- `167:test_structure_reprocesses_incompatible_or_corrupt_page_checkpoint.respond`
- `209:test_structure_old_run_without_page_progress_starts_normally.respond`

### tests/test_structure_diagnostics.py

- `21:_document`
- `39:_render`
- `45:_source`
- `81:test_structure_request_preserves_typed_arguments_and_retry_boundary.invoke`
- `142:test_structure_leaves_small_image_and_cover_unchanged.render_cover`
- `161:test_structure_uses_text_when_image_cannot_be_prepared.fail_render`
- `166:test_structure_uses_text_when_image_cannot_be_prepared.respond`
- `190:test_structure_falls_back_to_text_after_finite_vision_failure.respond`
- `235:test_structure_final_llm_failure_has_safe_page_context_and_no_artifact.fail`
- `274:test_structure_does_not_hide_task_programming_type_error_with_fallback.fail`
- `305:test_structure_uses_text_only_after_vision_output_truncation.respond`
- `344:test_structure_stops_when_vision_and_text_both_truncate.fail`
- `390:test_structure_recovers_text_truncation_with_prompt_mode.respond`

### tests/test_task_artifacts.py

- `46:test_task_directory_is_not_replaced_before_validation.fail`

### tests/test_terminal_evidence.py

- `39:_evidence`
- `48:test_evidence_io_holds_exactly_one_lock`
- `60:test_evidence_io_holds_exactly_one_lock.tracked_lock`
- `71:test_evidence_io_holds_exactly_one_lock.read`
- `75:test_evidence_io_holds_exactly_one_lock.write`
- `89:test_evidence_corruption_is_not_success`
- `97:test_evidence_write_error_releases_lock_and_preserves_previous`
- `105:test_evidence_write_error_releases_lock_and_preserves_previous.fail`
- `116:test_evidence_lock_uses_bounded_existing_library`
- `122:test_evidence_lock_uses_bounded_existing_library.capture`
- `132:test_evidence_terminal_survives_stale_running_update`
- `144:test_evidence_permission_failure_is_not_hidden`
- `151:test_evidence_permission_failure_is_not_hidden.fail`
- `199:test_terminal_evidence_forbids_arbitrary_fields_and_unsafe_names`
- `213:test_evidence_store_rejects_temp_root_and_invalid_terminal`
- `232:test_progress_and_failure_are_reduced_to_safe_values`
- `271:test_external_call_counter_restores_nested_and_failed_contexts.fail_in_context`
- `296:test_evidence_literal_narrowing_keeps_allowlist`
- `306:test_evidence_and_counts_contain_no_sensitive_or_external_values`
- `333:test_cleanup_detached_temp_preserves_external_evidence`
- `348:test_detached_watchdog_collects_completion_without_stdout`
- `377:test_detached_watchdog_times_out_without_restart`
- `400:test_detached_watchdog_never_promotes_missing_terminal`
- `416:test_public_detached_runner_uses_existing_lifecycle_once`
- `422:test_public_detached_runner_uses_existing_lifecycle_once.fake_watchdog`
- `452:test_public_detached_runner_executes_existing_convert_lifecycle`

### tests/test_translation_output_failures.py

- `22:_page`
- `36:_page_with_units`
- `75:test_translation_output_mismatch_retries_same_chunk_then_succeeds.structured`
- `102:test_translation_output_truncation_retries_once_with_thinking_disabled.structured`
- `146:test_translation_output_truncation_fallback_is_bounded_and_safe.structured`
- `189:test_translation_output_truncation_splits_chunk_sequentially.structured`
- `249:test_split_fallback_restores_protected_placeholders.structured`
- `293:test_normal_chunk_protects_and_restores_protected_fragments`
- `300:test_normal_chunk_protects_and_restores_protected_fragments.structured`
- `331:test_placeholder_variants_are_canonicalized_before_restoration`
- `359:test_placeholder_cardinality_and_unknown_tokens_fail_safely`
- `378:test_missing_placeholder_retries_before_failing_the_split_unit`
- `385:test_missing_placeholder_retries_before_failing_the_split_unit.structured`

### tests/test_translation_workflow.py

- `101:test_translation_branches_skip_and_resume_from_cover.fake_observe`
- `111:test_translation_branches_skip_and_resume_from_cover.fake_split`
- `120:test_translation_branches_skip_and_resume_from_cover.fake_docling`
- `127:test_translation_branches_skip_and_resume_from_cover.fake_unpack`
- `132:test_translation_branches_skip_and_resume_from_cover.fake_merge`
- `137:test_translation_branches_skip_and_resume_from_cover.passthrough`
- `142:test_translation_branches_skip_and_resume_from_cover.fake_load`
- `148:test_translation_branches_skip_and_resume_from_cover.fake_structure`
- `159:test_translation_branches_skip_and_resume_from_cover.fake_translate`
- `163:test_translation_branches_skip_and_resume_from_cover.fake_translate_lite`
- `167:test_translation_branches_skip_and_resume_from_cover.fake_check`
- `170:test_translation_branches_skip_and_resume_from_cover.fake_review`
- `182:test_translation_branches_skip_and_resume_from_cover.fake_fix`
- `186:test_translation_branches_skip_and_resume_from_cover.fake_verify`
- `190:test_translation_branches_skip_and_resume_from_cover.fake_cover`
- `201:test_translation_branches_skip_and_resume_from_cover.fake_validate`
- `205:test_translation_branches_skip_and_resume_from_cover.fake_markdown`
- `209:test_translation_branches_skip_and_resume_from_cover.fake_docx`

### tests/test_workflow_state.py

- `19:_checkpoint`
- `110:test_checkpoint_commit_failure_keeps_single_task_result_without_partial.task`
- `129:test_checkpoint_commit_failure_keeps_single_task_result_without_partial.fail_after_task`

### translate/adapters/docling.py

- `24:DoclingClient.__init__`
- `49:DoclingClient._request`

### translate/adapters/langfuse.py

- `46:_Observation.start_observation`
- `48:_Observation.update`
- `50:_Observation.end`
- `95:_warning`
- `115:_get_client`
- `192:observe.reset_parent`

### translate/adapters/llm.py

- `78:LLMError.__init__`
- `105:_LLMAttemptError.__init__`
- `244:_model`
- `268:_status_code`
- `300:_invoke_with_retry`
- `384:structured.invoke_and_parse`

### translate/adapters/pandoc.py

- `188:_validate_docx`
- `200:_validate_docx_layout`
- `295:_remove_update_fields`
- `320:_index_paragraph`
- `399:_is_cover_paragraph`
- `405:_is_page_break`
- `411:_is_generated_front_matter`
- `483:_validate_output_directory`

### translate/adapters/pdf.py

- `108:_validate_png`
- `113:_validate_split`

### translate/adapters/qdrant.py

- `57:RegistrationError.__init__`
- `89:_retryable`
- `107:_retry`
- `142:_ensure_time`
- `171:_embeddings`
- `180:_store`
- `229:_docling_text`
- `265:_text`
- `294:_register`
- `435:_write_and_verify`
- `443:_write_and_verify.batch_exists`
- `462:_write_and_verify.write_batch`
- `493:_write_and_verify.verify_batch`
- `513:_registration_revision`
- `542:_source_parts`
- `568:_valid_pdf_parts`

### translate/common/fingerprint.py

- `133:_compare`
- `153:_optional_file_hash`

### translate/common/lifecycle.py

- `50:ResumeRejectedError.__init__`
- `94:PublicRunError.__init__`
- `250:execute_run.progress`
- `256:execute_run.task_status`
- `288:execute_run.observation_warning`
- `499:_safe_output_diagnostics.count`
- `518:_copied_inputs`
- `523:_collect_sources`
- `540:_execute_operation`

### translate/common/logger.py

- `18:RedactionFilter.__init__`

### translate/common/progress.py

- `86:WorkflowProgress.__init__`

### translate/common/runs.py

- `129:RunRepository.__init__`
- `285:_safe_role`
- `363:_safe_logical_path`
- `391:_read_scanned_record`
- `400:_is_link_or_junction`

### translate/common/settings.py

- `120:_positive`
- `132:_positive_float`
- `144:_runs_dir`
- `211:_validate`

### translate/common/terminal_evidence.py

- `101:_canonical_run_id`
- `158:TerminalEvidence.validate_run_id`
- `163:TerminalEvidence.validate_safe_names`
- `189:EvidenceStore.__init__`
- `556:_read_heartbeat`
- `575:_operation_from_previous`
- `581:_safe_phase`
- `588:_safe_stage`
- `592:_nonnegative_int`
- `600:_optional_nonnegative_int`
- `604:_child_parser`
- `648:_child_entry.callback`

### translate/common/workspace.py

- `144:_validate_json`
- `148:_write_manifest`
- `156:_flush_tree`
- `167:_backup_path`
- `177:OutputLock.__init__`
- `181:OutputLock.__enter__`
- `193:OutputLock.__exit__`

### translate/tasks/align.py

- `32:_items`
- `41:_valid`

### translate/tasks/cover.py

- `35:_validate_cover`

### translate/tasks/docling.py

- `53:_validate_output`

### translate/tasks/fix.py

- `35:_apply`
- `38:_apply.fixed`
- `72:_validate_mapping`

### translate/tasks/normalize.py

- `24:_clean`
- `43:_page`
- `51:_filter_tree`

### translate/tasks/position.py

- `17:_key`
- `35:_resolve`
- `65:_continuous`
- `85:_rewrite_ref`
- `93:_merge_table`
- `120:_merge_table.dimensions`
- `155:_merge_fragments`
- `222:_reading_order`
- `250:_reading_order.order_key`
- `276:_sort_children`

### translate/tasks/review.py

- `125:_is_output_truncated`
- `171:_cache_key`

### translate/tasks/split.py

- `17:PdfInputError.__init__`

### translate/tasks/structure.py

- `58:StructurePageError.__init__`
- `241:_heading_jumps`
- `252:_merge_code`
- `274:_apply`

### translate/tasks/translate.py

- `145:_restore_placeholders`
- `159:TranslationOutputError.__init__`
- `189:apply_translations.translated`
- `202:_chunks`
- `256:_translate_page`
- `267:_translate_page.translate_chunk`
- `295:_translate_page.translate_chunk.split_after_truncation`

### translate/tasks/translate_lite.py

- `20:_protect`

### translate/tasks/unpack.py

- `17:_safe_target`

### translate/tasks/validate.py

- `17:_translation_warnings`
- `44:_require_translations`

### translate/tasks/verify.py

- `30:_revert`

### translate/workflows/comparison_review.py

- `91:_load_document`
- `95:_save_findings`
- `106:_load_findings`
- `114:_comparison_document`
- `151:build_graph.tracked`
- `154:build_graph.tracked.wrapped`
- `197:build_graph.branch_root`
- `200:build_graph.split_node`
- `210:build_graph.docling_node`
- `216:build_graph.unpack_node`
- `221:build_graph.merge_node`
- `231:build_graph.position_node`
- `238:build_graph.normalize_node`
- `245:build_graph.load_node`
- `251:build_graph.align_node`
- `264:build_graph.check_node`
- `275:build_graph.review_node`
- `290:build_graph.report_node`

### translate/workflows/translation.py

- `98:_document`
- `104:_findings`
- `112:_save_document`
- `117:_save_findings`
- `128:_workspace`
- `140:build_graph.node`
- `141:build_graph.node.wrapped`
- `177:build_graph.split_node`
- `184:build_graph.docling_node`
- `191:build_graph.unpack_node`
- `195:build_graph.merge_node`
- `204:build_graph.position_node`
- `210:build_graph.normalize_node`
- `218:build_graph.load_node`
- `223:build_graph.structure_node`
- `234:build_graph.translate_node`
- `248:build_graph.translate_lite_node`
- `255:build_graph.check_node`
- `262:build_graph.review_node`
- `277:build_graph.fix_node`
- `288:build_graph.verify_node`
- `300:build_graph.cover_node`
- `306:build_graph.validate_node`
- `315:build_graph.markdown_node`
- `325:build_graph.docx_node`
- `387:_failed_status`

## 導入済み機能との重複

| 対象 | 確認した代替 | 判定と注意 |
| --- | --- | --- |
| common/identifiers.pyのUUIDv7 bit構築 | uuid-utils 0.17.1のuuid_utils.compat.uuid7 | stdlib UUID/version7の返却を確認。導入済みPackageで置換可能。直接利用の依存宣言と公開UUID契約Testが必要 |
| Docling/LibreTranslate/LLM/Qdrantの試行回数・指数backoff/full jitter | tenacity 9.1.4 Retrying/stop_after_attempt/retry_if_exception/wait_random_exponential | 機構は重複。retryable判定・file seek・deadline・診断変換は製品固有。Graph node retryへの機械的移動は禁止 |
| workspace/fingerprintのfile hash loop | 標準hashlib.file_digest | 同等機能と内部重複あり。copy中に同時計算するhashとは区別 |
| settingsの正値検証 | Pydantic 2.13.5 Field/PositiveInt/PositiveFloat | env名の診断・有限float・clampを維持して型制約へ集約する候補。pydantic-settingsは未導入 |
| OutputLock/Evidence lock | portalocker | 現作業ツリーは利用済み。旧OS別実装はpending修正で撤去済み、I/O不具合の解決は未確認 |
| Atomic保存 | portalocker.open_atomic | 既存path不可のassertがありdrop-in代替にならない。検証後公開・directory復元も契約差あり |
| PDF/Pandoc処理 | pypdfium2/Pillow/Pandoc | 既存機能へ委譲済み。Internal DocumentとPandoc ASTのschema対応は製品固有で、parser再実装ではない |
| redaction/文書ID付き分割/token推定 | 完全に同等な導入済みAPIは未確認 | 存在しない代替を仮定して違反と断定しない。tiktokenをローカルGemmaの正確なtokenizerとは扱えない |

追加注意: OpenAIEmbeddingsの既定max_retries=2とQdrant外側retryが二重。STRUCTURE追加1回retryとLLM adapter retry、translate内容整合性retryも合計回数/時間を点検する。Packageを使うだけでは二重retryは解消しない。

## ④ Resumeと進捗の二重管理禁止

前のdocument_processing/4file新設案は撤回した。次nodeの決定はLangGraph checkpointを唯一の正本とする。単なる移動/名称変更で解決しない。

| 状態 | 現在の利用 | 対応対象 |
| --- | --- | --- |
| SqliteSaver/get_state().next/stream(None) | 翻訳・比較の実際の再開位置 | 維持する唯一の正本 |
| GraphState completed_tasks/current/total/current_task | 独自に追加した進捗表示値 | 完了履歴/Graph状態からの導出へ縮小し、別の完了管理をしない |
| WorkflowProgress.completed | 上記完了値を再保持して通知を抑止 | 追跡classを廃止する方向でstream表示へ統合 |
| RunRecord.status/last_task | 表示、export gate、削除gate、失敗fallback | checkpoint/稼働lockから導出。manifestへ独立更新する状態を残さない |
| 公開fingerprint | 入力/設定変更時のResume拒否 | 製品固有の入力検証として必要。進捗管理ではない |
| Workflow別fingerprint/thread_id/workflow.json | 公開判定より狭い別hashでcheckpointを識別 | UUIDv7とthread_id対応を一本化する案。旧checkpoint移行は未決定 |
| STRUCTURE page cache | node内で完了pageのモデル呼出をskip | 独自再開機構。逐次subgraph等でLangGraphの永続化へ移す設計が必要。消すだけで全page再実行にしない |
| REVIEW chunk cache | node内で完了chunkのRAG/LLMをskip | 同上。分割後ID/順序を保持し、二つの正本を並存させない |
| Qdrant batch実在確認 | 決定的IDの外部副作用を冪等化 | checkpointの代替ではない。可変Qdrant状態を前提とする検証を維持 |
| TerminalEvidence | 検証の終端証拠、製品prepare_runは参照しない | testsへ隔離、製品からのcounter依存を撤去 |

register/convertは現在Graphを使わないため、状態廃止だけではexport/削除が壊れる。この2操作の正本を含む設計確認が必要。導入済みLangGraph tasks streamは開始/終了/Errorを提供するが、値の安全な抽出・対象page/chunkの診断は製品契約として検証する。モデル並列化は導入しない。

## 現在の完了状態

監査・候補の記録のみ。全関数の意味的同等性やコメント内容を網羅的に証明した完了宣言ではない。③-1・③-2・④は未解決。正式verifyでは利用者指定のtranslation→Microsoft WordでPDF化→入力PDFと生成PDFのreviewを実施する。単体Testや既存ArtifactからのDOCX再生成はその代替にしない。

