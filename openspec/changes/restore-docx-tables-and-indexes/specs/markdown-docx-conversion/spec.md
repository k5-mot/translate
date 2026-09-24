<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: MarkdownをDOCXへ変換できる
Systemは、読取り可能なMarkdownと有効な参照DOCXを受け取り、見出し、List、Code、Table、画像、Caption、FootnoteおよびLinkを保持したDOCXを生成しなければならない（SHALL）。表はWordの表として編集可能でなければならず、HTML断片を単なる本文段落へ変換してはならない（MUST NOT）。

#### Scenario: Markdown変換に成功する
- **WHEN** 利用者が有効なMarkdown、参照DOCXおよび出力先を指定する
- **THEN** Systemは要求された文書要素を持つ検証済みDOCXを生成する
- **AND** 入力に表がある場合、出力には対応するWord表と表題が含まれる

## ADDED Requirements

### Requirement: 生成一覧を利用できる
Systemは、本文の見出し、図題および表題から、目次、図一覧および表一覧を生成しなければならない（SHALL）。一覧の見出しはそれぞれ「目次」「図一覧」「表一覧」とし、生成時点で少なくとも1つの対象がある一覧は空であってはならない（MUST NOT）。各一覧の末尾には改ページを置かなければならない（MUST）。

#### Scenario: 見出しと図表がある文書を変換する
- **WHEN** 入力Markdownに見出し、図題または表題が含まれる
- **THEN** DOCXの表紙の後に「目次」「図一覧」「表一覧」がこの順序で現れる
- **AND** 対応する一覧に対象名が表示され、各一覧の後で本文が新しいページから始まる

#### Scenario: 対象がない一覧を変換する
- **WHEN** 図または表が存在しない
- **THEN** 該当一覧は空の動的フィールドを残さず、見出しと改ページだけを持つ

### Requirement: テンプレート番号を本文番号と重複させない
Systemは、参照DOCXのアウトライン番号がMarkdown本文に含まれる番号を二重表示しないようにしなければならない（MUST）。見出しの階層情報は目次生成に利用可能なまま保持しなければならない（SHALL）。

#### Scenario: 番号付き見出しを変換する
- **WHEN** Markdown見出し本文が番号を含み、参照DOCXのHeadingスタイルがアウトライン番号を定義している
- **THEN** DOCX本文では番号が一度だけ表示され、見出しはWordの目次対象として認識される

### Requirement: テンプレートスタイルを追跡できる
Systemは、使用する`template.docx`の各Wordスタイルについて、style ID、種別、表示名および継承元を`translate/templates/template-style.md`へ記録しなければならない（SHALL）。

#### Scenario: テンプレートスタイル一覧を検証する
- **WHEN** 保守者がテンプレートとスタイル一覧を比較する
- **THEN** 全style IDが一覧に一度ずつ存在し、テンプレートにないstyle IDは記載されない
