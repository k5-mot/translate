<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: 文書構造と保護対象を保持する
Systemは、見出し、段落、List、Code、Table、Figure、Caption、Footnote、Link、文字装飾および読取り順を日本語成果物へ保持しなければならない（SHALL）。URL、Path、Command、Code、識別子、数値および単位を翻訳によって欠落または意図せず変更してはならない（MUST NOT）。通常chunkと分割fallback chunkのいずれでも、Systemは保護対象をplaceholderとしてLLMへ渡し、応答を正規化・復元してから採用しなければならない（SHALL）。

#### Scenario: 複数列と図表を含む文書を変換する
- **WHEN** 入力PDFが複数列、欄外要素、重なる座標、分割Table、FigureおよびCaptionを含む
- **THEN** Systemは決定的な読取り順と再構成済みの文書構造を持つ日本語DOCXを生成する

#### Scenario: 通常chunkで保護対象を維持する
- **WHEN** 通常の高推論chunkがURL、Path、Command、Code、識別子、数値または単位を含む
- **THEN** Systemはplaceholderを介して原文保護値を復元し、欠落・改変した応答を採用しない

#### Scenario: 保護対象を維持する
- **WHEN** 入力PDFがURL、Path、Command、Code、識別子、数値および単位を含む
- **THEN** Systemは検査可能な対応関係を保ち、placeholderの表記揺らぎを復元できない場合は成果物公開前に失敗する

#### Scenario: 分割fallback chunkで保護対象を維持する
- **WHEN** 出力枯渇後にchunkを分割して翻訳する
- **THEN** Systemは各sub-chunkのplaceholderを一対一に復元し、欠落・重複・未知tokenを成果物公開前に失敗として扱う

### Requirement: 翻訳結果を検査してから公開する
Systemは、決定的検査と意味Reviewを行い、指摘がある翻訳単位だけに修正候補を生成し、検証に合格した候補だけを採用しなければならない（SHALL）。修正または検証が失敗した単位は修正前訳へ戻し、警告として記録しなければならない（MUST）。通常chunkまたは分割fallback chunkで保護対象の復元に失敗した場合は、有限回の再試行後にTRANSLATEを停止し、原文保護値やLLM生応答を診断証跡へ記録してはならない（MUST NOT）。

#### Scenario: 修正候補を採用する
- **WHEN** 修正候補が指摘を解消し、新しい欠落、追加または誤訳を生じない
- **THEN** Systemは候補を最終採用訳として使用する

#### Scenario: 修正または検証に失敗する
- **WHEN** 修正生成または検証が対象単位で失敗する
- **THEN** Systemは修正前訳を保持し、対象IDと理由を警告へ記録して残りの文書処理を継続する

#### Scenario: 通常chunkの保護対象復元が有限回で失敗する
- **WHEN** 通常chunkの応答から保護対象を復元できず、規定回数の再試行も失敗する
- **THEN** SystemはTRANSLATEを停止し、RunをResume可能な失敗状態に保持し、失敗証跡には`ProtectedFragmentMissing`と対象IDだけを記録する
