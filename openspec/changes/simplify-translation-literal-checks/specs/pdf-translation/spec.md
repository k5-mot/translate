<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: 文書構造と保護対象を保持する
Systemは、見出し、段落、List、Code、Table、Figure、Caption、Footnote、Link、文字装飾および読取り順を日本語成果物へ保持しなければならない（SHALL）。文書構造として識別されたCodeの内容とLink先を保持しなければならない（MUST）。本文中の固有名詞・略語・一般識別子について、表記の完全一致だけを根拠に欠落と判定したり翻訳を停止したりしてはならない（MUST NOT）。明確なURL・ファイル名の欠落または変更は品質警告として記録し、その警告だけを理由に成果物公開を拒否してはならない（MUST NOT）。数値・単位・意味の保持は既存の品質検査の対象とし、表記一致の緩和を翻訳単位の欠落や不正応答の受入へ拡張してはならない（MUST NOT）。

#### Scenario: 複数列と図表を含む文書を変換する
- **WHEN** 入力PDFが複数列、欄外要素、重なる座標、分割Table、FigureおよびCaptionを含む
- **THEN** Systemは決定的な読取り順と再構成済みの文書構造を持つ日本語DOCXを生成する

#### Scenario: 略語の自然な訳を受理する
- **WHEN** 本文のU.S.が米国へ翻訳され、対象の訳文が揃っている
- **THEN** Systemはこの表記差だけによる保護文字列欠落の指摘・再試行・停止を行わない

#### Scenario: 明確なURLまたはファイル名の変更を警告する
- **WHEN** 本文のhttps://example.org/manualまたはmanual.pdfが訳文から欠落するか別の値になる
- **THEN** Systemは対象と理由を品質警告へ記録して既存のReviewへ渡し、警告だけでは停止しない

#### Scenario: 保護対象を維持する
- **WHEN** 文書構造としてCodeとLink先を取得でき、翻訳または修正を行う
- **THEN** SystemはCode内容とLink先を保持し、Linkの表示文章は翻訳できる

### Requirement: 翻訳Backendを選択できる
Systemは、LLM BackendまたはLibreTranslate Backendを選択でき、どちらも同じ公開成果物契約を満たさなければならない（SHALL）。LLM Backendは翻訳Rule、該当用語および有効な参照検索結果を利用しなければならない（MUST）。両Backendは本文の文字列を独自の保護記号として返すことを成功条件とせず、同じ事後品質検査を適用しなければならない（MUST）。

#### Scenario: LLM Backendを使用する
- **WHEN** 利用者がLLM Backendを選択する
- **THEN** Systemは翻訳Rule、用語および利用可能な参照検索結果を適用して日本語訳を生成する

#### Scenario: LibreTranslate Backendを使用する
- **WHEN** 利用者がLibreTranslate Backendを選択する
- **THEN** Systemは保護記号の応答を要求せず、同じ文書構造保持・品質警告契約を持つ日本語成果物を生成する

### Requirement: 翻訳結果を検査してから公開する
Systemは、決定的検査と意味Reviewを行い、指摘がある翻訳単位だけに修正候補を生成し、検証に合格した候補だけを採用しなければならない（SHALL）。修正または検証が失敗した単位は修正前訳へ戻し、警告として記録しなければならない（MUST）。固有名詞・略語の表記一致専用の検査段階を追加してはならない（MUST NOT）。URL・ファイル名の品質警告は確認候補であり、検出だけを理由に翻訳失敗へ変換してはならない（MUST NOT）。

#### Scenario: 修正候補を採用する
- **WHEN** 修正候補が指摘を解消し、新しい欠落、追加または誤訳を生じない
- **THEN** Systemは候補を最終採用訳として使用する

#### Scenario: 修正または検証に失敗する
- **WHEN** 修正生成または検証が対象単位で失敗する
- **THEN** Systemは修正前訳を保持し、対象IDと理由を警告へ記録して残りの文書処理を継続する

#### Scenario: 表記警告と応答不備を区別する
- **WHEN** URL変更の警告を含む正常応答と、翻訳対象が欠落した不正応答をそれぞれ受け取る
- **THEN** Systemは前者を既存品質検査へ進め、後者の既存拒否条件は維持する

### Requirement: 翻訳の機能品質を検証できる
Q-FUNC（ISO/IEC 25010 機能適合性）として、Systemは本Capabilityの全Scenarioを自動Testで実行可能にし、正常系・異常系とも成功率100%を満たさなければならない（MUST）。Q-RELとして、両Backendの合成fixtureで略語表記差だけによる停止とURL・ファイル名warningだけによる停止を0件にしなければならない（MUST）。

#### Scenario: Capability Testを実行する
- **WHEN** 保守者がPDF翻訳CapabilityのTest suiteを実行する
- **THEN** 表紙、両Backend、構造保持、品質警告および応答不備の検査Scenarioがすべて成功する
