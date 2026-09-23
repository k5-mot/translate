<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: ローカルModelのSTRUCTURE応答を安全に完了する

Systemは、ローカルOpenAI互換ModelによるSTRUCTUREのstructured outputが出力上限へ到達した場合、同時実行を行わず、定義済みの代替structured-output経路を最大1回だけ逐次実行しなければならない（MUST）。代替経路でschemaに適合する完全な応答を得た場合だけ構造補正とpage Artifactを公開し、応答本文が不完全な場合は採用してはならない（MUST NOT）。代替経路の選択はRun fingerprint、入力copy、Qdrant状態および保存済みmetadataを変更してはならない（MUST NOT）。Q-REL、Q-COMPおよびQ-SEC（ISO/IEC 25010）として、同時Model requestを1件以下、部分Artifact公開を0件、raw response・原文・画像binaryのFailure漏えいを0件にし、mock testと同一Runの実PDF Gateで検証しなければならない（MUST）。

#### Scenario: STRUCTUREの代替経路で完全な応答を得る

- **WHEN** STRUCTUREの初回structured outputが`finish_reason=length`となり、代替経路が完全なschema適合応答を返す
- **THEN** Systemは代替応答だけを適用してpage Artifactとcheckpointを公開し、同一Runを次のTaskへ継続する

#### Scenario: 代替経路でも出力が枯渇する

- **WHEN** 初回と最大1回の代替structured outputがいずれも完全なschema応答にならない
- **THEN** Systemは`output-truncated`、Task、page、target、stage、finish reasonおよび数値token usageだけをFailureへ保存し、部分Artifactを公開せずResume可能な状態で停止する

#### Scenario: 同一Runを再開する

- **WHEN** 代替経路で停止したRunを現在と同じfingerprintで明示的にResumeする
- **THEN** Systemは完了済みTaskを再実行せず、未完了STRUCTURE pageから逐次処理を再開する
