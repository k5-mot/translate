<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## Q-MAIN Verification Evidence

検証日: 2026-09-20

| Command | Result | Evidence |
| --- | --- | --- |
| `uv sync --dev` | PASS | 117 packages resolved、115 packages checked |
| `uv run ruff check .` | PASS | `All checks passed!` |
| `uv run ruff format --check .` | PASS | 102 files already formatted |
| `uv run ty check` | PASS | `All checks passed!` |
| `uv run pytest` | PASS | 95 passed in 4.08s |

`ty`の対象はProject Runtime codeである。Project外toolingの`.agents/`と、Runtime型検査とは別にpytest/Ruffで検証する`tests/`は`tool.ty.src.exclude`へ明示した。全Testは上記pytest実行に含まれ、CLI、Streamlit browser harness、Capability、障害注入およびSecurity Scenarioを含む。
