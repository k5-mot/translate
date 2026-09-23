<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実PDF GateでTRANSLATEの二分割fallbackは呼び出されたが、sub-chunk応答がURL/path等の保護fragmentを落とし、`ProtectedFragmentMissing`で停止した。ローカルLLMへ保護対象を明示し、応答後に決定的復元する必要がある。

## What Changes

- split fallbackのpromptで保護fragmentを一意placeholderへ置換し、応答後に元のfragmentへ戻す。
- placeholder欠落時は既存の有限retryを使い、復元後もID・protected fragment検証を通過した結果だけを適用する。
- raw response、prompt、原文およびcredentialはFailure/evidenceへ保存せず、逐次・同一Run・既存fingerprint契約を維持する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: split fallbackでも保護fragmentを維持して翻訳を継続または安全停止する要件を追加する。

## Impact

- `translate/tasks/translate.py` のsplit promptと応答復元。
- protected fragment回帰test、同じRunの実PDF detached Gate。
- 新依存、並列実行、公開API、fingerprint変更は導入しない。
