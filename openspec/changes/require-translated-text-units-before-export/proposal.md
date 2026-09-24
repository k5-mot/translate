<!-- markdownlint-disable MD013 MD033 MD041 -->

## Proposal Status

提案作成途中。grill-with-docsで公開前の空訳判定範囲を確認中であり、実装承認済み・apply可能とは扱わない。訳文層なし・空配列に加え、原文に文字があるのに出力訳が空文字または空白だけの場合も停止する案を推奨する。回答後に下記の範囲とspecs/design/tasksを確定する。実装・Testの変更はまだ行っていない。

## Why

最終VALIDATEがCaptionの訳文層を確認せず、未翻訳Captionを原文で補った成果物を公開できる（[CONTENT-VALIDATE-001](../document-all-python-function-purposes/verification.md)）。本文・表セルでも検査と描画の層選択が異なるため、実際に出力する層を共通の対象列挙で検査する必要がある。

## What Changes

- 表紙以外の本文・Caption・Table cellについて、原文があるのに出力に使う訳文層が未作成または空配列ならVALIDATEで停止することを明文化する。
- 最終層が存在すればそれを使用し、未作成の場合だけ初回訳を使用する。空の最終層を古い初回訳で検査して合格にしない。
- 検査対象の列挙は既存のblock_text_unitsを再利用し、本文・Caption・結合セル起点の対象IDを一貫させる。
- 未翻訳Caption、空の最終層、正常訳、表紙除外と公開前停止の回帰Testを追加する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: VALIDATEでの翻訳層存在検査と停止条件を追加する。既存の日本語成果物・Caption保持要求を具体化し、空配列と未作成を区別する公開前条件を明示する。

## Impact

主な変更先は`translate/tasks/validate.py`、既存VALIDATE/Workflow Test、pdf-translation delta。Documentの保存形式、翻訳Backend、公開引数は維持する。既存のTextUnit viewを再利用し、新規module・依存・外部呼出・再開管理は追加しない。従来見逃した不完全な文書は成功から失敗へ変わる。不完全な出力への互換性を維持する目的で例外を設けない。

独立したMarkdown→DOCX変換に翻訳要件を課さず、描画Taskを翻訳の存在検査機構へ作り替えない。文面が日本語として正しいか、すべての語句が訳されたかは既存CHECK/REVIEWの対象であり、今回の層検査だけで保証しない。

空文字・空白だけの訳も現状は通過するため、単なる非空配列検査で訳欠落全体が解消したとは判断しない。原文自体が空のセル、表紙、原文と同一でよい保護対象は、文字がある原文に対する訳欠落と区別する。判断材料は[診断記録](verification.md)を参照する。

## Stakeholders and Lifecycle Impact

- 利用者: Captionが未翻訳のまま「検証済み」となる状態を防ぎ、失敗Taskと対象を確認できる。
- 取得・供給: 新規Packageやサービス取得はなく、既存のPR/CIで供給する。サンプル・成果物・.agents・秘密情報をコミットしない。
- 移行・運用: 既存Artifact/Checkpointを自動修正・削除しない。失敗したTaskはLangGraphのCheckpointに従って再開し、独自の巻戻し・完了台帳を設けない。
- 保守: 正常/欠落/空の層と公開境界を自動検査する。最新translation→Microsoft Word PDF化→reviewの実検証と利用者目視を残す。
- 廃止: API・保存形式の廃止はなく、見逃しに依存した成功判定だけを取り除く。

## Quality Considerations

- Q-FUNC: 本文/Caption/cellで訳文層欠落の見逃し0件、対象漏れ・重複0件。層選択のfixtureを自動検査する。
- Q-REL: VALIDATE失敗時の後続MARKDOWN/DOCX実行0回、成功reportの新規公開・既存成果物の上書き0件。実GraphとCheckpointで確認する。
- Q-SEC/Q-INT: 失敗はTask・page・対象IDと固定理由で診断し、原文・訳文・秘密を例外やcheckpointへ追加保存しない。
- Q-COMP/Q-MNT: 既存のTextUnitとTask関数/クラス、serializer、公開入口を再利用する。表紙、FIX skip警告、正常層、asset検査を回帰検査し、新しい管理層を作らない。
- 性能効率: モデル/外部要求の追加0件。既存文書の有限走査のみであり、性能改善を別目標にしない。
- 柔軟性/移植性・安全性: 新しい環境、デプロイ方式、身体/環境への影響を導入しないため、新たな要求は適用しない。
