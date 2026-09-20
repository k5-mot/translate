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
    ├── registration/pdf-parts/<source-key-hash>/
    └── <task-name>/
```

`inputs/`は入力の正本copy、`outputs/`はDownloadおよびexportの正本、`.workspace/`はCheckpointとTask Artifactです。root直下の`run.json`にはstatus、入力hash、Credentialを除く設定snapshot、fingerprintおよび最後のTaskだけを保持します。Workflow固有fingerprintとthread IDは`.workspace/workflow.json`へ分離します。

## 🔄 移行とRollback

旧`.work/`は新Runと互換ではなく、自動移行も行いません。旧実行結果を使ってResumeせず、元入力から新しいRunを作成してください。移行中も旧`.work/`を自動削除しないため、必要な成果物は運用者が別の場所へ保全できます。

RollbackではApplication codeを以前の版へ戻しても、新しい`runs/`を削除または旧layoutへ変換しません。再適用時の診断と再開に使えるよう、そのまま保持してください。旧版が新Runを読めない場合は新しい公開操作を停止し、既存のexport済み成果物を利用します。

Run IDはcanonical lower-case UUIDv7だけを受理します。この切替にUUIDv4との互換性、自動変換、directory改名およびmetadata書換えはありません。UUIDv4 Runは一覧から警告付きで除外され、Resume、exportおよび削除を同じ検証Errorで拒否します。Version更新前に、旧Versionで必要なUUIDv4成果物をRun root外へexportし、不要なUUIDv4 Runを明示削除してください。更新後に残したUUIDv4 directoryの処分が必要な場合は、旧Codeと切替前のRun root backupを対で復元して操作します。

元の参照File／DirectoryはUUIDv7の新規Runとして、必要に応じて`--source-id`付きで登録します。Rollback時もQdrantの旧revisionを推測して削除せず、新しいsource keyによる再登録で置換します。新CodeをRollbackする場合、切替後のUUIDv7 Runと`registration-v2` Pointは別領域へ保持し、旧Versionへ読ませたり自動削除したりしません。

## 📚 大規模PDFの参照登録

PDF登録は原FileのSHA-256をstreaming計算し、`.workspace/registration/pdf-parts/`へ`PDF_SPLIT_PAGES`以下のpartをatomic保存します。complete manifestが一致する同じRunのResumeだけがpartを再利用します。各partはpage順にDoclingへ送り、global chunk indexを付け、Embedding、Qdrant upsertおよびretrieve確認を最大16件のbatchで行います。外部model requestとWorkflow nodeは同時数1で順番に実行します。Chunk方式は`registration-v2`としてrevisionへ含まれ、同じsource keyの全新Pointを確認した後だけ旧schema、設定違いおよび失敗済みrevisionを削除します。

登録全体は一つのTask deadlineを共有します。途中失敗では確認済みの新Pointが一時的に残る場合がありますが、成功件数は報告せず旧revisionを保持します。外部Serviceを復旧して同じrun IDを明示Resumeすると、決定的なPoint IDへのupsertと最終cleanupで一つのrevisionへ収束します。Runを削除するとsplit Artifactも削除されますが、Qdrant Pointは別Lifecycleであり自動削除されません。

登録失敗の`failure.json`、Run log、CLIおよびStreamlitには`REGISTER`、次のstage、下位例外型だけを診断値として表示します。

| stage | 確認対象 |
| --- | --- |
| `collect` | 登録対象Fileの収集 |
| `hash` | streaming SHA-256 |
| `split` | PDFの分割Artifact作成・検証 |
| `extract` | Docling変換またはText抽出・Chunk化 |
| `write` | EmbeddingまたはQdrant upsert |
| `verify` | 書込み済みPointのretrieve確認 |
| `replace` | 確認後の旧revision削除 |

raw外部応答、Credential、文書本文、File pathおよびDocling job IDは診断へ保存しません。`extract`ではDocling、`write`ではEmbedding／Qdrant書込み、`verify`ではPoint確認、`replace`では旧revision削除の到達性と設定を確認してください。

## 📊 容量監視とSupport

Runは自動削除されません。CLIの`runs`またはStreamlitのRun一覧に表示される`size`と更新日時を定期的に確認し、保存volumeの空き容量へ運用上の閾値を設けてください。入力PDF、分割PDF、Docling archive、画像およびDOCXを含むため、Run数だけでは容量を見積もれません。大規模PDFでは入力copyに加えて分割Artifact分の空き容量を確保します。

障害調査では次を記録します。

- run ID、status、operation、`last_task`
- `.workspace/logs/run.log`の秘密を除いた警告
- `.workspace/failure.json`のTask、Page、Group、対象IDおよび安全な原因
- 登録失敗時のstage、下位例外型、Task deadlineおよび外部Service health
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

本変更ではruntime Dependency、公開CLI optionおよびWord→PDF機能を追加していません。Word→PDF変換は利用者側Operationです。

## 🔖 参考文献

- [ISO/IEC/IEEE 12207:2026](https://www.iso.org/standard/90219.html)
- [OpenSpec gap-resolution design](../openspec/changes/resolve-translate-contract-verification-gaps/design.md)
- [Run Lifecycle specification](../openspec/changes/establish-translate-ja-contracts/specs/run-lifecycle/spec.md)
- [Q-MAIN Verification Evidence](../openspec/changes/resolve-translate-contract-verification-gaps/verification.md)
- [Run identity and registration hardening design](../openspec/changes/harden-run-identity-and-reference-registration/design.md)
