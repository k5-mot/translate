<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と観測結果は[proposal.md](proposal.md)のWhyを参照する。比較Workflowはsource／target branchをLangGraphから開始し、各node wrapperが`TaskStatusEvent`をLifecycleへ送る。単独の無効PDF Testでは期待する`TARGET-SPLIT`／`translation_ja`を保存するが、全suiteでは同じcaseが`SOURCE-SPLIT`／対象なしとなる。これはFailure schema不足ではなく、実行中の正しい失敗eventが保存されないか、別のErrorで上書きされる順序依存を示す。

## Goals / Non-Goals

**Goals:** 全suiteで決定的に再現する最小条件を特定し、一つのRunで最初に実際に失敗したTaskと入力roleを安全なFailureへ一度だけ帰属させる。並列Model／Embedding処理を追加せず、比較branchのcheckpointとResume契約を保つ。

**Non-Goals:** source／target解析を一つのTaskへ戻すこと、Failure schemaまたは公開CLIを変更すること、raw例外を保存すること、LangGraphを置換すること、Model／token／timeout設定を変えること。

## Decisions

### 1. 全suite失敗を順序依存の契約Testへ縮約する

既存Testの個別成功を根拠にせず、全suiteの前半を二分し、原因となるTestまたは共有状態を絞る。縮約したTestでは一つの比較Runに対して失敗event列と最終Failureだけを安全なenum／IDで観測し、例外本文、path、Credentialおよび文書内容は記録しない。random sleepやTestの並び替えで隠す案は採用しない。

### 2. Task wrapperで入力roleをTask定義へ固定する

原因が失敗event欠落または外側fallbackである場合、比較Workflowのtracked nodeはTask名から確定できるinput roleをfailed eventへ明示する。下位例外がより具体的な`target_id`を持つ場合はそれを優先し、SPLITでは`SOURCE-*`を`source_en`、`TARGET-*`を`translation_ja`へ対応させる。Lifecycleが`last_task`だけからroleを推測する案は、他Taskのtarget概念と混同するため採用しない。

原因が別の共有状態である場合は、その状態の実行scope化またはcleanupを最小修正し、role補完を不要に広げない。いずれの場合も最初のfailed eventを正本とし、外側fallbackはactive Failureが書かれていない場合にだけ使用する既存境界を維持する。

### 3. archive判定を現行全Gateで更新する

focused Test、縮約した順序Test、全pytestを同じprocess条件で成功させる。`resolve-translate-contract-verification-gaps`の過去Evidenceだけではarchiveせず、現行件数と結果を検証Evidenceへ追記してから再verifyする。既存の完了Taskを未実施扱いには戻さないが、回帰が残る間はarchive不可とする。

## Quality Attribute Design

| ID | Approachとtrade-off | Evidence |
| --- | --- | --- |
| Q-FUNC／Q-USE | nodeの実失敗とTask／roleを一対一にする。補完値は比較入力roleだけに限定する | source／target失敗注入、公開Error |
| Q-REL／Q-COMP | event列とfirst failureを決定的にし、旧Failure readerを維持する | 単独、順序Test、全pytest、Resume Test |
| Q-PERF | Model／Embedding逐次性と既存Graph構成を維持する | concurrency設定、Model呼出し差分0 |
| Q-SEC | raw例外をprocess内だけで扱い、allowlist IDだけを保存する | sentinel scan、Failure schema Test |
| Q-MAIN／Q-PORT | 原因を再現する最小Testと境界修正だけを追加する | Ruff、Format、ty、pytest、strict validation |

## Lifecycle, Migration and Operations

Data migrationはない。既存FailureとRunは読取り可能なまま保持し、修正後の新しい失敗だけが正しいTask／roleを記録する。運用者とSupportはrun ID、Task、role、例外型だけで入力側を判定する。Rollbackは本Changeのcode／Test commitを戻し、Run、exportおよびQdrantを変更しない。廃止操作はない。

## Risks / Trade-offs

- [Risk] 全suiteのタイミングに依存して再現が不安定になる → Test groupを二分して共有状態を特定し、time待ちではなくevent／scope境界を固定する。
- [Risk] role補完が下位の具体的な対象IDを上書きする → 下位`target_id`を常に優先し、SPLITの欠落時だけinput roleを使用する。
- [Risk] sourceとtarget branchを逐次化すると既存checkpoint挙動が変わる → Graphのbranch構成を変更せず、Model／Embeddingの逐次制約とFailure帰属だけを検証する。
- [Risk] 過去Evidenceが現行Test件数と食い違う → 現行Gate結果を新しいEvidenceとして記録し、archive前verifyをやり直す。

## Migration Plan

1. 順序依存を再現する最小Test条件とevent欠落箇所を特定する。
2. 原因境界へ失敗Testを追加し、最小修正を適用する。
3. focused／全Gateと秘密scanを通し、既存Runを変更していないことを確認する。
4. 本Changeをverify／archiveし、`resolve-translate-contract-verification-gaps`を再verifyしてarchiveする。
