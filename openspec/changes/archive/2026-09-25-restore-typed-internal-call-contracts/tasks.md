## 1. 型付き呼出契約

- [x] 1.1 STRUCTUREの型付き署名と逐次再送を実装し、全引数、返却object、成功/再送成功/再送失敗/非接続エラーのcall数をTestで確認する（Q-FUNC/Q-REL）。
- [x] 1.2 Evidenceのgenerator/FailureRecord/Literal型を修復し、counterの入れ子・例外終了時復元と許可値/未知値のTestを通す（Q-SEC/Q-MNT）。

## 2. 全体検証と引継ぎ

- [x] 2.1 対象Ruff lint/format、全体ty、関連Testと全体pytestを実行して結果をverification.mdへ記録し、全体tyが0 diagnosticsになることを確認する。
- [x] 2.2 既存未commit差分・保存形式・依存に変更がないことを差分確認し、元監査の型エラー項目に解決証拠を追記する。未解決の他項目は保持する（Lifecycle/保守）。
