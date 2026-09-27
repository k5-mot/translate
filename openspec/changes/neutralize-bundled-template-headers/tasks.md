<!-- markdownlint-disable MD041 -->

## 1. 同梱資産と契約Test

- [ ] 1.1 `tests/test_output_contract.py`に同梱テンプレートの全ヘッダー／フッターと有効な参照先を検査するTestを追加し、現資産の仮文言とPAGE欠落で失敗することを確認する（Q-FUNC）。
- [ ] 1.2 同梱`template.docx`のヘッダーを空、通常フッターをPAGEのみ、先頭フッターを空に修正する。Test成功、関係参照の整合性、styles等の対象外ZIP部品のhash不変を確認する（Q-FUNC/Q-MAINT）。
- [ ] 1.3 `template-style.md`へ同梱資産の表示内容と独自テンプレートの扱いを記載し、全110スタイルの一致および既存ドキュメントTest成功を確認する。

## 2. 変換経路の回帰検証

- [ ] 2.1 実Pandocで複数ページ用Markdownを変換し、有効ヘッダー／フッターの契約、本文文字列保持を検証する。未使用部品にだけPAGEがある場合を否定Testで検出する（Q-FUNC/Q-REL）。
- [ ] 2.2 独自のヘッダー／フッターを持つ参照DOCXで実変換し、内容保持と入力hash不変を検証する。既存の外部参照拒否・失敗時完全版保持Testも実行する（Q-COMP/Q-SEC/Q-REL）。
- [ ] 2.3 Ruff、format確認、ty、全pytest、OpenSpec strict validateを実行し、実行条件と結果を`verification.md`へ記録する。新規依存・旧形式互換・既存出力変更がないことも差分で確認する。

## 3. Word表示と受入判定

- [ ] 3.1 本変更で生成した複数ページDOCXをMicrosoft Wordで開き、利用者操作相当でPDF化する。先頭の空表示、以降の正しいページ番号、仮文言0件、新たな更新確認ポップアップ0件を確認し、DOCX/PDFのhashと観測結果を`verification.md`へ記録する（Q-INTERACTION/Q-SEC）。
- [ ] 3.2 新規sample3のreasoning OFF・逐次Translation→Word PDF→原文とのReviewを既存受入Changeで実施した結果を参照し、利用者の目視受入と未解決Findingを記録する。単体検証だけで全体受入を完了扱いしない。
- [ ] 3.3 全TaskとFindingを照合して同期・archive可否を記録する。移行不要、旧表示の廃止、既存成果物の保持を確認し、未検証事項があればarchiveを保留する。
