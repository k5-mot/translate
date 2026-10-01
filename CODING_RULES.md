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

- MUST; 再実装の前に導入済みVersionのAPIと、入出力、例外、Retry単位、
  永続化および副作用を比較し、同等の機能は既存APIへ委譲すること
- MUST; Module新設や共通化では、実際の利用元、責務、既存Codeまたは依存APIで
  不足する理由を説明すること。配置変更だけを重複機能の解消とみなさないこと

### 💬 コメント

- MUST; すべての関数とMethodに目的を説明するCommentを付けること。
  非公開、特殊Method、入れ子およびTest関数も対象とする
- SHOULD; PythonではDocstringを基本とし、定義に明確に対応する説明Commentも
  認める。自明でない入力制約、副作用および失敗条件も説明すること
- MUST; Lambdaは周囲の説明と合わせて意図を読み取れるようにし、実行する
  Python文字列内の関数も同じ基準で確認すること。説明のためだけのWrapperは
  追加しないこと
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

- MUST; 製品仕様で定めたPython対応Versionの範囲で実装すること
- MUST; 実行用Entry Pointは`main()`またはCLI Applicationと
  `if __name__ == "__main__":`で実行境界を明示すること
- MAY; 内部Moduleには、開発時のDebugに有用な場合に限り、簡易な`main()`と
  `if __name__ == "__main__":`を設けてもよい
- MUST; 内部ModuleのDebug Entry Pointは既存Functionへ委譲し、製品処理を
  再実装しないこと
- MUST NOT; 直接実行する用途がないPython Fileへ形式的なEntry Pointを追加しないこと
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

### ⚙️ 品質検査の参考設定

次はLintとFormatの参考例である。Projectの実際の設定を置き換えるものではない。

```toml
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
```

### 📝 Docstring

Pythonの関数およびMethodのDocstringはGoogle Styleを基準とする。

本節では、配布対象のPython PackageおよびApplication Entry Pointを製品Codeとする。
`tests/`配下のTest Case、FixtureおよびTest専用HelperをTest Codeとする。

すべてのPython Codeには、次の共通規則を適用する。

- MUST; すべての関数およびMethodにDocstringを記載すること。非公開関数、
  特殊Method、入れ子関数およびTest関数も対象とする
- MUST; Docstringの先頭に、関数の目的を簡潔に表す説明Titleを記載すること
- MUST; 関数が送出または下位処理から伝播し、呼び出し元が処理する必要のある
  例外は、`Raises:`へ例外と発生条件を記載すること
- MUST; `yield`を使用する関数では`Yields:`を記載し、生成する値の型および
  意味を記載すること。この場合、`Returns:`は記載しないこと
- MUST NOT; 実装にない検証、例外、副作用または性能特性をDocstringへ記載しないこと
- MUST NOT; 各Sectionを形式的に埋めるため、複数の関数へ流用できる定型文を
  記載しないこと
- MUST; Docstringの内容を実装と一致させ、引数、戻り値、例外、生成値または
  振る舞いを変更した場合は同じ変更でDocstringを更新すること

製品Codeには、次の規則も適用する。

- MUST; `self`および`cls`を除く引数を持つ関数では、すべての引数を`Args:`へ
  記載し、処理上の用途を説明すること。必要に応じて単位、範囲、許容値および
  欠損時の扱いも記載すること
- MUST; `None`以外の値を返す関数では、`Returns:`へ戻り値の意味を記載すること。
  必要に応じて形式、順序および欠損時の扱いも記載すること
- MUST; Titleだけでは処理方式、入出力の制約、副作用、状態遷移または失敗条件が
  明確にならない場合、Titleの後に空行を設けて本文を記載すること
- MAY; 引数を持たず、値を返さない単純な関数、特殊MethodまたはPropertyでは、
  Titleだけの一行Docstringを使用してもよい
- SHOULD; Repository外から直接利用される公開APIで、型注釈と説明だけでは
  使用方法が明確でない場合、`Examples:`へ代表的な使用方法を記載すること
- SHOULD; 利用時に知る必要がある注意事項または制約がある場合、`Note:`へ
  記載すること

Test Codeには、次の規則を適用する。

- MAY; Test名と説明Titleから検証目的が明確な場合、一行Docstringを使用してもよい
- MUST; Test名と説明Titleだけでは前提条件、操作または期待結果が明確にならない場合、
  Titleの後に空行を設けて本文を記載すること
- MAY; Test関数、FixtureおよびTest専用Helperでは、引数と戻り値の役割がTest Code
  から明確な場合、`Args:`および`Returns:`を省略してもよい
- MUST NOT; Test Codeへ形式を満たすことだけを目的とした`Examples:`または`Note:`を
  記載しないこと

製品Codeの基本形は次のとおりとする。

```python
def sha256_file(path: Path) -> str:
    """File内容のSHA-256 Hashを返す。

    Fileを分割して読み込むため、全内容をMemoryへ読み込まずに計算する。

    Args:
        path (Path): Hashを計算するFileのPath。

    Returns:
        str: 小文字の16進数で表した64文字のSHA-256 Hash値。

    Raises:
        OSError: Fileを開けない、または読み込めない場合。
    """
```

Generatorでは`Returns:`の代わりに`Yields:`を使用する。

```python
def iter_items() -> Iterator[str]:
    """要素を順番に取得する。

    利用可能な要素を一件ずつ返す。

    Yields:
        str: 取得した要素。

    Examples:
        要素を順番に処理する。

        >>> for item in iter_items():
        ...     print(item)

    Note:
        要素の返却順序は保証しない。
    """
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
