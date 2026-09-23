<!-- markdownlint-disable MD041 -->

## Context

`proposal.md`のWhyを参照。現行実装は出力枯渇後のsplit sub-chunkだけplaceholder保護を有効にし、通常の高推論chunkでは原文fragmentを直接promptへ渡している。そのため通常chunkの実LLM応答で保護対象欠落が発生した。

## Goals / Non-Goals

**Goals:**

- すべての翻訳chunkで同じplaceholder保護・canonical復元・検証を適用する。
- 通常chunkの高推論を維持しつつ、保護失敗は既存の有限retryと安全なFailure Evidenceへ接続する。
- prompt長増加を計測し、保護対象の保持とローカルLLMの実行時間を受入検証する。

**Non-Goals:**

- 翻訳モデル、context length、外部依存、並列実行の変更。
- 保護対象を推測・追記して成功扱いにすること。
- registerとtranslateを同一operation Runとして強制的に再利用すること。

## Decisions

1. **All-chunk protection**: `force_no_reasoning`に関係なく、各chunkのprompt targetをplaceholder化する。既存の高推論/none-thinking設定は維持し、restore後にID・fragment検証を行う。
2. **Stable local numbering**: token番号はchunk内のunitとfragmentの順序から決定し、split sub-chunkではsub-chunkごとに再計算する。応答で未知・重複・欠落があれば`ProtectedFragmentMissing`とする。
3. **Retry boundary**: placeholder復元・`_validated_mapping`の失敗は同じchunkのretry回数内で再要求する。全試行失敗時は成果物をatomic publishせず、既存LifecycleのResume状態へ伝播する。
4. **Prompt budget accounting**: placeholder置換で増える文字列をavailable input budgetの既存計算に含め、chunk分割条件を越える場合は既存split pathへ委譲する。新しい並列経路は作らない。
5. **Evidence minimization**: 失敗の公開情報はtask/page/target/stage/causeに限定し、promptやfragmentはログ・checkpointに保存しない。

## Quality Attribute Design

- **Q-FUNC/Q-COMP**: 通常・split双方の保護fragment保持率100%をunit testと`sample3.pdf` Runで検証する。
- **Q-REL/Q-REC**: 失敗時に有限retry、atomic cleanup、Resume可能なRunを確認する。成功時は成果物が公開されることを確認する。
- **Q-PERF**: placeholder保護によるprompt/実行時間の増加をRunのTIME出力で記録し、シーケンシャル実行を確認する。
- **Q-SEC**: 生応答・原文保護値をFailure Evidenceに含めないことをテストする。
- **Q-MNT**: 全pytest、Ruff、format、型検査、OpenSpec strict validationをゲートとする。

## Lifecycle, Migration and Operations

- 新コードは新規translate Runおよび明示Resumeへ適用し、既存register Runのfingerprint拒否契約は維持する。
- 少ページ検証は既存登録済みQdrant参照を利用し、`sample3.pdf`のtranslate/reviewをシーケンシャルに実行する。
- ロールバックは本Changeのコードコミットを戻し、失敗Runと明示export成果物は保持する。Run削除は既存の明示操作で行う。

## Risks / Trade-offs

- **[Risk]** placeholderによりpromptが長くなり、出力枯渇が増える → chunk budgetと既存split fallbackを共有する。
- **[Risk]** 高推論モデルがplaceholderを無視する → restore検証を必須とし、有限retry後は安全に停止する。
- **[Risk]** 実Run時間が長くなる → 並列化せず、TIME証跡と少ページサンプルで段階検証する。

## Migration Plan

1. unit testと静的検査を通過させる。
2. `sample3.pdf`でregister済み参照を用いたtranslateを実行し、成功ならreview、失敗なら同一translate Runをresumeする。
3. source hash、成果物、Failure Evidence、cleanupを検査する。
4. 問題があればコードコミットをrollbackし、Runを削除せず保存する。

