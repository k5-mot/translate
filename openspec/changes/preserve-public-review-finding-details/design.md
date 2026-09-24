<!-- markdownlint-disable MD041 -->

## Context

[proposal.md](proposal.md)のWhyを参照。`ReportTask.run`はCHECKとREVIEWのFindingを結合し、severity/kind/messageだけをMarkdownへ描画する。診断JSONには全fieldを保存している。CLIの`--output`、UIのdownload、共通exportはMarkdownを渡し、診断JSONで公開情報の欠落を補えない。

`Finding.target_ids`は空配列、evidence/suggestionはNoneを許す。REVIEWには未知IDの存在検証がない。比較Documentは対応Groupの添字から`alignment/<index>`を作るが、現行の対応一覧はそのラベルを出さない。Groupには元のsource_ids/target_idsがあるものの、REPORT入力だけで元PDFページを確定できない。

## Goals / Non-Goals

**Goals:** 保存済み情報を失わず安全に公開描画する境界をREPORTに置き、既存の対応IDと結び付ける。描画方針を明示して、任意項目や未知IDで捏造・黙殺しない。

**Non-Goals:** Findingの再生成、未知IDの新たな拒否契約、元PDFページの推定、ALIGNの意味的誤対応修正、入力文書の変更。commonの再編や再開管理の変更は別の指摘として残す。

## Decisions

1. **公開内容:** 集計・対応・指摘の三部構成を維持する。各Findingには重大度、種別、メッセージ、対象ID、根拠、修正方針の日本語ラベルを設ける。CHECKの後にREVIEWを置く現行順序と全件表示を維持する。JSONだけを公開する案は、利用者のMarkdown入口と既存契約に合わないため採用しない。
2. **対象の追跡:** 対応一覧を既存のgroups順で列挙し、`alignment/0`からのラベルを付ける。完全一致するFinding対象はそのラベルからsource/target IDへ辿れる。caption/cell IDもそのまま表示する。独立したID台帳は作らず、IDの部分一致・類似文字列でGroupを推定しない。空対象は「対象未指定」、未知対象は値を保持して「対応情報なし」とする提案であり、未知IDを理由に従来成功したREPORTを停止させない。
3. **欠落値:** evidence/suggestionのNoneは「未記載」、空文字は「空文字」と示し、値がある場合は全文を保持する。空白だけの値を勝手にstripして欠落扱いしない。単語や根拠をLLMで補完する代替案は採用しない。これらは今回提示する可逆的な表示案であり、FindingのModel/検証条件は変更しない。
4. **文字列描画:** 不定の自由文（message/evidence/suggestion/kind/各ID）をMarkdown構文として解釈させない。導入済み`markdown_it`のparserを使った先行メモリ試験では既存`markdown._escape`はHTMLと実体参照をliteralとして保持できなかった。既存`markdown._render_literal_block`のcode処理にある、内容中の最長backtickより長いfenceを選ぶ方法は、複数行・HTML・実体参照を保持できる。REPORTでも同じ小さい描画方法を使い、固定ラベルの下にliteralを配置する。集計の任意kindも対象とし、特殊文字のない通常のseverity/kind表示は可能な限り維持する。
5. **再利用の境界:** `_render_literal_block`はBlock/current translation/languageを入力とし、数式・表にも分岐するため、Findingの文字列表示のためだけにBlockを偽造したり別Taskのprivate関数へ依存したりしない。既存の標準`re`とfence構築の小さな処理をREPORT内に限定する。汎用Markdown framework、追加依存、新規common/utils moduleは作らない。既存描画のHTML/Word変換に影響を与えない。
6. **保存/API:** 現行atomic_write_text/jsonとBaseTaskの計測、関数wrapperを使用する。新規API、進捗記録、Checkpoint、retry、設定や外部呼出を追加しない。レポートへ追加する情報は元のFinding/Groupからのみ取得する。

## Quality Attribute Design

| 品質ID | 設計と検証Evidence |
| --- | --- |
| Q-FUNC/Q-INT | CHECK/REVIEW全項目・複数対象・caption/cell・多対多・未対応Groupを公開Markdownと照合。既知IDの参照先と未知IDの非捏造を検査 |
| Q-SEC | 複数行、空行、CRLF、連続backtick、HTML、実体参照、リンク/見出しを含む文字列をparserのtokenで検査。raw HTML token 0件。製品はHTMLを生成しない |
| Q-REL/Q-COMP | 0件表示2箇所、JSON全field・順序・集計の同一性、入力hash不変、CLI/UI/exportのbyte同一性。実REPORTを通したArtifactを公開経路のTestへ渡す |
| Q-MNT | 既存Task内の限定変更。新関数の目的説明、Ruff/ty/Test。新しい依存・外部要求・再開台帳0件 |

parserのCRLF→LF正規化は表示上の改行として比較する。原文byteの正本は既存JSONであり、Markdown rendererの改行正規化をFinding内容の書換えへ波及させない。

## Lifecycle, Migration and Operations

実装前に既存Testが見落とす三fieldの公開欠落を失敗Testで示す。CLI/UIの受渡しTestは、fakeな既製Markdownだけではなく製品REPORTの生成結果を使う。最新の変更を含む実translationが成功した後、Microsoft Wordをユーザ操作として使ってPDF化し、入力PDFと比較Reviewする。LLM/Embeddingは逐次実行する。実行中の旧Reviewを再起動・停止したり、成果物を置換したりしない。

過去の成功Translationに基づく現Reviewは診断証拠として追跡するが、この修正または最新Translationの正式verifyの代替にしない。COMPARE-ALIGN-001が残る間は比較品質全体を合格扱いしない。利用者のWord/PDF目視確認を記録し、無回答を承認とみなさない。

## Risks / Trade-offs

- [Risk] literal表示で文面内の強調やリンクが操作できなくなる → 根拠の忠実な文字列表示を優先し、固定ラベル/見出しは読みやすくする。表示案はapply前のレビュー対象とする。
- [Risk] 存在しない対象や未記載根拠を表示できたことで、Finding自体も正しいと誤認する → 未指定/未記載を区別し、生成側やALIGNの不具合は別に追跡する。
- [Risk] 実REPORTが成功してもCLI/UI経路で欠落する → 公開されたbytesを検証する。
- [Risk] 外部障害で実translationが完了しない → 失敗段階とResume状態を記録し、単体Testのみで正式verifyを完了にしない。

## Migration Plan

既存feature branchでこのChangeのCode/Testのみを実装し、既存の無関係な差分を保存する。過去のレポートの自動移行・削除はしない。Rollbackは描画変更のrevertで可能で、データ移行を伴わない。ただし欠落バグが復帰することを記録する。正式verify後にarchive、PR/CI、mainへのmerge、originへのpushを行い、未解決指摘を消さない。

用語は既存CONTEXT.mdのFinding/Artifact/Taskを使用し、変更しない。可逆的な局所描画修正のため、別GlossaryやADRは新設しない。
