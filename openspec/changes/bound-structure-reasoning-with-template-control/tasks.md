<!-- markdownlint-disable MD013 MD041 -->

## 1. Evidence and Run Preconditions

- [ ] 1.1 先行Change `enforce-structure-nonthinking-provider-contract`のcommitted Evidenceを読み直し、短い実requestが`chat_template_kwargs.enable_thinking=false`を受理してattempt 1、7.910秒、`finish_reason=stop`、schema-validおよびreasoning 245 tokensで完了したことを記録する。同じshort probeを再送しない（Q-FUNC／Q-PERF／Q-SEC、取得／供給）
- [ ] 1.2 Run `01a0c97c-f5cf-7031-b808-4ad545133925`のinput hash、fingerprint、Failure、SPLIT～LOAD file count／aggregate hash／latest mtime、private checkpoint、公開STRUCTUREおよび外部outputをread-onlyで再baseline化し、前回Evidenceとの差分とRun未変更を確認する（Q-COMP／Q-REL／Q-SEC、運用・移行）

## 2. Failing-First Request and Checkpoint Contracts

- [ ] 2.1 Adapter Testを先に追加し、thinking抑制policyが`reasoning_effort="none"`とJSON booleanの`chat_template_kwargs.enable_thinking=false`をstrict schemaの`response_format`と同じrequestへ一度だけ渡し、既定policyではtemplate引数を追加しないことを失敗確認する（Q-FUNC／Q-COMP／Q-MAIN）
- [ ] 2.2 STRUCTURE Testを先に追加し、vision／text両経路だけがthinking抑制policyを使用し、vision失敗時だけtextへ逐次fallbackし、Translation／Review／FIX／VERIFY／ALIGNのrequest policyと同時実行数1が変わらないことを失敗確認する（Q-FUNC／Q-PERF／Q-COMP）
- [ ] 2.3 Adapter Testでtemplate field拒否の400が一回で停止し、AIMessage／SDK双方の`finish_reason=length`が途中内容をparseせず既存`output-truncated`へ分類され、raw prompt／response／reasoningをErrorへ含めないことを確認する（Q-REL／Q-USE／Q-SEC）
- [ ] 2.4 page checkpoint Testを先に追加し、旧versionまたはthinking policyが異なるpageを再利用せず、同一policy／schemaだけをAtomic再利用し、公開Run fingerprintが不変であることを失敗確認する（Q-COMP／Q-REL、移行／Rollback）

## 3. Minimal Template-Control Implementation

- [ ] 3.1 `translate/adapters/llm.py`へ後方互換な型付きthinking policyを追加し、抑制時だけnested template optionと`reasoning_effort=none`を最終request bodyへ構成して2.1および2.3を成功させる。prompt instruction、native API、Dependencyおよび暗黙fallbackは追加しない（Q-FUNC／Q-MAIN／Q-PORT）
- [ ] 3.2 `translate/tasks/structure.py`のvision／textだけへthinking抑制policyを指定し、他Taskのreasoning／requestと逐次fallbackを維持して2.2を成功させる（Q-FUNC／Q-PERF／Q-COMP）
- [ ] 3.3 `PAGE_CHECKPOINT_VERSION`とpage keyへthinking policyを含め、旧page miss／新page hit、Atomic publishおよび公開fingerprint不変を確認して2.4を成功させる（Q-COMP／Q-REL、移行／Rollback）

## 4. Automated Quality, Security and Lifecycle Gates

- [ ] 4.1 Adapter、STRUCTURE、checkpoint、Failure、Resume、WorkflowおよびAtomic Artifactのfocused Testを成功させ、request回数／順序、400即時停止、有限retry、truncation非採用、部分Artifact公開0件および旧Failure読取りを確認する（Q-FUNC／Q-REL／Q-COMP）
- [ ] 4.2 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest -q`を成功させ、Dependency lock、公開CLI／Run schema／fingerprint、他Task requestおよびOS固有製品分岐の差分0件を確認する（Q-MAIN／Q-PORT／Q-COMP、取得／供給）
- [ ] 4.3 Test output、console、Failure、run metadata、checkpoint、logおよびChange Evidenceを走査し、Credential、endpoint、prompt、本文、reasoning本文、raw response、tracebackおよび画像binaryの漏えい0件を記録する（Q-SEC／Q-USE、Support）
- [ ] 4.4 `openspec validate bound-structure-reasoning-with-template-control --strict`を成功させ、正本Specに未同期deltaがなく`skip_specs: true`が実装修正の範囲と一致することを確認する（Q-MAIN、保守）

## 5. Sequential Real Page Proof

- [ ] 5.1 4章成功後にruntimeのModel、context 30,208、parallel 1、queued 0／idleおよび他Model／Embedding request 0件を確認し、request timeout 900秒、retry 1、逐次実行のpage 3 probe条件を記録する。条件不一致ならModel requestを送らず停止する（Q-PERF／Q-REL、運用）
- [ ] 5.2 保存済み入力とSTRUCTURE rulesを使用してpage 3をRun外の一時directoryで一度だけ実行し、vision一回、失敗時だけtext一回の順序を守る。`finish_reason=stop`、完全`StructureResponse`、Pydantic適合、非truncationおよび有限wall timeを全て満たさなければ追加requestとRun Resumeを行わず停止する（Q-FUNC／Q-PERF／Q-REL）
- [ ] 5.3 page 3のmode、finish reason、schema適合性、attempt、wall timeおよび非負のtoken usageだけをEvidenceへ記録し、reasoning token countを合否条件に使わず、prompt、本文、reasoning本文、raw response、Credential、endpointおよび画像を保存していないことをscanする（Q-SEC／Q-USE）

## 6. Conditional Same-Run Resume and Handoff

- [ ] 6.1 page 3成功時だけRunのinput hash、fingerprint、SPLIT～LOAD aggregateおよび既存Artifactをbaselineと再比較し、Resume互換かつ既完了Taskが不変であることを確認する。差分があればResumeせず停止する（Q-COMP／Q-REL、移行）
- [ ] 6.2 公開`cli.py`から`--resume 01a0c97c-f5cf-7031-b808-4ad545133925`を一度だけ指定し、Model／Embeddingを逐次実行して未完了STRUCTURE以降を再開する。失敗時は追加ResumeせずFailureとcheckpointを保持する（Q-FUNC／Q-PERF／Q-REL、運用・Support）
- [ ] 6.3 Resume成功時にRun status、100%進捗、DOCX／Markdown／診断Artifact、表紙の一度だけの出力、page 1本文除外、Atomic publish、外部outputおよび既完了SPLIT～LOAD不変を検査し、失敗時は部分成果物を公開していないことを確認する（Q-FUNC／Q-REL／Q-COMP）
- [ ] 6.4 実装差分、Test、実機Evidence、Run状態、Security scan、Rollback、廃止影響および後続のComparison Review可否を`verification.md`へまとめ、全Taskと受入条件が成功した場合だけarchive可能と判定する（Q-MAIN／Q-SEC、保守・廃止）
