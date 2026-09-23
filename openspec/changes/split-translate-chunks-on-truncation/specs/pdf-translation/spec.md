<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: PDFを日本語DOCXへ変換できる

Systemは、TRANSLATEのstructured outputが`finish_reason=length`となり、同じchunkの推論無効化fallbackも出力上限へ到達した場合、対象chunkを決定的に分割し、各sub-chunkを推論無効化で逐次処理しなければならない（MUST）。分割は最大2段階または1単位までに制限し、ID対応およびprotected fragment検証を通過した応答だけを適用しなければならない（MUST）。分割経路でも完全な応答を得られない場合、Systemは部分翻訳を公開せず、既存の診断とResume可能なFailureを保持して停止しなければならない（MUST）。

#### Scenario: 出力枯渇後の分割で翻訳を継続する

- **WHEN** 通常要求と同じchunkの推論無効化fallbackが`output-truncated`となり、分割したsub-chunkが完全な応答を返す
- **THEN** Systemはsub-chunkの順序とIDを維持して翻訳を適用し、同時要求なしに次の未完了単位へ進む

#### Scenario: PDF翻訳に成功する

- **WHEN** 利用者が読取り可能な英語PDFと有効な設定を指定する
- **THEN** SystemはRunの公開成果物として検証済み日本語DOCXを生成する

#### Scenario: 読取り不能なPDFを拒否する

- **WHEN** 利用者が空、暗号化済み、破損または読取り不能なPDFを指定する
- **THEN** Systemは入力Errorを示し、DOCXを公開しない

#### Scenario: 分割上限でも出力が枯渇する

- **WHEN** 最大2段階のsub-chunk要求または1単位要求でも完全な応答を得られない
- **THEN** Systemはstage、cause、`output-truncated`、finish reasonおよび数値token usageだけをFailureへ保存し、部分訳、raw response、原文およびcredentialを公開しない

#### Scenario: 分割fallbackのResume

- **WHEN** 分割途中でRunが停止し、利用者が同じRun IDを明示してResumeする
- **THEN** Systemは完了済みTask/chunkを再実行せず、失敗した未完了単位から逐次処理を継続する
