# 📜 コーディング規約

本書は、このRepositoryで実装する際の共通規則と、Python、TypeScript、
Java固有の規則を定める。

## 🧭 共通規則

### 🪶 実装の単純性（Implementation simplicity）

現在の要求を満たす最も単純な実装を優先する。

- MUST; 妥当な範囲で最小の差分にすること
- MUST NOT; 将来の仮想的な要求のために抽象化を導入しないこと
- MUST NOT; 現在の必要性を解決しないLayer、Service、Factory、Wrapper、
  InterfaceまたはHelperを追加しないこと
- SHOULD; 新しいFileを作る前に既存実装の変更を優先すること
- MUST NOT; 必要性を説明できないDependencyを追加しないこと
- MUST NOT; 1か所だけで使うCodeを一般化しないこと
- MUST; YAGNIに従うこと。小規模な重複は早すぎる抽象化より優先する
- MUST; Repositoryの既存Architecture Levelを維持し、無関係なArchitectureを
  改善しないこと
- MUST; 完了前に、その変更で導入した不要な抽象化または間接層を除去すること

既存Code、標準Library、Platform機能、導入済みDependencyの順に再利用を検討する。
依存Packageが解決する処理を、正当な理由なくScratch実装してはならない。

### 💬 コメント

- MUST; 設定値、定数および閾値には、目的、単位、有効範囲または採用理由が
  自明でない場合、保守者が判断根拠を理解できる説明Commentを付けること
- MUST; 複雑なAlgorithm、分岐、状態遷移または制約には、処理の意図、理由および
  前提が分かる説明Commentを適切な粒度で付けること
- MUST NOT; Codeを読めば分かる処理を、行単位で言い換えるだけのCommentを
  追加しないこと
- MUST; Code変更でCommentの内容が古くなった場合は、同じ変更で更新または
  削除すること

### ✅ 共通完了条件

- MUST; 変更範囲に対応するFormat、Lint、型検査およびTestを実行すること
- MUST; 実行できない検査がある場合は、未実行理由を完了報告へ記載すること
- MUST NOT; 無関係なFileを一括FormatまたはRefactorしないこと
- MUST; Secret、Credential、生成物および一時Fileが差分へ混入していないことを
  確認すること

## 🐍 Python

### 🧰 実装と実行

- MUST; Python 3.12以上を使用すること
- MUST; 製品として直接実行を保証するEntry Pointを`cli.py`と`main.py`に限定すること
- MUST; 製品Entry Pointは`main()`またはCLI Applicationと
  `if __name__ == "__main__":`で実行境界を明示すること
- MAY; 内部Moduleには、開発時のDebugに有用な場合に限り、簡易な`main()`と
  `if __name__ == "__main__":`を設けてもよい
- MUST NOT; 内部ModuleのDebug Entry Pointを公開Interfaceとして扱わないこと
- MUST; 内部ModuleのDebug Entry Pointは既存Functionへ委譲し、製品処理を
  再実装しないこと
- MUST NOT; 直接実行する用途がないPython Fileへ形式的なEntry Pointを追加しないこと
- MUST; `time.perf_counter()`で各Taskの経過時間を計測可能にすること
- SHOULD; Path操作には`pathlib`、Process実行には`subprocess.run()`を使用すること
- MUST; RuffのLintとFormat検査を通すこと
- MUST; 型検査が構成されているProjectでは`ty check`を通すこと
- MUST; TestがあるProjectでは`pytest`を通すこと

標準Commandは次のとおりとする。

