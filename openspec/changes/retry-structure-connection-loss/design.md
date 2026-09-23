## Decisions

- `LLMError.cause`がconnection系（`OpenAIConnectionError`等）のときだけ、同じprompt/pageを最大1回再送する。
- retryは前の要求終了後に開始し、partial responseは使わない。再試行後も失敗なら既存`StructurePageError`へ分類する。
- 接続retryはoutput truncation retryとは別の有限経路とし、raw responseを保存しない。
