<!-- markdownlint-disable MD013 MD041 -->

## 1. 計測表示の障害境界

- [x] 1.1 tests/test_timing_contract.pyへ成功/失敗×BrokenPipeError/閉じたstream/通常OSErrorの回帰Testを追加し、現実装で結果または元例外が置換されることを確認する。外部Serviceは呼ばない。
- [x] 1.2 BaseTask、CLI、UIの計測printだけを保護し、回帰Testで戻り値・元例外identity・本体呼出1回を確認する。通常の出力形式と既存47 Testを維持し、新Module・依存・保存状態を追加しない。
- [x] 1.3 CLI/UIの__main__境界を動的に検証し、成功・本体失敗・SystemExitの終了状態保持、KeyboardInterrupt伝播、成果物/Checkpoint保存失敗の非抑制を確認する。計測表示で新たに本文・秘密を出力しないことを検査する。

## 2. 統合検証と受入

- [x] 2.1 関連Test、全pytest、Ruff/format、ty、OpenSpec strict、diff検査を実行してverification.mdへ結果と範囲を記録する。Q-REL/Q-COMP/Q-MNT/Q-SECの証拠を対応付ける。
- [ ] 2.2 適用後のsample3新規translation→Microsoft Word PDF→原本とのreviewをreasoning OFF・逐次実行で検証し、Run ID・成果物hash・終端結果を記録する。適用前から稼働するRunを本修正の証拠へ流用しない。
- [ ] 2.3 Word/PDFを利用者に提示し目視結果を記録する。TASK-TIMING-001の解消を証拠で確認して元verificationへ追記し、他の未解決事項と区別して正式verify・archive可否を判定する。データ移行・削除なし、.agentsと実生成物をcommitへ含めないことを確認する。
