<!-- markdownlint-disable MD013 MD041 -->

## Why

利用者が明示した関数説明必須・既存依存の再利用・Resume状態の二重管理禁止が、コーディング規約の具体的な検査境界として十分に書かれていない。追加監査で多数の説明欠落と重複機構を確認したため、修正の採否基準を先に明文化する。

## What Changes

- 関数/メソッド/入れ子/Test関数の目的を説明する規則と、lambda・実行文字列の扱いを明記する。
- 既存Packageの同等機能を再実装しない規則を、API・契約差・検証証拠の確認手順として具体化する。
- LangGraph checkpointを再開位置の唯一の正本とし、独立した完了状態・page/chunk再開記録の二重管理を禁止する。
- 本文書変更の完了と既存コードの是正完了を分け、監査の未解決件数を保持する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。開発規約だけの変更としてskip_specsを指定する。製品の保存layoutや公開動作は変更しない。

## Impact

CODING_RULES.mdと変更・検証文書のみ。新しい実行時依存や製品moduleは追加しない。既存の説明欠落・Package再利用・checkpoint移行は別の実装修正で追跡する。

## Stakeholders and Lifecycle Impact

開発者とレビュー担当者が必要性・責務・検証根拠を一貫して判断できる。運用者の起動操作や保存データは変わらない。取得/供給/廃止の製品変更はないため対象外。規約追加を過去コード適合済みと取り違えないよう、監査を参照する。

## Quality Considerations

Q-MNT: 3つの利用者要求が明示規範と検証基準へ対応し、既存規則との矛盾・重複を0件にする。Q-REL: 再開状態の正本と副作用の冪等性を区別する。文書だけなので性能・UI・機能の新要求は追加しない。利用者指定の正式verify条件である実translation→Word PDF化→reviewは省略せず、実行証拠が揃うまでarchiveしない。
