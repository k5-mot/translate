<!-- markdownlint-disable MD041 -->

## Context

前ChangeでTRANSLATEに推論無効化の1回fallbackを追加したが、実PDFでは通常要求とfallbackの双方が`finish_reason=length`、`output_tokens=16384`で終端した。ローカルモデルは推論を無効化しても長い入力単位で出力上限に達することがある。

## Decisions

1. **決定的な二分割**: 同じchunkで初回要求と推論無効化fallbackがともに出力枯渇したときだけ、chunkの配列を中央で二分する。各sub-chunkは元の順序とIDを保持する。
2. **有限・逐次**: 分割は最大2段階（最大4 sub-chunk）までとし、各要求は前の要求終了後に開始する。空配列や1単位まで到達した場合は再分割せずFailureへ戻す。
3. **検証済み結果だけを適用**: 各sub-chunkを`reasoning="none"`、`thinking="disabled"`で要求し、既存のID集合とprotected fragment検証を通過した場合だけmappingへ追加する。失敗途中のmappingは公開成果物へ書き出さない。
4. **安全な診断**: 最終Failureは既存の`LLMError`分類を利用し、stage、cause、`output-truncated`、finish reason、数値token usageのみを保持する。分割した原文、prompt、raw responseは例外・artifactへ渡さない。

## Resume boundary

`_translate_page`のchunk mappingはページ完了時にだけ適用されるため、分割途中の失敗はページ未完了として残る。Run metadata、fingerprint、input copy、Qdrant状態は変更せず、同じRunの明示Resumeで失敗chunkから再実行する。

## Verification

- 分割成功、最大深さ到達、ID不一致、protected fragment欠落および診断redactionをunit testで確認する。
- 全pytest、Ruff、format、既存ty baselineおよびstrict validationを実行する。
- 失敗した同じRun IDでdetached Gateを実行し、TRANSLATE進行または安全停止、SQLite hash不変、temp cleanup、Resume証跡を確認する。
