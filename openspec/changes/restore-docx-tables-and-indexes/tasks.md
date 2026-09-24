<!-- markdownlint-disable MD041 -->

## 1. 仕様・テンプレート資料

- [x] 1.1 `markdown-docx-conversion` Delta Specを検証し、表・一覧・改ページ・番号重複防止のScenarioが`openspec validate --strict`を通ることを確認する
- [x] 1.2 `template.docx`の`styles.xml`を読み取り、全style ID・種別・表示名・継承元を`translate/templates/template-style.md`へ列挙する

## 2. Markdown構造の生成

- [x] 2.1 表BlockをPandoc grid tableへ変換し、caption、header、セル内改行、複数行を保持するUnit Testを追加する
- [x] 2.2 表の不正shapeを既存検証で拒否し、正常な表がPandoc DOCXの`w:tbl`になるIntegration Testを追加する

## 3. DOCX一覧・見出し正規化

- [x] 3.1 変換済みDOCXから見出し・図題・表題を取得し、TOC/図一覧/表一覧のSDTを日本語見出し付き静的段落へ置換する
- [x] 3.2 各一覧の直後へ改ページを挿入し、表紙→目次→図一覧→表一覧→本文の順序と空一覧の挙動をXML Testで固定する
- [x] 3.3 `styles.xml`のHeading1～Heading9からアウトラインnumPrだけを除去し、outlineLvlと目次対象を維持する
- [x] 3.4 dirty field、updateFields、外部ファイルrelationshipおよび表紙caption拒否の既存契約を回帰Testで確認する

## 4. 実成果物検証

- [x] 4.1 `pytest tests/test_output_contract.py`、Ruffおよび型検査を実行し、全DOCX構造Testが成功することを確認する
- [x] 4.2 sample3の既存Runまたは新規RunからDOCXを再生成し、`w:tbl`数、一覧テキスト、改ページ、重複しない見出し番号をXML/plain textで記録する
- [ ] 4.3 利用者がWordでDOCXを開き、表・目次・図一覧・表一覧・改ページ・見出しを目視確認した後、OpenSpec Changeをverify/archive可能と判定する

## 5. Verify指摘への対応

- [x] 5.1 見出し/本文をまたぐ縦結合の列位置と結合を保持し、当該表の繰返し見出しを無効・見出しセルを太字にする回帰Testを追加してV-C2を修正する
- [x] 5.2 空隅セル・複数見出し行・本文の行見出しを保持する実Pandoc/DOCX Testを追加してV-W2を修正する
- [x] 5.3 表セルとCaptionのLink/Code/marks/改行を保持する実Pandoc/DOCX Testを追加してV-W1を修正する
- [x] 5.4 追加Test・Ruff・型検査と全体Testを実行し、成功/失敗・未検証範囲をverification.mdへ記録する
- [ ] 5.5 sample3.pdfで公開translationを実行し、Microsoft Wordで生成DOCXをPDF化してから入力PDFと生成PDFの公開reviewを実行し、順序と実成果物を正式verifyの証拠として記録する
