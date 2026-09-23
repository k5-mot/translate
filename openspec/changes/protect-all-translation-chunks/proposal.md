<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

`sample3.pdf`の実translateで、分割fallbackではなく通常の高推論chunk（page 2）から保護対象が欠落し、`ProtectedFragmentMissing`で停止した。通常chunkにも同じ保護契約を適用し、URL・Path・数値等を失わずに翻訳を完了できるようにする必要がある。

## What Changes

- 通常chunkとtruncation split chunkの両方で、保護対象をplaceholder化してLLMへ渡す。
- 通常chunkの高推論応答でもplaceholderをcanonical化・復元し、保護対象欠落時は有限retry後に安全に停止する。
- 既存のID対応、診断秘匿、シーケンシャル実行およびResume契約を維持する。
- `inputs/sample3.pdf`でregister済み参照を利用したtranslate/reviewの再検証を行う。

## Capabilities

### New Capabilities

- なし。

### Modified Capabilities

- `pdf-translation`: 翻訳chunkの種類にかかわらず保護対象を保持し、欠落時に成果物を公開しない契約へ変更する。

## Impact

- `translate/tasks/translate.py`のprompt保護、応答復元およびretry制御。
- 保護対象を含む翻訳ユニットのLLM prompt長と実行時間。
- PDF翻訳のunit test、少ページ実Runの成果物・Resume証跡。
- 外部依存は追加せず、Embedding/LLMはシーケンシャルのままとする。

## Stakeholders and Lifecycle Impact

- 運用・保守: 保護対象欠落を公開前に検出し、失敗RunをResume可能にする。
- 取得・供給・移行: Run形式と公開CLIの互換性を維持するため変更なし。
- 廃止: 既存の明示Run削除範囲を維持する。

## Quality Considerations

- Q-FUNC/Q-COMP: 通常chunkとsplit chunkの双方でURL、Path、Command、識別子、数値および単位の保持率100%をunit testと実Runで確認する。
- Q-REL/Q-REC: 保護対象欠落時に有限retryで停止し、本文だけの成果物を公開しないことをRun証跡で確認する。
- Q-SEC: prompt、生LLM応答および保護値をFailure Evidenceへ記録しないことを確認する。
- Q-MNT: 全pytest、Ruff、format、型検査およびOpenSpec strict validationを実行する。

