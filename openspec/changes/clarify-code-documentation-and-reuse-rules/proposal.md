<!-- markdownlint-disable MD013 MD041 -->

## Why

利用者が明示した関数説明必須・既存依存の再利用と、製品固有のResume状態の二重管理禁止を、管理先を区別して明文化する。汎用的なコーディング規約と製品仕様・設計を混在させず、追加監査で確認した違反の是正基準を示す。

## What Changes

- 関数/メソッド/入れ子/Test関数の目的を説明する規則と、lambda・実行文字列の扱いを明記する。
- 既存Packageの同等機能を再実装しない規則を、API・契約差・検証証拠の確認手順として具体化する。
- 再開状態の一元化はrun-lifecycleの要求とし、LangGraphへの委譲とcommonの配置制約はOpenSpecのdesign.mdで管理する。製品固有の規則をCODING_RULES.mdへ記載しない。
- 本文書変更の完了と既存コードの是正完了を分け、監査の未解決件数を保持する。
- CODING_RULES全体を点検し、対応Python版・公開entry point・Task計測の製品契約をOpenSpecへ移す。製品固有の依存と除外pathを参考設定から除き、実設定を重複管理しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: Task単位のCheckpoint要求を明確化し、再開位置・完了履歴・進捗表示に矛盾する独立状態を持たないことを要求する。対応Python版、公開entry pointとTask経過時間の既存契約を規約から移管する。

## Impact

今回の編集はCODING_RULES.mdとOpenSpec文書のみ。製品固有要求を追加するためskip_specsを解除する。新しい実行時依存や製品moduleは追加しない。既存の説明欠落・Package再利用・checkpoint移行は未実装タスクとして追跡し、仕様記載を実装済みと扱わない。

## Stakeholders and Lifecycle Impact

開発者とレビュー担当者が必要性・責務・検証根拠を一貫して判断できる。運用者の起動操作や保存データは変わらない。取得/供給/廃止の製品変更はないため対象外。規約追加を過去コード適合済みと取り違えないよう、監査を参照する。

## Quality Considerations

Q-MNT: 利用者要求を汎用規約と製品仕様・設計へ分類し、管理先の重複を0件にする。Q-REL: 再開状態の正本と副作用の冪等性を区別する。要求の追加だけで性能・機能の実装適合を宣言しない。利用者指定の正式verify条件である実translation→Word PDF化→reviewは省略せず、実行証拠と未実装事項の解消が揃うまでarchiveしない。
