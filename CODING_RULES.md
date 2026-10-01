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

- MUST; すべての関数およびMethodにDocstringを記載すること。非公開関数、
  特殊Method、入れ子関数およびTest関数も対象とする
- MUST; Docstringの先頭に、関数の目的を簡潔に表す説明Titleを記載すること
- MAY; 説明Titleだけで契約を十分に表せる単純な関数、特殊Method、入れ子関数
  およびTest関数では、一行Docstringを使用してもよい
- MUST; 入出力の制約、副作用、状態遷移または失敗条件が説明Titleだけでは
  明確でない場合、Titleの後に空行を設けて本文を記載すること
- MUST; 名前と型注釈だけでは用途、単位、範囲または制約が明確でない引数は、
  `Args:`へ名前と説明を記載すること
- MUST; 型注釈だけでは戻り値の意味、順序または欠損時の扱いが明確でない場合、
  `Returns:`へ説明を記載すること
- MUST; 呼び出し元が処理する必要のある例外を明示的に送出する場合、`Raises:`へ
  例外と発生条件を記載すること
- MUST; `yield`を使用する関数では`Yields:`を記載し、生成する値の型および
  意味を記載すること
- SHOULD; Repository外から直接利用される公開APIで、型注釈だけでは使用方法が
  明確でない場合、`Examples:`へ代表的な使用方法を記載すること
- SHOULD; 利用時に知る必要がある注意事項または制約がある場合だけ、`Note:`を
  記載すること
- MUST NOT; `Args:`、`Returns:`、`Raises:`、`Examples:`または`Note:`を、
  形式を満たすためだけの定型文で追加しないこと
- MUST; Docstringの内容を実装と一致させ、引数、戻り値、例外、生成値または
  振る舞いを変更した場合は同じ変更でDocstringを更新すること

基本形は次のとおりとする。

```python
def example(name: str, enabled: bool = False) -> bool:
    """処理を実行する。

    指定された値を使用して対象の処理を実行する。

    Args:
        name (str): 処理対象の名前。
        enabled (bool, optional): 処理を有効化する場合はTrue。

    Returns:
        bool: 処理に成功した場合はTrue、失敗した場合はFalse。

    Raises:
        ValueError: nameが不正な場合に発生する。

    Examples:
        関数の基本的な使用方法を示す。

        >>> example("test", True)
        True

    Note:
        実行前に必要な初期化処理を完了しておくこと。
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