```bash
# Dependencyを同期し、Python品質検査を実行する。
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

### 📦 推奨Package

次のPackageは、現在のTaskで該当機能が必要な場合に限り優先して検討する。
推奨は導入必須を意味しない。

| 用途 | 推奨Package |
| --- | --- |
| Browser操作・E2E | `playwright` |
| 表形式Data処理 | `polars` |
| 環境・Dependency管理 | `uv` |
| Lint・Format | `ruff` |
| 型検査 | `ty` |
| HTTP Client | `httpx` |
| CLI | `typer` |
| Data検証・設定Model | `pydantic` |

### ⚙️ `pyproject.toml`参考設定

次はAgent／RAG用途を含むProject向けの参考例である。新規Projectへ一括適用せず、
実際に使用するDependencyとPathだけを残すこと。

```toml
[project]
name = "agent-skills"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.28.1",
  "openai>=2.8.1",
  "pillow>=12.0.0",
  "portalocker>=3.2.0,<4",
  "pypdfium2>=5.13.0,<6",
  "pydantic>=2.12.5",
  "python-dotenv>=1.2.1",
  "typer>=0.20.0",
  "langchain>=1.4.0",
  "langchain-openai>=1.6.0",
  "langchain-qdrant>=1.1.0",
  "langgraph>=1.2.11",
  "langgraph-checkpoint-sqlite>=3.1.1",
  "langfuse>=3,<5",
  "qdrant-client>=1.16.0,<2",
  "typing-extensions>=4.16.0",
  "streamlit>=1.64.0",
]

[dependency-groups]
dev = ["pytest>=9.1.1", "ruff>=0.15.22", "ty>=0.0.61"]

[tool.ruff]
line-length = 88
indent-width = 4

[tool.ruff.lint]
select = [
  "E", "W", "F", "I",
  "UP", "FA", "FURB",
  "B", "BLE", "C4", "DTZ", "PIE", "RSE", "RET", "SIM", "SLOT",
  "TRY", "RUF",
  "ANN", "TC", "PYI",
  "ASYNC",
  "S",
  "C90", "PL", "PERF", "ARG", "ERA",
  "A", "FBT", "SLF", "N",
  "EM", "G", "LOG",
  "PTH",
  "ICN", "INP", "TID",
  "PT",
  "T10", "T20",
  "Q", "ISC", "COM",
  "EXE", "PGH", "YTT",
]

# Ruff Formatterと競合するRuleを除外する。
ignore = [
  "W191", "E111", "E114", "E117",
  "D203", "D206", "D300",
  "Q000", "Q001", "Q002", "Q003", "Q004",
  "COM812", "COM819",
  "ISC002",
]

[tool.ruff.lint.mccabe]
max-complexity = 8

[tool.ruff.lint.pylint]
max-args = 5
max-branches = 8
max-returns = 5
max-statements = 40

# Testではassertを使用するためBanditのS101を除外する。
[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101", "PLR2004"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
line-ending = "lf"
docstring-code-format = true
docstring-code-line-length = "dynamic"

[tool.ty.src]
exclude = [".agents", "tests"]
```

## 🟦 TypeScript

### 🟦 実装と検証

- MUST; Project既存のPackage Managerと`package.json` Scriptを使用すること
- MUST; `strict` Type Checkを有効にし、型Errorを残さないこと
- MUST NOT; 理由のない`any`、型Assertionまたは`@ts-ignore`を追加しないこと
- SHOULD; BrowserまたはRuntimeの標準APIを第三者Packageより優先すること
- MUST; Projectで構成されたFormat、Lint、型検査およびTestを通すこと

標準的なScript名がある場合は次を使用する。

```bash
# Project既存のScriptでTypeScript品質検査を実行する。
npm run format --if-present
npm run lint
npm run typecheck
npm test
```

## ☕ Java

### ☕ 実装と検証

- MUST; Project既存のJava VersionとMavenまたはGradle Wrapperを使用すること
- MUST NOT; 既存ProjectにないFrameworkまたはAnnotation Processorを、
  Boilerplate削減だけを理由に追加しないこと
- SHOULD; Value Objectには、既存Versionで利用可能な場合`record`を検討すること
- MUST; Compiler Warning、構成済みFormatter、静的解析およびTestを通すこと
- MUST; 外部Process、FileおよびNetworkのErrorを握りつぶさないこと

Projectに応じて、次のいずれかを使用する。

```bash
# Maven Wrapperを使用して検証する。
./mvnw verify

# Gradle Wrapperを使用して検証する。
./gradlew check
```

## 🔖 参考文献

- [Python documentation](https://docs.python.org/3/)
- [Ruff documentation](https://docs.astral.sh/ruff/)
- [ty documentation](https://docs.astral.sh/ty/)
- [TypeScript documentation](https://www.typescriptlang.org/docs/)
- [Java documentation](https://docs.oracle.com/en/java/)
