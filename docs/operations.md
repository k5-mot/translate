# 🛠️ Run Repository運用ガイド

本書は、CLIとStreamlitが共有する永続Runの移行、運用、保守および廃止手順を定義します。これはProject内のLifecycle確認表であり、規格適合の認証を主張するものではありません。

## 📦 Run layout

Runの正本は`TRANSLATE_RUNS_DIR`です。未設定時はRepository直下の`runs/`を使用します。

```text
runs/<run-id>/
├── run.json
├── inputs/
├── outputs/
└── .workspace/
    ├── checkpoints.sqlite
    ├── workflow.json
    ├── failure.json（失敗中のみ）
    ├── logs/run.log
    ├── run.lock
    └── <task-name>/
```

`inputs/`は入力の正本copy、`outputs/`はDownloadおよびexportの正本、`.workspace/`はCheckpointとTask Artifactです。root直下の`run.json`にはstatus、入力hash、Credentialを除く設定snapshot、fingerprintおよび最後のTaskだけを保持します。Workflow固有fingerprintとthread IDは`.workspace/workflow.json`へ分離します。

## 🔄 移行とRollback

旧`.work/`は新Runと互換ではなく、自動移行も行いません。旧実行結果を使ってResumeせず、元入力から新しいRunを作成してください。移行中も旧`.work/`を自動削除しないため、必要な成果物は運用者が別の場所へ保全できます。

RollbackではApplication codeを以前の版へ戻しても、新しい`runs/`を削除または旧layoutへ変換しません。再適用時の診断と再開に使えるよう、そのまま保持してください。旧版が新Runを読めない場合は新しい公開操作を停止し、既存のexport済み成果物を利用します。

schema version 1の翻訳・比較Runは一覧、Download、export、明示削除および互換なResumeを維持します。version 1の参照登録Runはstable source keyを持たないため、登録Resumeだけを理由付きで拒否します。一覧・export・削除は可能です。元の参照File／Directoryをversion 2の新規Runとして`--source-id`付きで登録し、登録完了を確認してから旧Runを削除してください。Rollback時もQdrantの旧revisionを推測して削除せず、新しいsource keyによる再登録で置換します。

## 📊 容量監視とSupport

Runは自動削除されません。CLIの`runs`またはStreamlitのRun一覧に表示される`size`と更新日時を定期的に確認し、保存volumeの空き容量へ運用上の閾値を設けてください。入力PDF、Docling archive、画像およびDOCXを含むため、Run数だけでは容量を見積もれません。

障害調査では次を記録します。

- run ID、status、operation、`last_task`
- `.workspace/logs/run.log`の秘密を除いた警告
- `.workspace/failure.json`のTask、Page、Group、対象IDおよび安全な原因
- 失敗TaskのPage、Groupまたは対象ID
- 使用したApplication versionと外部Serviceの到達性

Credential、原文全文および画像binaryをIssueや問い合わせへ添付しないでください。Docling、LLM、LibreTranslate、Qdrant検索の回復不能な障害ではRunを保持して同じrun IDをResumeします。成功Resumeではactiveな`failure.json`が除去されますが、redact済みの過去障害は`run.log`に残ります。Langfuse障害は`run.json`のwarningとlogを確認し、本処理の成果物を優先します。

Support時は、まず`failure.json`の対象と外部Serviceの到達性を確認し、設定を修復してCLIの`--resume <run-id>`またはStreamlitのRun一覧から再開します。Qdrantの現在状態はResume拒否条件に含めません。再発時は安全なlogとrun IDだけを共有し、raw例外やService応答本文は共有しません。

## 🗑️ Exportと明示削除

削除前に必要な成果物をCLIの`export`またはStreamlitのDownload／export操作でRun root外へcopyします。削除はCLIの`delete-run`またはStreamlitの確認checkboxと削除buttonから明示的に実行します。

CLIの非対話削除では対象pathを確認して`--confirm`を指定します。実行中、lock取得中、存在しないRun、linkまたはRun root外pathの削除は拒否されます。削除対象は`runs/<run-id>/`全体であり、外部exportは残ります。削除後のRunは復元できません。

## ✅ ISO/IEC/IEEE 12207 Lifecycle確認表

このProjectでは次のEvidenceをReviewしました。

| Lifecycle | 確認項目 | Evidence | 状態 |
| --- | --- | --- | --- |
| 移行 | 新layout、旧`.work/`非互換、version 1登録Run、source key再登録、Rollback時のRun保持 | 本書「移行とRollback」、OpenSpec design | 完了 |
| 運用 | Run一覧、Resume、進捗、外部Service障害、容量監視、Support情報 | CLI／Streamlit browser test、障害注入test、本書 | 完了 |
| 保守・Support | Capability Scenario、fingerprint差分、active failure診断、redact済みlog、品質gate、Dependency lock | OpenSpec tasks、Q-MAIN Verification Evidence、本書「容量監視とSupport」 | 完了 |
| 廃止 | 自動削除なし、確認付き削除、root containment、export保持 | Run Repository test、CLI／Streamlit削除test、本書 | 完了 |

## 🔖 参考文献

- [ISO/IEC/IEEE 12207:2026](https://www.iso.org/standard/90219.html)
- [OpenSpec gap-resolution design](../openspec/changes/resolve-translate-contract-verification-gaps/design.md)
- [Run Lifecycle specification](../openspec/changes/establish-translate-ja-contracts/specs/run-lifecycle/spec.md)
- [Q-MAIN Verification Evidence](../openspec/changes/resolve-translate-contract-verification-gaps/verification.md)
