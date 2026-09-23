<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: ローカルLLMのrequest timeoutを有限範囲で設定する

Systemは、ローカルOpenAI互換LLMの生成に十分な既定request timeoutを適用しなければならない（MUST）。timeoutは正の有限値で、`TRANSLATE_REQUEST_TIMEOUT_SECONDS`による明示上書きを受け付けなければならない（MUST）。timeout、retry回数、backoffおよびtask deadlineはそれぞれ有限であり、Model／Embeddingを並列実行してはならない（MUST NOT）。timeout後はTaskをResume可能なFailureとして停止し、固定されたinvoke stageとcauseだけを保存しなければならない（MUST）。

#### Scenario: 既定timeoutで長いローカル生成を許容する

- **WHEN** timeout環境変数が指定されず、ローカルLLMが既定値以内に応答する
- **THEN** Systemは既定の十分なtimeoutをChatOpenAIへ渡し、応答検証と後続Taskへ進む

#### Scenario: 利用者がtimeoutを明示する

- **WHEN** `TRANSLATE_REQUEST_TIMEOUT_SECONDS`へ正の有限秒数が指定される
- **THEN** Systemはその値を採用し、retry／task deadlineを超えない範囲で逐次実行する

#### Scenario: timeoutが発生する

- **WHEN** ローカルLLMがrequest timeout内に応答しない
- **THEN** Systemは`text-invoke`または`vision-invoke`、固定causeおよび対象Taskを秘密非含有Failure／Terminal Evidenceへ保存し、Runを停止して明示Resume可能にする

