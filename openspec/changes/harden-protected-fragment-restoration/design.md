<!-- markdownlint-disable MD041 -->

## Context

`proposal.md`のWhyを参照。現在の分割翻訳は保護対象をplaceholderへ置換し、応答後に完全一致で戻している。ローカルLLMはplaceholderの大文字小文字、区切り文字、空白を揺らすことがあり、検証前の正規化がないため`ProtectedFragmentMissing`へ遷移する。

## Goals / Non-Goals

**Goals:**

- 分割翻訳の応答から安全にplaceholderを同定し、原文の保護値へ一度だけ復元する。
- 表記揺らぎを許容する範囲と曖昧・欠落として拒否する範囲を決定的にする。
- 復元失敗時に有限回の再試行を行い、最終的な失敗を安全な証跡へ伝播する。

**Non-Goals:**

- LLMに保護対象の意味的な翻訳や推測をさせること。
- 外部依存、並列実行、Run形式、公開CLIの変更。
- 保護対象を欠落した応答へ値を無条件に追記して成功扱いにすること。

## Decisions

1. **Canonical placeholder contract**: promptで渡すtokenを既存の`__PROTECTED_<unit>_<fragment>__`に固定し、応答検査の前にUnicode正規化、大小文字正規化および安全な区切り文字・空白の揺らぎだけをcanonical tokenへ写像する。番号が異なる、複数tokenが一つへ合流する、または原文にないtokenは受理しない。
2. **One-to-one restoration**: 各期待tokenは翻訳単位ごとに一度だけ現れることを要求し、canonical化後に対応する原文fragmentを復元する。復元後の検査は既存のID集合検査と同じ境界で実行し、URL等の生値を例外文字列へ含めない。
3. **Bounded repair retry**: placeholderを含むsplit sub-chunkでは、正規化後も保護対象が欠落または曖昧な場合に限り、同じ単位を既存retry設定の範囲内で再要求する。再試行では保護対象の推測・自動追記をせず、規定回数後は`ProtectedFragmentMissing`として停止する。
4. **Evidence minimization**: 失敗証跡はtask、page、target ID、stage、cause typeおよび時刻だけを保存し、prompt、LLM生応答、原文fragment、URLを保存・ログ出力しない。実行は既存のシーケンシャル呼出しを維持する。
5. **Verification layers**: unit testで正常なtoken、大小文字・区切り揺らぎ、欠落、重複、未知tokenを検証し、`sample3.pdf`の少ページ実Runで実LLMの公開拒否とResume状態を確認する。

## Quality Attribute Design

- **Q-FUNC/Q-COMP**: 正規化は許容する揺らぎを限定し、保護値の一対一復元とID検証を行う。unit testと少ページ実Runのartifact検査をEvidenceにする。
- **Q-REL/Q-REC**: 再試行は設定済み回数を上限とし、失敗時は成果物を公開せずRun状態を保持する。失敗証跡のstage/causeとsource hashを確認する。
- **Q-SEC**: 診断情報から保護値と生応答を除外する。Evidence JSONとログのsecret/URL検査を行う。
- **Q-MNT**: 既存APIと設定を維持し、全pytest、Ruff、format、strict validationで回帰を検出する。

## Lifecycle, Migration and Operations

- 既存Runのcheckpointやfingerprint形式は変更せず、コード更新後の新規Runまたは明示Resumeで適用する。
- 運用時は`sample3.pdf`で少ページの再現確認を行い、失敗時は同じRunをResumeする。Run削除時の成果物範囲は既存契約に従う。
- ロールバックは本Changeのコードコミットを戻すだけで、入力コピーや明示export済み成果物は削除しない。

## Risks / Trade-offs

- **[Risk]** 揺らぎ許容を広げすぎると誤ったfragmentへ復元する → token番号と出現回数を厳密に検査し、曖昧なら失敗する。
- **[Risk]** 再試行によりローカルLLMの実行時間が増える → 既存retry上限を共有し、並列化しない。
- **[Risk]** 失敗が続くと成果物が生成されない → Resume可能なRunと安全な分類証跡を残し、入力を再処理しない。

## Migration Plan

1. unit testと静的検査を通過させる。
2. `inputs/sample3.pdf`でregister/translate/reviewの少ページ検証を実行する。
3. 失敗時は同じRunのResume結果、成功時はDOCX/Markdownと保護値検査を記録する。
4. 問題がある場合はコードコミットをrollbackし、Runディレクトリは保持する。

