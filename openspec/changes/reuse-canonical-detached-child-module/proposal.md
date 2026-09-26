<!-- markdownlint-disable MD013 MD041 -->

## Why

実Comparison ReviewでLangfuseに39件の`llm.request`が残る一方、診断JSONの`llm_calls`は0だった。診断childのmodule起動とAdapterの通常importでcounterの束縛先が分かれる経路を修正し、実行済みなのに未実行と読める検証結果を防ぐ。

## What Changes

- Debug child入口を通常importした既存処理へ委譲し、既存counter hookと同じContextVarを使用する。
- 成功・公開失敗・再試行時の計数が子processの終端JSONへ届くことを、外部通信を行わない回帰Testで確認する。
- 既存Evidence schema、直接上書き・lock・flush/fsync、公開操作、Checkpoint、Resume判定を維持する。
- 過去の0件記録は上書きせず、計測不成立として検証文書に残す。Langfuse span数と送信試行数の意味を区別する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。既存`run-lifecycle`の品質検証を支える検証Toolの不具合修正であり、公開Requirementは変更しない。先行する`persist-detached-resume-terminal-evidence`、`overwrite-diagnostic-json-in-place`と同様に`skip_specs: true`とし、delta specは作成しない。

## Impact

`translate/common/terminal_evidence.py`のdebug入口、`tests/test_terminal_evidence.py`と関連検証記録が対象。Adapterの既存計数位置を維持し、新Module・依存・状態台帳・環境設定を追加しない。common全体の再配置、ALIGN、表内画像、出力構成の変更は含めない。

## Stakeholders and Lifecycle Impact

- 検証者・保守者: 通常importとmodule起動の差を回帰Testで検出できるようにする。過去の0件を未呼出しの証明には使わない。
- 移行・運用: 既存JSONは読込み可能。診断process停止後に変更を適用し、次の実検証はreasoning OFF・逐次実行で行う。旧Run・成果物を保持する。
- 廃止・Rollback: 二重のcounter束縛経路だけを廃止する。変更撤回時も既存Run・診断記録を削除しない。
- 取得・供給: 新Package・外部Service・公開interfaceの追加はないため、新たな調達・配布手順は不要。

## Quality Considerations

| ID / 特性 | 確認目標 |
| --- | --- |
| Q-FUNC 機能適合性 | 既知回数の既存hook呼出しが終端JSONと一致。未束縛時は副作用なし |
| Q-REL 信頼性 | 成功/公開失敗/再試行、入れ子と例外後のcontext復元をTest。前回計数の混入0 |
| Q-PERF 性能効率 | 新たな外部request・parallel実行・常駐監視を追加しない |
| Q-COMP 互換性 | JSON形式、CLI/UI、fingerprint、Checkpointを変更せず関連回帰Test成功 |
| Q-USE 利用時の分かりやすさ | LLM送信試行、Embedding client生成、Qdrant hookの粒度を区別して記録 |
| Q-SEC Security | 本文・認証情報を追加保存せず、テスト用秘密文字列の漏出0 |
| Q-MAIN 保守性 | 既存関数への委譲のみ。Ruff・format・ty・全pytest成功 |
| Q-PORT 移植性 | Windowsの実子processとmodule入口を通す回帰Test成功 |

新たな安全性用途、操作方式、拡張設定は導入しないため、それらの新規品質目標は設けない。Embedding/Qdrantの厳密な物理通信回数や同時実行数の計測設計は本修正の合格条件に混ぜない。
