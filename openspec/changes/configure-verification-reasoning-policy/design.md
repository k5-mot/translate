<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象範囲は[proposal.md](proposal.md)を参照。現状は`Settings`に推論切替がなく、TRANSLATE/REVIEW/VERIFY/FIXはhigh、ALIGNはlow、STRUCTUREはnone/disabledを指定する。LLM Adapterの`_model`には既に`reasoning_effort`とthinking無効化の送信実装があり、新しいProvider制御を開発する必要はない。

公開Runのfingerprintに加え、Translation/Comparison Reviewは独自のWorkflow識別を保持する。REVIEWには入力ペア由来のChunk cache、STRUCTUREには生成契約付きPage cacheが残る。これらの再開状態重複の撤去は別Changeの未完了事項であり、今回新しい完了一覧やcacheを追加しない。

## Goals / Non-Goals

**Goals:** 既存の送信境界でOFFを確実に適用し、default互換を維持する。設定差による既存結果の混用を防ぎ、実要求の指定値と観測値を一致させる。

**Non-Goals:** 通常実行の推論値変更、推論強度の多段階UI、Providerの再実装、常設計測基盤、保存layout/common整理、既知ALIGN/表画像品質の修正。WordからPDFへの変換を製品機能へ追加しない。

## Decisions

### 既存SettingsとAdapterで解決する

`Settings.reasoning_mode`は`Literal["task-default", "off"]`、既定値は`task-default`。`load_settings`で`LLM_REASONING_MODE`を読み、未知値を設定名と許容値のみのErrorで拒否する。`.env.sample`は通常値を示し、検証プロセスでだけ`off`を上書きする。CLI option/UI widgetを別々に作る案は、設定経路と優先順位を増やすため採用しない。

`adapters.llm.structured`でモデル構築・観測より前に実効値を決定する。OFFなら`reasoning="none"`、`thinking="disabled"`にし、既存`_model`を通して次を送る。

- `reasoning_effort: "none"`
- `chat_template_kwargs: {enable_thinking: false}`
- `thinking_budget_tokens: 0`（整数）

defaultでは呼出元の指定をそのまま維持する。prompt、schema mode、token予約、timeout、retry、Embeddingは変えない。Adapter呼出しのmetadataは実効reasoning/thinkingを記録する。これは既存送信契約の再利用であり、Provider全般で必ず推論tokenが0になるという保証ではない。

### 出力切断回復の重複を避ける

TRANSLATEの既存`force_no_reasoning`判定に全体OFFを反映する。OFFでのlength切断は同じ要求をnoneとして再送せず、既存の最大深さ2・左右逐次の分割へ進む。単一要素、深さ上限、非切断Errorは従来の失敗伝播を維持する。defaultのhigh→none一度→有限分割、および応答内容検証の有限retryを回帰Testする。

### 旧通常設定のhashを保存し、OFFだけ識別する

公開fingerprintと両Workflowのfingerprintには、OFFのときだけ`llm_reasoning_mode: "off"`を追加する。defaultでは追加しないことで、導入前のcanonical JSON/hash/thread IDを変えない。欠落がdefaultであることをTestと利用説明へ明記する。公開fingerprintは既存の共通処理に合わせ全操作で同じ設定差を扱い、無関係な既存hash仕様の最適化はしない。

thread IDを変えるだけでは同じworkspaceのREVIEW cacheを再利用し得るため、Workflow直接呼出しにも、既存`workflow.json`の推論設定（欠落はdefault）と現在値の不一致を**書込み前に拒否**する境界を設ける。別workspaceでのみ新規実行する。これによりcache形式や独立した完了状態を新設せず混用を防ぐ。Task内部cacheの全体撤去は今回に含めない。公開CLI/UI経由では既存のfingerprint判定が先に拒否する。

STRUCTUREはdefaultでも既に同じnone/disabled/budget=0のため、Page生成契約を変更しない。設定変更を既存UUIDv7保存layoutの移行や旧Run削除に結び付けない。

## Quality Attribute Design

- Q-FUNC/Q-USE: Settingsの未指定・明示default・off・未知値、全Task相当のhigh/low/noneと両schema modeを送信境界で検査。CLI/UI共通読込も確認する。
- Q-COMP/Q-REL: 旧通常hash不変、default/off双方向拒否、off/off再開、同workspace直接呼出し拒否、拒否前後のArtifact不変、有限切断回復をTestする。
- Q-SEC: 未知値のErrorと実効設定metadataへ合成Secret/本文が混入しないことを検査する。Langfuse障害時の継続契約は維持する。
- Q-PERF: 既存LangfuseのProvider観測でOFF要求の時間・推論/通常出力tokenを取得可能な範囲で集計する。APIへ本文を要求せず、全体時間と個別要求を二重加算しない。
- Q-MAINT/Q-PORT: 新規Module/依存なし。既存のTestとruff/tyを実行し、サンプルや生成物をcommitしない。

## Lifecycle, Migration and Operations

停止済みRunは`01a0d520-15a4-74a2-9eaf-afafa726a03a`、session `43282`。利用者承認で対象workerを停止しexit 1を確認した。停止は品質検証失敗や正常完了とは区別し、metadataのrunning表示を生存証拠としない。input/Artifact/SQLiteとWALを削除・編集しない。

実装・局所検証後、旧workerがいないこととProvider側で旧要求が稼働していないことを確認する。新たなLLM/Embedding要求を重ねず、LM Studio自体は停止しない。OFFをプロセス環境へ渡し、非対話CLIで`--resume`なし、未使用export先を指定してsample3の新規翻訳を一度だけ開始する。Run ID、入力hash、実行Code、設定、終端状態をverification.mdに記録する。

新規DOCXを検査後、Microsoft Wordを使う手動相当オペレーションでPDF化し、元sample3 PDFとのReviewもOFFの新規Runで行う。Wordは自身が開始したinstanceだけ終了する。成果物を利用者目視へ提示する。既知のALIGN不整合等が残れば、その結果を合格へ変更せず記録する。関連する`preserve-public-review-finding-details`と`restore-docx-tables-and-indexes`の受入記録へ参照を追加する。

## Risks / Trade-offs

- [Providerが指定を無視する] → 初回の利用可能なProvider観測で確認する。非0ならOFF検証の合格を止めて診断し、取得不能なら実測未確認と記録する。暗黙にhighへ戻さない。
- [推論OFFで品質が変わる] → 完了時間だけで判断せず、DOCX構造・本文保持・比較結果・目視を分離して評価する。
- [既存workspace cacheの混用] → 新規Run/別export先と設定不一致拒否を併用する。過去の途中成果物を新Runへコピーしない。
- [既存未コミット差分との衝突] → 特に`adapters/llm.py`と関連Testの差分を保持し、このChangeの差分だけを識別する。

## Migration Plan

1. 新設定・送信境界・互換性・有限回復のTestと文書を追加し、通常既定値を維持する。
2. 自動検査後にOFFの新規実検証へ進む。旧Runは保存し、今回の検証でResumeしない。
3. 設定を通常へ戻す場合は`task-default`または未指定にする。OFF Runを通常設定でResumeしない。旧CodeはOFFを理解しないため、Rollback時にOFF Runを旧Codeで開かず保存する。

新語の定義変更や不可逆な設計選択はないため、CONTEXT.mdとADRは増やさない。
