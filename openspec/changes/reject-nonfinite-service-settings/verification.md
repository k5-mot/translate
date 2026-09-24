<!-- markdownlint-disable MD013 MD041 -->

## 計画段階の検証（2026-09-25）

提案のみ。0/8 tasksで、製品修正・正式verify・archive・merge・pushは未実施。SETTINGS-FINITE-001は未解決のまま。

### 確認した事実

- `load_settings('convert', env=...)`の隔離した合成設定で、4種類すべての秒数環境変数が`nan`/`NaN`/`inf`/`+Infinity`/`1e309`を受理することを確認した。`-inf`、0、負数は既存の比較で拒否される。実Serviceへその値を渡す実験はしていない。
- 直接Settingsを作ると4 fieldともNaN/±Infinityを受理する。既存`test_settings.py`は0拒否と正常値を検査しており、この問題の回帰Testは存在しない。
- Pydantic 2.13.5の公開FiniteFloatは非有限を拒否し、PositiveFloatだけでは正のInfinityが通る。FiniteFloatとgt=0のTypeAdapterを組み合わせたメモリ内候補で、非有限・非正数の拒否と0.25/1,800/21,600/最大有限floatの保持を確認した。これは製品修正の証拠ではない。
- 生文字列を直接Pydanticへ渡すと、既存floatで受理される全角数字等の扱いが変わる。標準float変換を維持する設計へ反映した。内部retry=0を使う既存Testも確認し、env制約との区別を設計に記載した。
- 読取専用の実CLI診断で、.env無効・実秘密を渡さない子processへ合成の無効秒数と合成API keyを渡した。`python cli.py runs`は終了コード1、設定名あり、無効設定値markerあり、無関係な合成API key markerなし。出力本文は保存・表示せず存在判定だけを記録した。設定失敗なのでRun作成処理へ到達せず、新規Model要求は行っていない。
- from Noneは通常tracebackから原因表示を抑止するが、`__context__`を消すものではない。Pydanticの`.errors()`やunsafe構築APIを安全化済みと扱わない。

### 実翻訳との区別

既存のsession 58094（Run `01a0d4f7-20bf-7ed0-b580-7ddd2cb6299d`）を複数回pollし、同じlive handleを確認した。SPLIT〜STRUCTURE完了後、TRANSLATEが継続している。このprocessには本Changeの未実装修正は含まれない。停止・再起動や並列のLLM/Embedding呼出はしていない。

### 残課題

- 全実装・回帰・公開境界・実機検証が未完了。別Changeの441 passedを本修正の証拠にしない。
- CLIの不正設定値の原因表示を解消し、実入口でmarkerが出ないことを確認する必要がある。
- common配置、独自Resume状態の統合、表内画像の曖昧時動作、先行Word/PDFの利用者目視という未回答/未解決事項を引き継ぐ。本提案はその方針を決定しない。

### 文書の品質検査

- OpenSpec status: proposal/design/tasksがdone、仕様変更なしのためspecsはskipped。実装完了ではない。
- `openspec validate reject-nonfinite-service-settings --strict`: valid。
- `uv run pytest -q tests/test_documentation.py`: 21 passed（0.25秒）。
- `git diff --check`: 指摘なし。製品Codeは未変更のため全製品Test・型検査・実機Gateは本提案ターンでは再実行していない。
