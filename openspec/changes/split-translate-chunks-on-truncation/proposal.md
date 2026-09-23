<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実PDFの同じRunでTRANSLATEの通常要求と推論無効化fallbackの双方が16,384 output tokensで打ち切られた。単一chunkを同じ大きさで再送してもローカルLLMの生成上限を超えるため、未完了chunkを決定的に分割して安全に進める必要がある。

## What Changes

- `output-truncated`を同じchunkで再度検出した場合、入力単位を決定的に分割し、推論無効化で各sub-chunkを逐次処理する。
- 分割は有限深さまたは単位数までに制限し、ID対応・protected fragment検証を通過した応答だけを適用する。
- 分割経路でもraw response、部分訳および原文をFailure/evidenceへ保存せず、既存のResume、atomic cleanup、fingerprint、Qdrant契約を維持する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: TRANSLATEの出力枯渇時に有限のsub-chunk fallbackで回復または安全停止する要件を追加する。

## Impact

- `translate/tasks/translate.py` のchunk処理と翻訳失敗診断。
- TRANSLATE unit test、実PDF detached Gate、同じRunのResume証跡。
- 新しい依存、並列実行、公開API、Run fingerprint変更は導入しない。

## Quality Considerations

- Q-FUNC/Q-REL: 分割fallbackは最大深さと逐次要求数を守り、成功時は未完了単位を継続する。
- Q-SEC: 診断はstage、cause、finish reasonおよび数値token usageに限定し、本文やcredentialを漏らさない。
- Q-COMP/Q-PORT: 既存のCLI、Streamlit、Qdrant、UUIDv7 Runおよび保存期間契約を変更しない。
