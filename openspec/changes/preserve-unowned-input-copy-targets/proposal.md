<!-- markdownlint-disable MD013 MD041 -->

## Why

[INPUT-COPY-001](../document-all-python-function-purposes/verification.md)で、入力コピー先を新規作成できなかった場合にも既存先の削除を試みる実装を確認した。失敗時に既存データを巻き込まず、導入済み・標準機能へ委譲するという利用者の要求に沿って入力保存境界を是正する。

## What Changes

- 入力コピー先の排他的作成に成功する前の失敗では、コピー先を削除・上書きしない。
- 作成成功後のコピー・同期・hash・metadata処理で失敗した場合は、今回作った不完全なコピーだけを後始末し、元の失敗を通知する。後始末自体のOS Errorでも成功扱いにはしない。
- 独自copy/hashループを標準Libraryへ委譲し、保存したbyte列のSHA-256とsize、有限buffer、flush/fsync、metadataコピーを維持する。
- 新しい共通module、永続状態、Resume判定、依存、CLI/UI optionは追加しない。commonの最終配置や保存形式移行の回答待ち判断とは分離する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: 入力コピーの失敗時に、今回作成していない既存先を後始末対象にしない要求とScenarioを追加する。Task完了状態やGraphの再開仕様は変更しない。

## Impact

主対象は既存`translate/common/runs.py::_copy_verified`と`tests/test_run_input_manifest.py`、必要な公開準備境界Test。現行の呼出元はRunRepository.createのみ。新しいRun rootはcopy前に排他的作成され、root衝突はcleanup用tryの外で拒否されるため、通常公開経路で過去Runの削除が起きたとは断定しない。元入力、既存Run、外部exportの保全を回帰検証する。

## Stakeholders and Lifecycle Impact

利用者の既存入力・成果物を保全し、保守者は作成前/後の失敗を区別できる。標準Libraryだけを使用するため新たな取得・供給は不要。データ移行・廃止・過去Run削除は行わない。実行中processは停止・設定変更せず、新しいprocessで検証する。

## Quality Considerations

- Q-FUNC/Q-REL: コピー前の失敗で既存先の変更0件、正常時の内容/size/SHA-256不一致0件。作成後の障害では失敗として伝播し、削除可能な不完全コピーを除去する。
- Q-SEC: 既存先の破壊・上書き0件。Errorへ本文やCredentialを追加しない。hostileな別processによる作成後path置換への完全防御とは区別する。
- Q-MNT: コピーとhashを標準APIへ委譲し、独自stream wrapper、新module、永続所有者台帳0件。
- Q-PERF: 入力sizeに比例した全量memory保持0件。hashのため宛先の逐次読戻しが1回増えるため、単一passや高速化は保証せず、有限bufferの検査と実PDF時間を記録する。
- Q-COMP/Q-PORT: 既存Run形式と戻り値を維持し、Windows上のclose後cleanupと既存CIの検査を行う。UIの新機能・操作性変更は対象外。人の安全に関する機能変更はない。
- 正式verifyは自動Testに加え、実translation→自分で起動する非表示Microsoft WordでPDF化→元PDFとのComparison Reviewを逐次実行し、利用者目視を求める。未解決を残したままarchiveしない。
