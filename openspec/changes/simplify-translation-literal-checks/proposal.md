<!-- markdownlint-disable MD013 MD041 -->

## Why

本文の文字列を保護記号へ置換する現行処理は、U.S.等の略語も識別子として扱い、記号の欠落で実PDF翻訳を停止している。利用者が承認した「固有名詞・略語の厳密照合は不要、明確なURL・ファイル名の変更は品質チェックの警告に留める」契約へ簡素化する。

## What Changes

- **BREAKING**: 両翻訳Backendで本文の保護記号置換・復元・文字列完全一致を必須とする停止判定を廃止する。
- 固有名詞・略語・一般識別子の形状一致だけでは欠落Findingを作らない。明確なURL・ファイル名の変更は既存CHECKのwarningとし、その警告だけでは停止しない。
- 数値・単位・否定・条件・用語集などの既存品質チェック、対象ID・応答の欠落検査、有限retryと切断回復は維持する。新たなLLM判定段階は追加しない。
- 文書構造として取得したCodeとLink先は本文の文字列推測とは区別して保持する。
- 旧保護機能Changeの未完了受入と仕様差分を後継契約へ対応付け、旧要求の再同期による復活を防ぐ。過去の失敗証拠は保持する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: 本文の厳密保護から事後の品質警告へ変更し、両Backendの契約を揃える。
- `comparison-review`: 共通CHECKによるURL・ファイル名警告と、略語の表記差だけでは欠落としない範囲を明確にする。

## Impact

対象はtasks/translate.py、translate_lite.py、check.py、fix.pyの構造化Code保持境界、翻訳Rule、関連TestとOpenSpec。既存REVIEW/FIX/VERIFYへ接続し、新Module・依存・専用LLM call・並列化・独立再開台帳は追加しない。公開CLI/UI引数と出力形式は維持する。

## Stakeholders and Lifecycle Impact

- 利用者・運用: warning付き成果物は無誤訳保証ではない。reasoning OFF・逐次の新規sample3翻訳、Microsoft WordでPDF化、入力PDFとのReviewと利用者目視で受け入れる。
- 移行・保守: Rule変更を既存fingerprintへ反映し、旧結果を新契約の合格証拠へ流用しない。旧Runは保持する。
- 廃止: 本文marker専用実装・指示・Testを除去し、ID/空応答/切断/安全な障害記録のTestは残す。
- 取得・供給: 外部サービス契約や追加Packageの取得はない。成果物提供形式も変更しない。

## Quality Considerations

| ID / 特性 | 目標・確認方法 |
| --- | --- |
| Q-FUNC 機能適合性 | 両Backendで略語の自然な訳を受理し、明確なURL/ファイル名変更をwarningとして検出する合成Scenario成功率100% |
| Q-REL 信頼性 | 警告だけで停止する件数0、対象欠落等の既存失敗Test成功率100% |
| Q-PERF 性能効率 | 専用LLM call追加0、LLM/Embedding同時実行数1。実E2E時間と呼出し数を記録するが高速化率は保証しない |
| Q-COMP 互換性 | 両Backend同一契約、旧Rule fingerprint不一致時のResume拒否をTest |
| Q-USE 利用時の分かりやすさ | 警告に対象ID・理由を保持し、実Review reportで確認 |
| Q-SEC Security | 原文/秘密を例外・公開失敗情報へ追加しない。既存sentinel Testを回帰 |
| Q-MAIN 保守性 | marker専用分岐削除、新依存0、関数コメント・Ruff・型検査・全Test成功 |
| Q-PORT 移植性 | Windowsで実E2E、OS専用の翻訳処理追加0 |

安全性に関する新しい用途・保証は対象外。誤訳の完全自動判定を約束しない。
