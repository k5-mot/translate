<!-- markdownlint-disable MD013 MD041 -->

## 1. 有限値検証と境界の実装

- [x] 1.1 `tests/test_settings.py`に4環境変数×NaN/±Infinity/overflow/0/負数/変換不能、直接Settingsの非有限値のTestを追加し、現行実装で非有限値拒否のTestが失敗することを記録する。外部Serviceは使わない
- [x] 1.2 既存settings.pyの4 fieldと`_positive_float`を導入済みPydanticのFiniteFloat/TypeAdapter制約へ対応付け、1.1を成功させる。標準floatの変換、固定理由のValueError、通常tracebackでの原因非表示を維持し、新Dependency/module/独自finite検証器を作らない
- [x] 1.3 分数秒、1,800/21,600秒、有限の大きな値、全角数字・指数等の既存受理表記と内部retry=0をTestし、入力値の意図しない書換え0を確認する。正常設定のfingerprint不変も検証する（Q-COMP）

## 2. 公開境界と自動品質検査

- [x] 2.1 CLI/UIの既存入口を使い、不正設定はRun作成・外部要求より前に拒否されることをTestする。.envを無効化し実認証情報を渡さない実CLI子processで、設定名/固定理由の表示と無効値marker非表示を検査する。例外文字列だけのTestで合格にしない（Q-SEC/Q-USE）
- [x] 2.2 Ruff lint/format、ty、全pytest、OpenSpec strict validation、git diff --checkを実行し、件数、実行commit/差分、追加関数の目的説明、既存API委譲の確認結果をverification.mdへ記録する

## 3. 実機検証と指摘解消

- [ ] 3.1 実行中の先行session 58094の終端と後続検証の実行状況をlive handleで確認し、並列Model要求を避けて修正後Codeのprocessでsample3.pdfを実translationする。Run ID、入力/成果物hash、終了状態、長時間設定の維持を記録する
- [ ] 3.2 自分で起動した非表示Microsoft Wordで生成DOCXをPDF化し、Word/PDFを利用者へ提示する。その生成PDFと元sample3.pdfを実Comparison Reviewで逐次比較し、report・終了状態・ユーザ目視と残課題を記録する。PDF変換は製品機能にしない
- [ ] 3.3 SETTINGS-FINITE-001と元timeout Changeへ実装・自動/実機証拠を対応付け、すべてのTaskと要求に基づき正式verifyする。未解決事項がない場合だけarchiveし、PR/CI後にmainへマージ・originへpushする。.agents、サンプル、実行生成物、無関係な差分はcommitに含めない
