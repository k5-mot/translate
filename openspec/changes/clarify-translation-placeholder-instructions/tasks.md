<!-- markdownlint-disable MD013 MD041 -->

## 1. 翻訳指示と回帰検査

- [ ] 1.1 配布translation-rules.mdにtarget/文脈の区別、全IDの非空訳、同じID内の保護記号の無変更・一対一保持を追加する。実read_rulesで読み込むTestで各指示が欠けた旧ルールでは失敗し、新ルールで成功することを確認する（Q-FUNC/Q-MAINT）。
- [ ] 1.2 既存の翻訳出力Testへ合成の本文中URL・識別子、記号のみ、複数記号を追加し、通常/OFF、検証retry、切断分割後の送信に配布ルールが届き、復元結果が同じIDに保持されることを確認する。欠落・重複・未知記号・別ID移動の拒否と、有限回数・逐次順序・公開前失敗の既存Testも通す（Q-FUNC/Q-REL/Q-PERF/Q-SEC）。
- [ ] 1.3 ルール変更が公開fingerprintとWorkflow識別へ反映されることを既存Testで確認し、不足分だけ追加する。新しい互換性管理を作らず、Qdrant状態を識別へ含めない（Q-COMP/移行）。
- [ ] 1.4 関連Test、全体pytest、ruff check、ruff format --check、ty check、OpenSpec strict、git diff --checkを実施し、実行時の既存未コミット差分と結果をverification.mdに記録する。今回の差分だけをcommitする（Q-MAINT/Q-PORT/供給）。

## 2. OFFでの実成果物検証

- [ ] 2.1 旧実処理の終端を確認し、sample3.pdfをOFF・非対話・resumeなし・未使用export先で新規翻訳する。Code/入力hash/ルールhash、新旧Run ID、所要時間、取得可能な実効推論設定とtoken、終端結果を記録する。成功時は第2ページを含む全文の対象IDと保護値の対応を確認し、失敗時は成果物非公開とCheckpoint保持を記録して未完了とする（Q-FUNC/Q-REL/Q-PERF/Q-SEC/運用）。
- [ ] 2.2 成功した新規DOCXの表紙・本文・表・Caption・一覧・番号・改ページを検査し、Microsoft Wordで別PDFへ変換する。成果物hashと実行順を記録し、DOCX/PDFを利用者へ提示して目視結果を記録する。旧成果物で代用せず、PDF化を製品機能へ追加しない（Q-FUNC/Q-USE/供給）。
- [ ] 2.3 原本sample3.pdfと2.2のPDFをOFFの新規公開Reviewで逐次比較し、実効設定・report・終端結果を記録する。代表Findingを原本/DOCX/PDFと照合し、既知ALIGN等の問題を区別する。終了コード0だけで受入合格にしない（Q-FUNC/Q-REL）。

## 3. 正式検証と引継ぎ

- [ ] 3.1 実要求・Test・実成果物を対応付けて正式verifyし、TRANSLATE-PROTECTED-OFF-001と関連Changeへ同じ検証証拠を参照する。未達条件を残し、必要条件が揃った場合だけarchive可と記録する。archive時はskip_specsに従いDelta同期なしを確認する（Q-MAINT/保守・廃止）。
- [ ] 3.2 `.agents`、サンプル、outputs/runs、秘密、無関係な差分がcommitにないことを確認する。全体の受入条件が揃ってからPR/CI、mainへのmerge、originへのpushの結果を記録する（Q-SEC/供給）。
