<!-- markdownlint-disable MD013 MD041 -->

## 1. 段組判定の安定化

- [x] 1.1 既存POSITION Testへ幅中央値変化と左端標本消失の二つの3要素fixtureを追加し、修正前に二回目の順序反転を再現する。初回/二回目の結合件数と内容不変も確認する（Q-FUNC）
- [x] 1.2 代表位置を維持したまま、同じ代表ページの全有効provを幅・左端の両方の段組統計に利用する。元から複数provの要素、重複座標、欄外、同位置、座標欠損を含むTestで初回/二回目/三回目の文書と実NORMALIZE→LOADの順序が一致することを確認する。既存座標変換・中央値・安定sortを再利用する（Q-REL/Q-MNT）
- [x] 1.3 本文と表の結合候補で代表ページ一致も確認し、末尾だけ同じページの曖昧な候補は未変更で保持＋警告とする。複数ページprovの合成fixtureでページ別標本と内容の欠落0件、通常の同一ページ連鎖結合の維持を確認する

## 2. 回帰・補助検証

- [x] 2.1 保存済みsample3 MERGE Artifactを読取り、一時領域でPOSITIONを二回/三回適用して全documentとLOAD順序を比較する。元hash不変と順序差分0件を確認し、既存の本文/表/Caption/参照保持・Review/登録の回帰を実行する。保存済みArtifact検証を新規実E2Eと区別して記録する
- [x] 2.2 Ruff check/format、ty、全pytest、OpenSpec strict、git diff --checkを実行する。関数の目的説明、既存API再利用、追加Dependency/Module/永続制御状態/外部要求0件、reportへの本文・秘密の追加転記0件を確認し、Code版と結果をverification.mdへ記録する（Q-COMP/Q-SEC）

## 3. 実受入と供給

- [ ] 3.1 LLM接続回復を確認してからsample3.pdfの新規推論OFF・逐次Translation→Microsoft Word PDF→原本とのComparison Reviewを行い、段落・図表・一覧の読み順、終了状態、設定と入出力hashを記録する。未実行/失敗なら未完了を維持する
- [ ] 3.2 Word/PDFを利用者へ提示して目視確認を得て、全Scenario/Taskの証拠で正式verify・同期/archive可否を判定する。PR/CI→main merge/pushは未解決指摘と受入を確認後に実施し、`.agents`・入力・PDF/DOCX・実行生成物を除外する（供給・運用・保守・廃止）
