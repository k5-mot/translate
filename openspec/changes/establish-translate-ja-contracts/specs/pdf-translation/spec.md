<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## Purpose

利用者が英語PDFを入力し、原文の構造、図表、保護対象および表紙を維持した検証済み日本語DOCXを取得できるようにする。

## ADDED Requirements

### Requirement: PDFを日本語DOCXへ変換できる
Systemは、読取り可能な英語PDFを受け取り、日本語DOCXと診断用Artifactを生成しなければならない（SHALL）。空、暗号化済み、破損または読取り不能なPDFは入力Errorとして拒否しなければならない（MUST）。

#### Scenario: PDF翻訳に成功する
- **WHEN** 利用者が読取り可能な英語PDFと有効な設定を指定する
- **THEN** SystemはRunの公開成果物として検証済み日本語DOCXを生成する

#### Scenario: 読取り不能なPDFを拒否する
- **WHEN** 利用者が空、暗号化済み、破損または読取り不能なPDFを指定する
- **THEN** Systemは入力Errorを示し、DOCXを公開しない

### Requirement: 文書構造と保護対象を保持する
Systemは、見出し、段落、List、Code、Table、Figure、Caption、Footnote、Link、文字装飾および読取り順を日本語成果物へ保持しなければならない（SHALL）。URL、Path、Command、Code、識別子、数値および単位を翻訳によって欠落または意図せず変更してはならない（MUST NOT）。

#### Scenario: 複数列と図表を含む文書を変換する
- **WHEN** 入力PDFが複数列、欄外要素、重なる座標、分割Table、FigureおよびCaptionを含む
- **THEN** Systemは決定的な読取り順と再構成済みの文書構造を持つ日本語DOCXを生成する

#### Scenario: 保護対象を維持する
- **WHEN** 入力PDFがURL、Path、Command、Code、識別子、数値および単位を含む
- **THEN** Systemは検査可能な対応関係を保ち、欠落または意図しない変更がある場合は成果物公開前に失敗する

### Requirement: 翻訳Backendを選択できる
Systemは、LLM BackendまたはLibreTranslate Backendを選択でき、どちらも同じ公開成果物契約を満たさなければならない（SHALL）。LLM Backendは翻訳Rule、該当用語および有効な参照検索結果を利用し、LibreTranslate Backendは保護対象を復元・検証しなければならない（MUST）。

#### Scenario: LLM Backendを使用する
- **WHEN** 利用者がLLM Backendを選択する
- **THEN** Systemは翻訳Rule、用語および利用可能な参照検索結果を適用して日本語訳を生成する

#### Scenario: LibreTranslate Backendを使用する
- **WHEN** 利用者がLibreTranslate Backendを選択する
- **THEN** Systemは保護対象を維持した同一形式の日本語成果物を生成する

### Requirement: 表紙を一度だけ出力する
Systemは、入力PDFの第1ページを表紙画像として出力し、同じページの本文をMarkdownおよびDOCXへ重複出力してはならない（MUST NOT）。表紙画像を生成または検証できない場合は、本文だけの成果物へ縮退せずRunを停止しなければならない（MUST）。

#### Scenario: 表紙を画像として出力する
- **WHEN** 入力PDFの第1ページから有効な表紙画像を生成できる
- **THEN** Systemは表紙画像を成果物の先頭へ一度だけ配置し、第1ページ本文を除外する

#### Scenario: 表紙生成に失敗する
- **WHEN** 第1ページの画像化または画像検証に失敗する
- **THEN** SystemはCOVERで停止し、表紙なしのDOCXを公開せず、同じRunをResume可能に保つ

### Requirement: 翻訳結果を検査してから公開する
Systemは、決定的検査と意味Reviewを行い、指摘がある翻訳単位だけに修正候補を生成し、検証に合格した候補だけを採用しなければならない（SHALL）。修正または検証が失敗した単位は修正前訳へ戻し、警告として記録しなければならない（MUST）。

#### Scenario: 修正候補を採用する
- **WHEN** 修正候補が指摘を解消し、新しい欠落、追加または誤訳を生じない
- **THEN** Systemは候補を最終採用訳として使用する

#### Scenario: 修正または検証に失敗する
- **WHEN** 修正生成または検証が対象単位で失敗する
- **THEN** Systemは修正前訳を保持し、対象IDと理由を警告へ記録して残りの文書処理を継続する

### Requirement: 翻訳の機能品質を検証できる
Q-FUNC（ISO/IEC 25010 機能適合性）として、Systemは本Capabilityの全Scenarioを自動Testで実行可能にし、正常系・異常系とも成功率100%を満たさなければならない（MUST）。

#### Scenario: Capability Testを実行する
- **WHEN** 保守者がPDF翻訳CapabilityのTest suiteを実行する
- **THEN** 表紙、Backend、構造保持、保護対象および検査に関する全Scenarioが成功する

