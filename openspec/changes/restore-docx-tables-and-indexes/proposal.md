<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実際の翻訳成果物で、Doclingが抽出した表がDOCXでは本文へ現れず、Pandocの動的な目次・図一覧・表一覧もキャッシュされないため空欄になっています。さらに、英語の一覧見出し、改ページ不足、テンプレートの自動アウトライン番号が利用者の期待するWord成果物と一致しません。

## What Changes

- 表をPandocがDOCXの`w:tbl`として解釈できるMarkdown表へ変換し、表題と表一覧の対象を保持する。
- 目次、図一覧、表一覧の見出しをそれぞれ「目次」「図一覧」「表一覧」とし、生成時点で静的なエントリを格納して空欄をなくす。
- 各一覧の直後に必ず改ページを置き、表紙画像、一覧、本文の順序を固定する。
- テンプレートの見出しスタイルにある自動アウトライン番号を本文の数字と二重に表示しない。
- `translate/templates/template-style.md` に`template.docx`のスタイルID、種別、表示名および継承元を列挙する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `markdown-docx-conversion`: 表、静的な日本語の目次・図一覧・表一覧、改ページおよび見出し番号の重複防止をDOCX公開契約へ追加する。

## Impact

`translate/tasks/markdown.py`、`translate/adapters/pandoc.py`、`tests/test_output_contract.py`およびテンプレート文書のドキュメント化に影響する。新しい実行時依存は追加しない。DOCXのOOXML正規化で一覧のキャッシュ段落、改ページ、見出しスタイルを決定的に生成する。

## Stakeholders and Lifecycle Impact

- 運用者はWordを開いた時点で一覧を確認でき、フィールド更新や外部参照のダイアログに依存しない。
- 保守者はテンプレート更新時に`template-style.md`と実ファイルの差分を検証する。
- 既存Runの入力・チェックポイント形式は変更しない。生成済みDOCXの再生成だけで適用でき、旧成果物の自動移行は行わない。
- 廃止時は生成されたDOCXと一覧の静的テキストを通常の成果物削除ポリシーに従って削除する。

## Quality Considerations

- Q-FUNC（機能適合性）: 表が1つ以上あるMarkdownから`w:tbl`を1つ以上生成し、3種類の一覧が非空で所定の順序と改ページを持つことを自動検証する。
- Q-REL（信頼性）: 既存のatomic公開・不正DOCX拒否を維持し、正規化に失敗した場合は既存成果物を上書きしない。
- Q-USE（使用性）: 日本語見出しと、Wordのアウトライン番号と本文番号が重複しない表示を実DOCXで確認する。
- Q-MNT（保守性）: テンプレートの全スタイルを再現可能なMarkdown一覧にし、テストで表記規則を固定する。
