<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実Model detached GateではSTRUCTURE完了後、TRANSLATEのローカルLLM呼出しが既定の300秒request timeoutで終了した。ローカルModelの長い生成を許容する設定が必要であり、timeoutを短くしたまま再実行すると、Resume可能な正本Runを不要に停止する。

## What Changes

- ローカルOpenAI互換LLMの既定request timeoutを十分な有限値へ延長し、`TRANSLATE_REQUEST_TIMEOUT_SECONDS`による明示上書きを維持する。
- timeoutは無制限にせず、既存のretry回数・backoff・task deadline・逐次実行を維持する。
- timeout時に`text-invoke`／`vision-invoke`と安全な固定causeをFailure／Terminal Evidenceへ保持する。
- Unit／settings／Lifecycle Testと、同じUUIDv7正本Run cloneによるdetached Gateで、正本不変・temp cleanup・terminal Evidenceを確認する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: ローカルLLMの有限request timeoutとtimeout Failureの診断・Resume可能停止を明示する。

## Impact

- `translate/common/settings.py`の既定値と設定ドキュメント、`translate/adapters/llm.py`のtimeout適用、Lifecycle／Evidenceの診断Testに影響する。
- Run schema、fingerprint、Qdrant、CLI／Streamlit API、外部dependency、Model／Embeddingの並列数は変更しない。

## Quality Considerations

- Q-REL: 長い生成を許容しつつ、request／taskの有限上限とResume可能停止を保つ。
- Q-USE／Q-MAIN: timeout値、stage、causeを利用者へ安全に提示し、既存settings／retry回帰を防ぐ。
- Q-SEC: timeout Errorへprompt、本文、endpoint、credentialを保存しない。
- ISO/IEC/IEEE 12207: 設定変更をUnit／Integration／detached Gateで検証し、失敗時は公開Resumeを行わない。
