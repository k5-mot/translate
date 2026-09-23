<!-- markdownlint-disable MD041 -->

## Decisions

1. **placeholderはsplit時だけ**: 通常chunkの公開prompt契約は変えず、`force_no_reasoning`のsub-chunkだけ、各inlineの保護fragmentを`__PROTECTED_<unit>_<index>__`へ置換する。
2. **決定的復元**: structured responseのtextにplaceholderがあれば、対応する原文fragmentへ置換する。fragmentが元のまま返された場合も二重置換しない。
3. **有限検証**: 復元後に既存のID集合とprotected fragment検証を実行する。欠落は既存`retry_attempts`の範囲で再要求し、解消しない場合は安全な`ProtectedFragmentMissing`へ停止する。
4. **非漏えい**: placeholder mappingはprompt生成中だけ保持し、例外、terminal evidence、raw artifactへ渡さない。

## Verification

- placeholderを復元して完全応答を適用するunit test、欠落時の有限停止とredaction testを追加する。
- 全pytest、Ruff、format、ty baselineおよびstrict validationを実行する。
- 前Changeで失敗した同じRun IDをdetached Gateで再実行し、source hash不変、temp cleanup、TRANSLATE進行または安全停止を記録する。
