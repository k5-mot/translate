<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と観測結果は[proposal.md](proposal.md)のWhyを参照する。比較Workflowはsource／target branchをLangGraphから開始し、各node wrapperが`TaskStatusEvent`をLifecycleへ送る。単独の無効PDF Testでは期待する`TARGET-SPLIT`／`translation_ja`を保存するが、全suiteでは同じcaseが`SOURCE-SPLIT`／対象なしとなる。これはFailure schema不足ではなく、実行中の正しい失敗eventが保存されないか、別のErrorで上書きされる順序依存を示す。

## Goals / Non-Goals

**Goals:** 全suiteで決定的に再現する最小条件を特定し、一つのRunで最初に実際に失敗したTaskと入力roleを安全なFailureへ一度だけ帰属させる。並列Model／Embedding処理を追加せず、比較branchのcheckpointとResume契約を保つ。

**Non-Goals:** source／target解析を一つのTaskへ戻すこと、Failure schemaまたは公開CLIを変更すること、raw例外を保存すること、LangGraphを置換すること、Model／token／timeout設定を変えること。

## Decisions

### 1. 全suite失敗を順序依存の契約Testへ縮約する

既存Testの個別成功を根拠にせず、全suiteの前半を二分し、原因となるTestまたは共有状態を絞る。縮約したTestでは一つの比較Runに対して失敗event列と最終Failureだけを安全なenum／IDで観測し、例外本文、path、Credentialおよび文書内容は記録しない。random sleepやTestの並び替えで隠す案は採用しない。

### 2. 比較branchをcheckpointを保ったまま完全逐次化する

原因はsource／target branchの`started`通知が別workerから同じ`run.json`を更新し、Windowsのatomic replaceが競合することだった。Graphを`START → SOURCE-SPLIT → TARGET-SPLIT → source残Task → target残Task → ALIGN`へ接続し、両PDFを外部Service呼出し前に検証しながら、独立nodeとcheckpointを維持して実行順を一意にする。これによりRun metadata、Doclingおよび後続Model呼出しを一つずつ実行する。

Lifecycleへlockを追加する案はmetadata競合だけを隠し、local Serviceの逐次要件とGraphの実行順を保証しないため採用しない。SPLIT wrapperは下位Errorの具体的な`target_id`を優先し、欠落時だけTask定義済みの`source_en`／`translation_ja`を補う。最初のfailed eventを正本とし、外側fallbackはactive Failureが書かれていない場合だけ使う既存境界を維持する。

### 3. archive判定を現行全Gateで更新する

focused Test、縮約した順序Test、全pytestを同じprocess条件で成功させる。`resolve-translate-contract-verification-gaps`の過去Evidenceだけではarchiveせず、現行件数と結果を検証Evidenceへ追記してから再verifyする。既存の完了Taskを未実施扱いには戻さないが、回帰が残る間はarchive不可とする。

## Quality Attribute Design

| ID | Approachとtrade-off | Evidence |
| --- | --- | --- |
| Q-FUNC／Q-USE | branch実行順を固定し、nodeの実失敗とTask／roleを一対一にする | source／target失敗注入、公開Error |
| Q-REL／Q-COMP | event列とfirst failureを決定的にし、旧Failure readerを維持する | 単独、順序Test、全pytest、Resume Test |
| Q-PERF | Model／Embedding逐次性と既存Graph構成を維持する | concurrency設定、Model呼出し差分0 |
| Q-SEC | raw例外をprocess内だけで扱い、allowlist IDだけを保存する | sentinel scan、Failure schema Test |
| Q-MAIN／Q-PORT | 原因を再現する最小Testと境界修正だけを追加する | Ruff、Format、ty、pytest、strict validation |

## Lifecycle, Migration and Operations

Data migrationはない。既存FailureとRunは読取り可能なまま保持し、修正後の新しい失敗だけが正しいTask／roleを記録する。運用者とSupportはrun ID、Task、role、例外型だけで入力側を判定する。Rollbackは本Changeのcode／Test commitを戻し、Run、exportおよびQdrantを変更しない。廃止操作はない。

## Risks / Trade-offs

- [Risk] 全suiteのタイミングに依存して再現が不安定になる → Test groupを二分して共有状態を特定し、time待ちではなくevent／scope境界を固定する。
- [Risk] sourceとtargetの接続変更でtarget失敗後のResumeがsourceを再実行する → nodeは分離したまま維持し、checkpointからtargetの失敗Taskだけを再開するIntegration Testで確認する。
- [Risk] 逐次化で比較処理時間が延びる → local Serviceは同時実行に耐えないという運用制約を優先し、処理時間より再現性とRun整合性を選ぶ。
- [Risk] 過去Evidenceが現行Test件数と食い違う → 現行Gate結果を新しいEvidenceとして記録し、archive前verifyをやり直す。

## Migration Plan

1. 順序依存を再現する最小Test条件とevent欠落箇所を特定する。
2. 原因境界へ失敗Testを追加し、最小修正を適用する。
3. focused／全Gateと秘密scanを通し、既存Runを変更していないことを確認する。
4. 本Changeをverify／archiveし、`resolve-translate-contract-verification-gaps`を再verifyしてarchiveする。
