<!-- markdownlint-disable MD041 -->

## Context

STRUCTUREは既にJSON-schemaからprompt modeへ一回だけ切り替える回復経路を持つ。一方、TRANSLATEは`structured`の既定prompt modeを使いながら高推論設定を固定しており、ローカルGemmaが推論出力を使い切った場合に`text-output`の`output-truncated`で終端する。

## Goals / Non-Goals

**Goals:**

- TRANSLATEのtext output truncationを、同じchunkに対する最大1回の推論無効化要求で回復する。
- 完全な`TranslationResponse`、ID集合およびprotected fragment検証を通った結果だけを適用する。
- 失敗時の既存diagnosticとatomic cleanup、同一Run Resume契約を維持する。

**Non-Goals:**

- output token上限、Run fingerprint、chunk入力契約、公開APIまたは並列実行の変更。
- raw response保存、部分訳の公開、無制限retryまたは構造化経路の再設計。

## Decisions

1. **TRANSLATE専用の有限fallback**: `LLMError`が`stage=text-output`、`failure_kind=output-truncated`、`finish_reason=length`のときだけ、同一promptを`reasoning="none"`かつ`thinking="disabled"`で一回再送する。通常のID不一致retryは既存の`retry_attempts`契約を維持する。
2. **完全応答のみ採用**: fallback応答は既存のID集合と保護対象検証へ通し、`TranslationOutputError`なら再試行せず終端させる。raw本文は例外やevidenceへ渡さない。
3. **逐次実行**: 初回要求が終了してからfallbackを開始し、同時に一つのModel requestだけを許可する。
4. **Resume境界**: `_translate_page`でchunk単位のmappingを適用するため、失敗chunkの後続は未処理のまま残す。Run metadataやfingerprintを変更せず、既存のRun Resumeが同じchunkから再開できることをGateで確認する。

## Quality Attribute Design

- **Q-FUNC/Q-REL**: truncationを分類し、fallback成功時は翻訳を継続、失敗時は安全なFailureにする。focused testと実PDF Gateで検証する。
- **Q-SEC**: Failure/evidenceにはstage、cause、finish reason、数値token usageのみを許可し、原文・prompt・翻訳本文・credentialを出さない。redaction testで検証する。
- **Q-COMP/Q-PORT**:既存のCLI、Streamlit、Qdrant、Docling、LibreTranslateと同一Run契約を変更せず、全pytest、Ruff、strict validationで確認する。

## Lifecycle, Migration and Operations

保存済みRunにmigrationは行わない。新コードは同一fingerprintの未完了Runへ適用され、成功時のみ次Taskへ進む。失敗時はRunを削除せず、CLI/Streamlitの明示Resumeで再開できる。廃止時は既存Run削除契約に従う。

## Risks / Trade-offs

- [Risk] 推論無効化により翻訳品質が下がる可能性 → ID、protected fragment、後続reviewを必須にし、fallbackはtruncation時だけに限定する。
- [Risk] fallbackでも同じ上限に達する可能性 → 最大1回で停止し、token診断とResume境界を保持する。
- [Risk] 長時間のローカル要求 → 既存の1800秒request timeoutと21600秒task deadlineをそのまま適用する。

## Migration Plan

Migrationなし。実装後に同一Run detached Gateを再開し、TRANSLATEのtruncation回復または安全な失敗を記録する。成功後は同一run-idを明示Resumeし、完了済みchunkの再実行がないことを確認する。
