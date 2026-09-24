<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

`sample3.pdf`のtranslateは完了したが、REVIEWが1ページ分の大量pairsを一度にLLMへ渡したため、出力上限16,384 tokenで`LLMOutputTruncatedError`となった。ReviewのFindingを失わず、決定的な分割と同じRunからのResumeで比較Reviewを完了できるようにする必要がある。

## What Changes

- REVIEWの入力pairsを決定的なsub-chunkへ分割し、各chunkをシーケンシャルに査読する。
- output-truncated時は有限retry後にchunk分割へfallbackし、全Findingをページ単位へ統合する。
- Review Artifactは全chunk完了後にatomic公開し、未完了時は成果物を公開せず同じRunをResume可能にする。
- 既存checkpointに残るDocling画像URIもMERGE後の共通assets rootへ正規化し、VALIDATEから成果物生成まで継続できるようにする。
- `sample3.pdf`のtranslate成果物を使って、同じRunのREVIEW Resume、Comparison Reviewおよび最終品質検証を行う。

## Capabilities

### New Capabilities

- なし。

### Modified Capabilities

- `pdf-translation`: 翻訳後の意味Reviewが出力上限で停止せず、Findingを完全に保持して公開する契約を変更する。
- `comparison-review`: 翻訳PDFと入力PDFの比較Reviewを、分割Review結果を統合したArtifactで実行できるようにする。

## Impact

- `translate/tasks/review.py`のpairs分割、retry、Finding統合およびatomic Artifact。
- REVIEW WorkflowのResume checkpointとFailure Evidence。
- 実Runの処理時間とReview prompt数。
- 外部依存は追加せず、LLM/Embeddingはシーケンシャルに維持する。

## Stakeholders and Lifecycle Impact

- 運用・保守: 出力枯渇時に同じRunをResumeし、完成したFindingだけを公開する。
- 移行・供給: 既存Runのfingerprintと公開CLI契約は維持する。
- 廃止: Run削除範囲は変更しない。

## Quality Considerations

- Q-FUNC/Q-COMP: 全pairsが一度ずつReviewされ、Findingの欠落・重複が0件であることをunit testと実Runで確認する。
- Q-REL/Q-REC: output-truncated後に有限retryと分割fallbackを行い、未完了Artifactを公開せずResume可能にする。
- Q-SEC: Review prompt、生応答、入力本文をFailure Evidenceへ保存しない。
- Q-PERF: 分割は逐次実行し、chunk数・wall time・token診断を安全な証跡へ記録する。
- Q-MNT: 全pytest、Ruff、format、型検査、OpenSpec strict validationを通過させる。
