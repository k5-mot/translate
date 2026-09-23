<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実PDFの同一Runを構造応答のfallback後まで進めた結果、TRANSLATEのローカルLLM応答が16,384 output tokensで打ち切られ、翻訳開始位置で停止した。構造と翻訳で異なる推論設定を持つため、翻訳側にも有限で安全な回復経路が必要である。

## What Changes

- TRANSLATEのtext structured outputが`finish_reason=length`となった場合、推論を無効化した代替要求を最大1回だけ逐次実行する。
- 代替要求でも完全なID対応と保護対象検証を満たさない場合は、既存の安全なFailureとして停止し、部分翻訳を公開しない。
- 同一Run、fingerprint、入力copy、checkpointおよびQdrant状態を維持し、代替成功後は未完了の翻訳単位からResumeできるようにする。
- 出力枯渇のstage、finish reason、数値token usageをterminal evidenceへ残し、raw応答・原文・credentialを保存しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: TRANSLATEの出力枯渇を有限fallbackで完了または安全停止できる要件を追加する。

## Impact

- `translate/tasks/translate.py` の逐次翻訳呼出しと `translate/adapters/llm.py` のthinking policy利用。
- 翻訳診断、Lifecycle/Resume、同一Run detached Gateおよび関連unit test。
- 新しい依存、並列実行、公開API、Run fingerprint変更は導入しない。

## Stakeholders and Lifecycle Impact

- 運用・保守: ローカルLLMの推論枯渇を分類し、同一Runを再開できる。
- 移行: 保存済みRunと既存checkpointを変更せず、未完了TRANSLATE単位から続行する。
- 取得・供給・廃止: 外部依存、保存期間および削除契約は変更しないため非該当。

## Quality Considerations

- Q-FUNC: 代替応答が完全なID対応と保護対象を満たす場合だけ翻訳を適用する。unit testと実PDF Gateで検証する。
- Q-REL: fallbackは最大1回・逐次で、request timeoutとtask deadlineを尊重する。失敗時はResume可能なcheckpointを保持する。
- Q-USE: stage、cause、finish reasonおよびtoken usageを表示し、raw本文を表示しない。
- Q-SEC: 原文、翻訳本文、prompt、画像binaryおよびcredentialをFailure/evidenceへ保存しない。
- Q-COMP/Q-PORT: 既存CLI、Streamlit、Qdrant、Docling、LibreTranslateおよびUUIDv7 Run契約への回帰がないことを全pytestとstrict validationで確認する。
