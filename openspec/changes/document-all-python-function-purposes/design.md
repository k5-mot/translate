<!-- markdownlint-disable MD013 MD041 -->

## Context

proposal.mdのWhyを参照。既存tests/test_documentation.pyはREADME link・設定名・保存layoutを検査し、quality CIはWindows/Linuxでpytestを実行している。新しいCI段階やpackageは不要。

## Goals / Non-Goals

関数の目的と重要な境界を説明し、説明欠落の再導入を検出する。命名の言換えや一律の定型文は避ける。説明を理由にAPI・制御flow・保存・依存・配置を変えず、既存の設計違反を正当化しない。common整理やLangGraph正本化は別の未解決事項。

## Decisions

1. Pythonの説明は原則docstringで追加するが、既存の明確に対応する説明Commentも認める。公開・非公開・入れ子・特殊method・Test関数を同じ基準で確認し、既存docstringも実装との相違を修正する。自明でない制約・副作用・失敗時の動作を簡潔に記載する。
2. 導入済みRuff 0.16.8のD102/D103/D105/D107をstdin fixtureで検証した。public/test/asyncは検出するが、private/nested/private class/private module/__all__非公開/override/overload/property setterは免除し、説明Commentを代替として認めない。実行Python文字列とlambdaも対象外。規約と契約が異なるため、D全体の有効化や不要なLint package導入は行わない。
3. 既存tests/test_documentation.pyへ規約固有の全関数・説明Comment代替の存在検査を加える。構文解析は標準ast、Comment認識は標準tokenizeへ委譲する。独自parserやLint frameworkを作らず、Ruffの可視性規則も複製しない。定義/decorator群の直前、または本文先頭に対応するCommentを認め、noqa/type ignore等の制御Commentだけでは説明とみなさない。空白docstringも不合格にする。
4. 製品・Test・公開入口のPythonを列挙して確認し、未追跡の開発probeも別枠で確認する。.agents/.venv/生成物を製品sourceへ混ぜない。検査自身の関数にも説明を付ける。Test fixtureでprivate/nested/async/特殊method・decorator・空docstring・Comment代替・制御Commentの差を確認する。
5. 実行文字列の生成箇所は別途列挙し、実際にPythonとして実行されるものだけを確認する。任意の文書文字列をPythonとして再解析しない。lambdaの意図は包含する関数説明・周囲Commentと併せて手動点検し、説明のためだけのwrapperは作らない。
6. 説明を除いたASTが編集前後で一致することを確認し、機能変更を混ぜない。dirty fileは既存差分を保持して本Changeの説明だけをstageする。隣接コメントの存在検査は説明の正しさを保証しないため、意味の確認は監査記録へ明記する。
7. 既に利用者が全関数の説明、Comment代替、過剰実装の禁止を決めており、新しい製品選択はない。汎用概念のdocstringをGlossaryへ追加しない。容易に戻せる文書補足なのでADRは新設しない。

## Quality Attribute Design

Q-MNTは対象一覧・機械的存在検査・意味確認で検証する。Q-FUNC/Q-RELは説明除去後のAST比較と全Test、実E2Eを用いる。旧実行中Processを停止したり、コメント修正のためモデルを重複起動しない。

## Lifecycle, Migration and Operations

製品操作と保存schemaを変更せず、データ移行・削除なし。既存CIで説明検査を実行する。未承認のcommon Moduleをdocstring追加によって承認済みとみなさない。

## Risks / Trade-offs

- [Risk] docstring数だけで品質を判定する → 実装・利用文脈を読み、既存説明も確認。
- [Risk] 既存Lintの再実装になる → Ruffとの実証済み契約差に限定し標準parserを使用。
- [Risk] 空Commentやnoqaで合格する → 非空の説明と制御Commentのfixtureを追加。
- [Risk] 文字列内Codeやlambdaが漏れる → 対象を独立に棚卸しし、機械検査の限界を記録。
- [Risk] dirtyな機能変更を混入する → 説明差分のみ選択stage、AST比較で確認。

## Migration Plan

入口、Task/Workflow、adapter/common、Test、文字列内Codeの順に是正し、最後に説明欠落0を機械検査する。段階的commitでは未完了範囲を明示し、全対象が完了するまでarchiveしない。各補足はCode変更なしで取り消せる。
