<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: PDFを日本語DOCXへ変換できる

Systemは、読取り可能な英語PDFを受け取り、日本語DOCXと診断用Artifactを生成しなければならない（SHALL）。TRANSLATEのsplit sub-chunkではURL、Path、Command、Code、識別子、数値および単位を一意placeholderで保護し、structured response後に原文fragmentへ復元しなければならない（MUST）。復元後の完全なID対応およびprotected fragment検証を満たす応答だけを適用し、満たせない場合は部分翻訳を公開せずResume可能なFailureへ停止しなければならない（MUST）。

#### Scenario: split sub-chunkで保護fragmentを復元する

- **WHEN** split fallbackの応答がplaceholderを含み、復元後にID対応とprotected fragment検証を満たす
- **THEN** Systemは元のfragmentを保持した翻訳だけをmappingへ適用し、逐次処理を継続する

#### Scenario: 保護fragmentの復元に失敗する

- **WHEN** 有限retry後もplaceholderまたはprotected fragmentが欠落する
- **THEN** Systemは`ProtectedFragmentMissing`と安全な診断だけを保持し、raw response、prompt、原文および部分翻訳を公開しない

#### Scenario: PDF翻訳に成功する

- **WHEN** 利用者が読取り可能な英語PDFと有効な設定を指定する
- **THEN** SystemはRunの公開成果物として検証済み日本語DOCXを生成する

#### Scenario: 読取り不能なPDFを拒否する

- **WHEN** 利用者が空、暗号化済み、破損または読取り不能なPDFを指定する
- **THEN** Systemは入力Errorを示し、DOCXを公開しない
