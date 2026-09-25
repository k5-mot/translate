<!-- markdownlint-disable MD013 MD041 -->

## 1. 診断JSONの直接上書き

- [x] 1.1 EvidenceStore保存を事前serializeと既存lock内の直接write/flush/fsyncへ変更し、新規File・既存File・短いJSONへの更新・一時File置換非使用をTestする。汎用atomic writerと子process要求Fileは変更しない（Q-FUNC/Q-MAIN）。
- [x] 1.2 単一lockのTestを実I/O境界へ更新し、resolve/exists/readからwrite/closeまでの排他、有限待機、正常終端を古いrunningが上書きしないことを確認する（Q-REL）。
- [x] 1.3 serialize/open前の失敗とtruncate/部分write/flush/fsync後の失敗を分けてTestし、例外伝播・lock解放・空/不正JSONのGate拒否・成功値が残っても保存失敗を成功としない呼出し経路を確認する（Q-REL/Q-USE）。
- [x] 1.4 所有する合成childを書込み途中で強制終了し、process終了とlock解放を確認する。残る部分JSONが成功を許可せず、Run/入力を削除せず診断Fileだけ次回更新できることをTestする（Q-REL/Q-SEC）。

## 2. 統合・互換性と受入

- [x] 2.1 Repository内の実EvidenceStore親子I/Oを12秒上限で3回逐次確認し、既存親子I/O/終端回収/公開convert Testを実行する。件数・終了handle・例外を記録し、1件でも共有障害が残れば未合格とする。cleanupは所有合成領域だけに限定する（Q-PERF/Q-PORT）。
- [x] 2.2 既存Evidence/schema・安全な項目・temp外配置・公開Run/fingerprintの回帰、全体pytest、Ruff check/format、ty、OpenSpec strictを実行し結果を記録する。無関係なFailureKind差分を混入させず、依存/新状態台帳追加0を確認する（Q-COMP/Q-SEC/Q-MAIN）。
- [x] 2.3 persist-detached-resume-terminal-evidenceとserialize-detached-evidence-ioのverificationに、原子的保存/旧版保持の廃止と本Changeへの対応を追記する。旧失敗証拠は残し、新方式の成功と混同しない（移行・廃止）。
- [ ] 2.4 simplify-translation-literal-checksと共通のreasoning OFF・逐次sample3翻訳→Microsoft Word PDF→比較Reviewに診断保存を接続し、実process終了・Evidence・成果物の整合を記録する。実E2Eと合成試験を区別し、正式verify/archiveの可否を判定する（運用/Q-FUNC/Q-REL）。
