<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実翻訳の確認済み22要求では、生成tokenの89.80%を推論が占め、high要求2件は生成上限を使い切って再送していた。利用者の指示に従い現在の処理を中断し、検証時だけ全LLM要求の推論をOFFにして、新規Runで成果物を検査できるようにする。

## What Changes

- `LLM_REASONING_MODE=task-default|off`を追加する。未設定は既存のTask別指定を維持し、検証時だけ`off`を明示する。
- OFFではTaskの指定より優先して推論とProviderのthinkingを無効化する。STRUCTURE、TRANSLATE、ALIGN、REVIEW、VERIFY、FIXを含み、Embeddingには適用しない。
- 設定差をResume互換性とWorkflowのCheckpoint識別へ反映する。既存の通常設定Runを一律に無効化せず、OFFとの混用を拒否する。
- OFFで既に実行した要求を「推論を無効化した再試行」として重複送信せず、既存の有限な出力切断回復を維持する。
- `inputs/sample3.pdf`を新規Runで逐次検証し、実際のProvider観測と成果物の品質を別々に記録する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: 検証用推論設定の選択、既定動作、互換性および実効設定の観測契約。

## Impact

既存の`translate/common/settings.py`、`fingerprint.py`、`translate/adapters/llm.py`、`translate/tasks/translate.py`、Translation/Comparison Review Workflowの識別、対応Test、`.env.sample`と利用手順が対象。依存・Module・CLI option・UI widgetは新設しない。本文形式、timeout、token予算、モデル、逐次実行、保存layoutは変更しない。common整理、LangGraph再開状態の重複、ALIGN品質、表画像配置は別Changeの未解決事項として保持する。

## Stakeholders and Lifecycle Impact

- 運用・検証担当: 現在のRunは停止済み。旧入力・Artifact・Checkpointを残し、新しいIDと別export先でOFF検証する。
- 保守: default/offの回帰Testと実効値を記録し、速度だけを品質合格とみなさない。
- 移行・廃止: 設定未指定の既存Runを維持し、通常/OFF間のResumeを拒否する。旧Runの削除・状態書換え・成果物上書きは行わない。
- 取得・供給: 新しいServiceやPackageの取得は不要。WordによるPDF作成は引き続き検証オペレーションで、製品機能にしない。

## Quality Considerations

- Q-FUNC（機能適合性）: 対象LLM要求すべてにOFF設定が反映され、default要求が不変であることを送信境界Testで確認する。
- Q-PERF（性能効率性）: 実Runの要求時間と取得可能な推論/出力tokenを記録する。固定の短時間合格基準やhigh同等品質は要求しない。
- Q-COMP/Q-REL（互換性・信頼性）: 異なる推論設定の誤Resumeを0件とし、有限retry・逐次処理・障害後のCheckpoint保持を回帰Testする。
- Q-USE（利用性）: 許容値、既定値、新規検証手順を記載し、不正値は外部要求前に設定名付きで拒否する。
- Q-SEC（安全な情報取扱い）: metadataは実効設定と数値のみ追加し、本文・Credentialを出力しない。不正設定の元入力をErrorへ反映しない。
- Q-MAINT（保守性）: 既存Settings/Adapterへ限定した差分で実装し、Lint・型・Testを通す。
- Q-PORT（移植性）: CLI/UIが同じ設定を読み、新たなOS依存実装を追加しない。
- Safety（人・財産への危害防止）: 安全制御機器ではなく、直接の安全機能変更は対象外。成果物の人による確認と未解決品質問題は残す。
