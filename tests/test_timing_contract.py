"""Taskと公開entry pointの経過時間出力を検証する。"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from translate.document import Document, Page
from translate.tasks import base, check, docx
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_NAMES = (
    "align",
    "check",
    "cover",
    "docling",
    "docx",
    "fix",
    "load",
    "markdown",
    "merge",
    "normalize",
    "position",
    "report",
    "review",
    "split",
    "structure",
    "translate",
    "translate_lite",
    "unpack",
    "validate",
    "verify",
)


def test_every_task_uses_shared_timing_without_another_state_store() -> None:
    """全Taskを検査対象に含め、手書き計測と独立状態を増やさない。"""

    task_modules = {
        path.stem: path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "translate" / "tasks").glob("*.py")
        if path.stem not in {"__init__", "base"}
    }

    assert set(task_modules) == set(TASK_NAMES)
    assert all("perf_counter" not in source for source in task_modules.values())
    assert all("with self.measure():" in source for source in task_modules.values())
    assert "time.perf_counter()" in inspect.getsource(base)
    assert "translate.common" not in inspect.getsource(base)
    assert "translate.workflows" not in inspect.getsource(base)
    for entry_point in (PROJECT_ROOT / "cli.py", PROJECT_ROOT / "main.py"):
        source = entry_point.read_text(encoding="utf-8")
        assert "time.perf_counter()" in source
        assert "[TIME] TOTAL" in source
    assert not list(PROJECT_ROOT.rglob("*timing-state*"))


@pytest.mark.parametrize("name", TASK_NAMES)
@pytest.mark.parametrize("use_defaults", [False, True])
def test_function_delegates_all_typed_arguments_to_task(
    name: str, monkeypatch: pytest.MonkeyPatch, *, use_defaults: bool
) -> None:
    """全具体Taskの継承・signature・戻り値と既定値を含む転送を確認する。"""

    module: ModuleType = importlib.import_module(f"translate.tasks.{name}")
    task_type = getattr(
        module, "".join(part.title() for part in name.split("_")) + "Task"
    )
    assert issubclass(task_type, BaseTask)
    assert task_type.name == name.upper().replace("_", "-")
    expected_signature = inspect.signature(module.run)
    assert inspect.signature(task_type().run) == expected_signature
    positional = []
    keywords = {}
    for parameter in expected_signature.parameters.values():
        if use_defaults and parameter.default is not inspect.Parameter.empty:
            continue
        value = object()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            keywords[parameter.name] = value
        else:
            positional.append(value)
    expected = expected_signature.bind(*positional, **keywords)
    expected.apply_defaults()
    result = object()
    calls = []

    def invoke(_self: BaseTask, *args: object, **kwargs: object) -> object:
        """転送された引数を元signatureへ束縛し、同じ結果を返す。"""

        calls.append(expected_signature.bind(*args, **kwargs).arguments)
        return result

    monkeypatch.setattr(task_type, "run", invoke)
    assert module.run(*positional, **keywords) is result
    assert calls == [expected.arguments]


@pytest.mark.parametrize("fail", [False, True])
def test_timing_occurs_once_and_preserves_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fail: bool,
) -> None:
    """成功でも失敗でも一度計測し、失敗本文を出さず元例外を伝播する。"""

    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(base, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))
    error = ValueError("private response body")

    def convert(_markdown: Path, _output: Path, _template: Path) -> None:
        """外部変換を呼ばず、成功または同一例外を返す。"""

        if fail:
            raise error

    monkeypatch.setattr(docx, "create_docx", convert)
    output = tmp_path / "out.docx"
    if fail:
        with pytest.raises(ValueError, match="private response body") as raised:
            docx.run(tmp_path / "in.md", output, tmp_path / "template.docx")
        assert raised.value is error
    else:
        assert (
            docx.run(tmp_path / "in.md", output, tmp_path / "template.docx") == output
        )
    assert capsys.readouterr().out == "[TIME] DOCX page=- group=-: 2.500 s\n"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["merge", "structure", "markdown"])
def test_timing_finishes_after_atomic_publication(
    name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """従来は内側で終了していた計測が最終directory公開後に終わる。"""

    module = importlib.import_module(f"translate.tasks.{name}")
    output_dir = tmp_path / name
    published = output_dir / "document.json"
    clock_calls = []

    def clock() -> float:
        """開始時は未公開、終了時は公開済みのArtifactを確認する。"""

        clock_calls.append(published.exists())
        return float(len(clock_calls))

    def generate(*args: object) -> object:
        """最小Artifactをstaging内に作り、Taskの既存公開処理へ渡す。"""

        if name == "structure":
            return Document(pages=[])
        staging = args[1].parent if name == "markdown" else args[2]
        (staging / "document.json").write_text("{}", encoding="utf-8")
        return staging / "document.json"

    monkeypatch.setattr(base, "time", SimpleNamespace(perf_counter=clock))
    monkeypatch.setattr(module, "_run_into", generate)
    if name == "structure":
        module.run(Document(pages=[]), tmp_path / "in.pdf", "", None, output_dir)
    elif name == "markdown":
        module.run(Document(pages=[]), output_dir / "document.json")
    else:
        module.run([], tmp_path / "in.pdf", output_dir)
    assert clock_calls == [False, True]


def test_task_timing_includes_task_page_and_group_identifiers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """計測行からTaskとpage/group対象を識別できる。"""

    check.run(Document(pages=[Page(number=2)]), None, tmp_path / "check")

    output = capsys.readouterr().out
    assert "[TIME] CHECK" in output
    assert "page=" in output
    assert "group=" in output
