<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実PDFのSTRUCTURE page 3では、既定の画像付きrequestがlocal Gemma4 runtimeを停止させ、画像を約1.09 megapixelsへ縮小した診断requestはruntimeを通過したものの出力上限で停止した。テキストのみの同page requestはschemaに適合しており、画像入力の安全域と出力枯渇後の回復条件を明示しない限り、保存済みRunを安全に完了できない。

## What Changes

- STRUCTUREのvision入力画像を決定的な画素数上限内へ縮小し、縦横比とページ全域を保持する。画像内容やraw応答を診断情報へ保存しない。
- visionの`output-truncated`では切れた応答を採用せず、同じvision requestのretryも行わない。既存の非vision失敗時fallbackと同様、異なる入力であるtext-only経路を有限回・逐次で試す。完全でschema適合するtext応答が得られた場合に限りSTRUCTUREを継続し、得られなければ安全なFailureとResume可能なcheckpointを保持して停止する。
- 358ページ中351ページがSTRUCTUREのModel対象となるため、完了したpageの検証済み結果をRun内の非公開checkpointとして原子的に保持する。中断後は互換なpageだけを再利用し、Task全体が成功するまで公開STRUCTURE Artifactは作らない。
- 出力枯渇時に常にWorkflowを停止する現行の保留中`run-lifecycle` deltaと、この限定的な回復経路の整合を明記し、archive前に競合する記述を解消する。Translation全体のtruncationや同条件retryの扱いは緩めない。
- 実PDFの同一pageで回復経路を検証してから、既存UUIDv7 Runを明示Resumeする。既完了Artifact、入力copy、外部exportおよび旧Runを保護する。

## Capabilities

### New Capabilities

- `pdf-translation`: 未同期の既存Changeに定義済みのCapabilityを同じpathで引き継ぎ、STRUCTURE画像の上限と構造補正の完全応答条件を追加する。別名Capabilityは作らない。

### Modified Capabilities

- `run-lifecycle`: visionの出力枯渇を同条件retryせず、異なるtext-only入力で回復できた場合だけTaskを継続する限定条件と、失敗Task内の検証済みpage checkpoint再利用を追加する。回復失敗時の停止、診断の秘匿およびResume契約は維持する。

## Impact

- 製品: `translate/tasks/structure.py`、既存の画像描画境界、focused Test、および必要な場合に限る安全なFailure伝播。
- OpenSpec: `pdf-translation`と`run-lifecycle`のdelta、および先行する未完了Changeとのtruncation契約の整合。
- 既存Run: `01a0c97c-f5cf-7031-b808-4ad545133925`を保持して明示Resumeする。公開CLI option、Model、token設定、Dependency、Run root、Qdrant状態は変更しない。

## Stakeholders and Lifecycle Impact

- 利用者・運用: runtime停止を避け、text-onlyで完全な構造補正が可能な場合だけ継続する。品質が確認できない場合はDOCXを公開しない。
- 取得・供給: 既存Pillow、PDF adapter、LM StudioおよびModelを使い、新しいServiceやPackageを取得しない。
- 移行: 保存済みRunの入力と成功済みTask checkpointを変換しない。新しいpage checkpointが存在しない旧Runは通常のSTRUCTURE開始として扱い、出力に影響する固定画像上限と既存fingerprintの関係をResume前に検証する。
- 保守・Support: visionとtextの分岐を安全な分類値でTestし、raw prompt、本文、reasoning、response、endpointをFailureへ含めない。
- 廃止: Run、外部exportおよびQdrant Collectionを自動削除しない。

## Quality Considerations

- Q-FUNC: 元画像が上限を超える場合も全page領域を保ち、visionまたは完全なtext-only応答だけを採用する。page 3の実probeと実Runでschema適合を確認する。
- Q-PERF: 画素数上限、900秒request timeout、各Model呼出しの有限retry／deadlineおよび同時Model／Embedding request最大1件を測定する。351対象pageの逐次処理を前提に完了pageの再推論0件を確認する。
- Q-COMP: 旧Failureの読取り、Run fingerprint、完了済みArtifactのhash／mtime、CLI／StreamlitのResume契約を回帰Testする。
- Q-USE: 回復成功時はactive failureを残さず、回復失敗時はTask、page、target、stageおよび安全な原因を表示する。
- Q-REL: truncated response採用0件、同一vision request再試行0件、失敗したSTRUCTURE途中Artifact公開0件と検証済みpage checkpointの復旧を確認する。
- Q-SEC: Credential、endpoint、prompt、本文、reasoning、raw応答、画像binaryのTest、log、FailureおよびEvidence漏えい0件を確認する。
- Q-MAIN／Q-PORT: 新規DependencyとOS固有処理0件、Ruff、Format、ty、全pytestおよびOpenSpec strict validation成功を確認する。
- Interaction capability、SafetyおよびFlexibilityは公開操作や自律Actionを増やさないため、新規の品質目標を設けず既存回帰Testで確認する。
