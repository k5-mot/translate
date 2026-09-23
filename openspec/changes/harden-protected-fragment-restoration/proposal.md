<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

v9の実PDF検証では、Structureを完了した後のTRANSLATEで`ProtectedFragmentMissing`が発生し、分割されたLLM応答からURL等の保護対象を復元できずRunが停止した。保護対象を失わずにローカルLLMの出力揺らぎを扱い、少ページの実サンプルで再検証できる契約へ強化する必要がある。

## What Changes

- 分割翻訳で利用する保護placeholderを、LLMが表記揺れ・部分欠落を起こした場合にも安全に検出・復元できるようにする。
- 復元不能な応答は、保護対象を欠落させたまま公開せず、有限回の再試行または明示的な失敗証跡へ遷移させる。
- 復元処理の診断情報から原文URL等の機密値を除外し、対象IDと失敗分類だけを保持する。
- `inputs/sample3.pdf`を用いた実Runで、保護対象保持、Resume可能な失敗状態、成果物公開前検査を検証する。

## Capabilities

### New Capabilities

- なし（既存のPDF翻訳Capabilityを強化する）。

### Modified Capabilities

- `pdf-translation`: 分割翻訳後の保護対象復元・検証と、復元不能時の公開拒否契約を明確化する。

## Impact

- `translate/tasks/translate.py`のplaceholder生成、応答正規化、保護対象検証および再試行処理。
- TRANSLATEの失敗証跡とRun Resume状態。
- PDF翻訳のユニットテスト、少ページ実PDFの受入証跡。
- 外部依存の追加は行わない。LLM呼び出しは既存どおりシーケンシャルにする。

## Stakeholders and Lifecycle Impact

- 運用・保守: 保護対象欠落を成果物公開前に検出し、診断可能なRunとして保持する。
- 移行・取得・供給: 既存Run形式と公開CLI契約を変更しないため適用なし。
- 廃止: Run削除規則は変更しない。

## Quality Considerations

- Q-FUNC/Q-COMP: URL、Path、Command、識別子、数値および単位が欠落・改変されないことを、placeholder表記揺らぎを含むテストで確認する。
- Q-REL/Q-REC: 復元不能時に本文だけの成果物を公開せず、失敗証跡とResume可能状態を保持することを少ページ実Runで確認する。
- Q-SEC: 失敗証跡・ログに原文保護値やLLM生応答を記録しないことを検査する。
- Q-MNT: 既存の全自動Test、Ruff、型検査およびOpenSpec strict validationを実行する。

