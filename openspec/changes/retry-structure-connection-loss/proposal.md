## Why

長時間の実PDF GateでSTRUCTUREのLLM要求が一時的な`OpenAIConnectionError`で停止した。既存fallbackは出力枯渇だけを対象としているため、接続断を有限回再試行して同じpageを継続する。

## What Changes

- STRUCTUREのtext/vision要求で接続系LLMErrorを最大1回、逐次再試行する。
- 出力枯渇fallback、checkpoint、diagnostic redaction、timeout、fingerprintおよび並列禁止を維持する。

## Capabilities

### Modified Capabilities

- `pdf-translation`: STRUCTURE接続断から有限retryで回復する要件を追加する。
