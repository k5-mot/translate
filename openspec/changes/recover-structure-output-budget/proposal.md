<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実PDFの同一Runを1800秒のローカルLLM要求時間で再実行した結果、従来の300秒タイムアウトは回避できた一方、STRUCTUREのtext応答が16,384 output tokensで打ち切られ、`LLMOutputTruncatedError`として安全に停止した。受入れを完了するには、同一fingerprint・同一Runを維持したまま、ローカルOpenAI互換ModelのJSON構造応答を有限かつ逐次的に収束させる必要がある。

## What Changes

- STRUCTUREのlocal Model向けstructured output経路を、json-schema応答が長大化した場合にも収束しやすいprompt/schema fallbackへ調整する。
- 応答本文や原文を保存せず、`finish_reason=length`を検出したときは定義済みの一回限りの代替経路だけを逐次実行する。
- 代替経路でも完全なPydantic応答を得られない場合は、既存の安全な`output-truncated` FailureとResume可能なcheckpoint境界を保持する。
- token fingerprint、Run metadata、Qdrant状態および公開成果物契約は変更しないため、互換な同一RunをResumeできるようにする。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: ローカルLLMのSTRUCTURE structured outputを有限fallbackで完了または安全停止できる要件を追加する。

## Impact

- `translate/adapters/llm.py` の逐次structured output呼出しと `translate/tasks/structure.py` のSTRUCTURE呼出し。
- STRUCTUREのunit／integration test、実PDF detached Gate証跡、既存RunのResume経路。
- 新しい依存、並列実行、永続schema、公開API、Run fingerprintは導入しない。

## Stakeholders and Lifecycle Impact

- 運用・保守: ローカルLLMの長時間推論と応答枯渇を区別し、失敗時は同一RunをResumeできる。
- 移行: 保存済みRun、checkpoint、入力copyおよび成果物を変換しない。同一fingerprintのRunだけを再利用する。
- 取得・供給・廃止: 外部依存とRun保存期間の契約は変更しないため非該当。

## Quality Considerations

- Q-FUNC: 完全な構造応答を得た場合だけpage Artifactを公開し、部分応答を0件にする。mockおよび実PDF Gateで検証する。
- Q-REL: fallbackは最大1回・逐次、task deadlineとrequest timeoutを超えない。同一RunのResume可否とcheckpoint再利用を検証する。
- Q-USE: 失敗時は既存のpage、target、stage、finish reasonおよびtoken数だけを表示し、raw responseを出さない。
- Q-SEC: prompt、本文、画像binary、credentialをFailureやterminal evidenceへ保存しないことをredaction testで確認する。
- Q-COMP/Q-PORT: 既存CLI、Streamlit、Qdrant、Docling、LibreTranslateおよびUUIDv7 Run契約に回帰がないことを全pytestとstrict validationで検証する。
