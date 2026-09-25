<!-- markdownlint-disable MD013 MD041 -->

## 1. 翻訳と品質警告の簡素化

- [ ] 1.1 LLM通常・retry・切断再分割の本文marker生成/復元/完全一致検査と専用Ruleを除去し、U.S.→米国を受理するTest、対象ID欠落・空応答・切断回復Testを成功させる（Q-FUNC/Q-REL）。
- [ ] 1.2 LibreTranslateの本文marker処理を除去し、略語の自然な訳・出力件数不一致・サービス障害の回帰Testで同じ契約を確認する（Q-FUNC/Q-COMP）。
- [ ] 1.3 共通CHECKを明確なURL/既知拡張子のファイル名warningへ限定し、U.S./U.K./U.S.A./固有名詞/camelCaseの誤指摘0、manual.pdf変更のwarning、数値/否定/用語集等の既存検査をTestする（Q-FUNC/Q-USE）。
- [ ] 1.4 構造化Codeを両Backend・FIXの書換えから除外し、Link先とCode内容が翻訳→修正→Markdown/DOCXで保持され、Link表示ラベルは翻訳されることをTestする（Q-FUNC）。
- [ ] 1.5 CHECKのURL/ファイル名warningが対象ID・根拠付きで保存され、既存Reviewへ渡り、比較reportにも残ることと、警告だけでは停止しないことを統合Testする。専用LLM call追加0を確認する（Q-REL/Q-PERF/Q-USE）。

## 2. 互換性と廃止整理

- [ ] 2.1 既存fingerprint/Workflow versionへの検査契約変更の反映を確認し、両Backend・比較の旧設定/旧契約との不正なResume再利用を回帰Testで防ぐ。Rule hashと既存version項目を使用し、新互換性機構は追加しない（Q-COMP）。
- [ ] 2.2 設計に列挙した旧4 Changesのverificationへ廃止要求/残存要求/後継対応を記録し、旧marker Deltaを再同期しない扱いを確定する。履歴・旧Runを保持し、廃止専用Testを削除してもID/切断/安全性Testが残ることを確認する（廃止・保守/Q-MAIN）。
- [ ] 2.3 全体pytest、Ruff check/format、ty、OpenSpec strictと秘密情報回帰を実行し、既存の無関係な差分を区別して実行commit・結果をverification.mdへ記録する。新依存・独立再開台帳追加0を差分で確認する（Q-SEC/Q-MAIN）。

## 3. 実成果物の受入

- [ ] 3.1 overwrite-diagnostic-json-in-placeの保存回帰確認後、sample3.pdfをreasoning OFF・逐次・新規Runで翻訳し、実送信設定、終了状態、呼出し数、所要時間、生成DOCXと原本のhashを記録する。旧Runを再利用しない（Q-FUNC/Q-PERF/Q-PORT）。
- [ ] 3.2 同じDOCXをMicrosoft WordでPDF化し、原PDFと生成PDFで比較Reviewを実行する。入力の同一性・reportの根拠・警告を確認し、OFFと同時Model要求1を記録する。診断保存Changeとは同じE2E証拠を共有する（Q-FUNC/Q-USE）。
- [ ] 3.3 DOCX/PDFを利用者へ提示し、表・図・表紙・一覧・見出しも含む目視結果を記録する。本Changeの受入と残る別件を分離し、正式verify/仕様同期/archiveへ進めるか判定をverification.mdに残す（供給・運用・保守）。
