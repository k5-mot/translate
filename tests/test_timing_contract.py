"""Taskと公開entry pointの経過時間出力を検証する。"""

from __future__ import annotations

import ast
import builtins
import importlib
import inspect
from functools import partial
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from translate_v1.document import Document, Page
from translate_v1.tasks import base, check, docx
from translate_v1.tasks.base import BaseTask

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


@pytest.fixture(params=["broken-pipe", "closed-stream", "io-error"])
def broken_timing_print(request: pytest.FixtureRequest) -> Mock:
    """実printへ壊れた出力先を渡し、試みた計測行と呼出回数を検査可能にする。"""

    stream = StringIO()
    if request.param == "closed-stream":
        stream.close()
    else:
        error = (
            BrokenPipeError("timing pipe unavailable")
            if request.param == "broken-pipe"
            else OSError("timing output unavailable")
        )
        stream.write = Mock(side_effect=error)
    return Mock(wraps=partial(builtins.print, file=stream))


def _run_public_boundary(name: str, body: Mock, output: Mock) -> None:
    """実Moduleのimportと__main__節を使い、処理本体だけを隔離して動的に実行する。"""

    module = importlib.import_module(f"{name}_v1")
    path = PROJECT_ROOT / f"{name}_v1.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    boundary = tree.body[-1]
    assert isinstance(boundary, ast.If)
    namespace = vars(module).copy()
    namespace.update(
        __name__="__main__",
        time=SimpleNamespace(perf_counter=Mock(side_effect=[10.0, 12.5])),
        print=output,
    )
    namespace["app" if name == "cli" else "main"] = body
    # 境界を複製せず製品ASTを実行し、実importに存在しない名前も検出する。
    code = compile(ast.Module(body=[boundary], type_ignores=[]), str(path), "exec")
    exec(code, namespace)  # noqa: S102


@pytest.mark.parametrize("fail", [False, True])
def test_task_result_survives_timing_output_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    broken_timing_print: Mock,
    capsys: pytest.CaptureFixture[str],
    *,
    fail: bool,
) -> None:
    """具体Taskの成功値・元例外・実行1回を保ち、壊れた出力先へ再通知しない。"""

    error = ValueError("private body credential-sentinel")
    convert = Mock(side_effect=error if fail else None)
    monkeypatch.setattr(docx, "create_docx", convert)
    monkeypatch.setattr(base, "print", broken_timing_print, raising=False)
    monkeypatch.setattr(
        base, "time", SimpleNamespace(perf_counter=Mock(side_effect=[10.0, 12.5]))
    )
    source, output, template = (
        tmp_path / name for name in ("in.md", "out.docx", "t.docx")
    )
    if fail:
        with pytest.raises(
            ValueError, match="private body credential-sentinel"
        ) as raised:
            docx.run(source, output, template)
        assert raised.value is error
    else:
        assert docx.run(source, output, template) == output
    convert.assert_called_once_with(source, output, template)
    broken_timing_print.assert_called_once_with("[TIME] DOCX page=- group=-: 2.500 s")
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("name", ["cli", "main"])
@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "failure",
        "exit-zero",
        "exit-error",
        "artifact",
        "checkpoint",
        "interrupt",
    ],
)
def test_public_result_survives_timing_output_failure(
    name: str,
    outcome: str,
    broken_timing_print: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """公開起動境界で成功・失敗・終了通知と保存障害を元のidentityのまま保持する。"""

    error = {
        "success": None,
        "failure": RuntimeError("private body credential-sentinel"),
        "exit-zero": SystemExit(0),
        "exit-error": SystemExit(7),
        "artifact": OSError("artifact persistence failed"),
        "checkpoint": ValueError("checkpoint persistence failed"),
        "interrupt": KeyboardInterrupt(),
    }[outcome]
    body = Mock(side_effect=error)
    if error is None:
        _run_public_boundary(name, body, broken_timing_print)
    else:
        with pytest.raises(type(error)) as raised:
            _run_public_boundary(name, body, broken_timing_print)
        assert raised.value is error
        if isinstance(error, SystemExit):
            assert raised.value.code == error.code
    body.assert_called_once_with()
    broken_timing_print.assert_called_once_with("[TIME] TOTAL: 2.500 s")
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("name", ["task", "cli", "main"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, RuntimeError])
def test_timing_does_not_suppress_interrupts_or_programming_errors(
    name: str,
    error_type: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """表示中の利用者中断・終了通知・対象外の不具合を広いexceptで隠さない。"""

    error = error_type("not a stream failure")
    output = Mock(side_effect=error)
    body = Mock()
    arguments = ()
    if name == "task":
        monkeypatch.setattr(base, "print", output, raising=False)
        monkeypatch.setattr(docx, "create_docx", body)
        arguments = tuple(tmp_path / item for item in ("in.md", "out.docx", "t.docx"))
        invoke = partial(docx.run, *arguments)
    else:
        invoke = partial(_run_public_boundary, name, body, output)
    with pytest.raises(error_type, match="not a stream failure") as raised:
        invoke()
    assert raised.value is error
    body.assert_called_once_with(*arguments)
    output.assert_called_once()


@pytest.mark.parametrize("name", ["cli", "main"])
@pytest.mark.parametrize("fail", [False, True])
def test_public_boundary_keeps_normal_stdout_format(
    name: str, capsys: pytest.CaptureFixture[str], *, fail: bool
) -> None:
    """正常なstdoutでは成功・失敗とも既存形式を一度だけ出し、本文を漏らさない。"""

    error = RuntimeError("private body credential-sentinel")
    body = Mock(side_effect=error if fail else None)
    output = Mock(wraps=builtins.print)
    if fail:
        with pytest.raises(
            RuntimeError, match="private body credential-sentinel"
        ) as raised:
            _run_public_boundary(name, body, output)
        assert raised.value is error
    else:
        _run_public_boundary(name, body, output)
    body.assert_called_once_with()
    output.assert_called_once_with("[TIME] TOTAL: 2.500 s")
    captured = capsys.readouterr()
    assert captured.out == "[TIME] TOTAL: 2.500 s\n"
    assert captured.err == ""


@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_task_does_not_suppress_persistence_failure(
    error_type: type[Exception],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    broken_timing_print: Mock,
) -> None:
    """Task内の必須保存も、出力障害と同じ例外型だからという理由で抑制しない。"""

    error = error_type("required persistence failed")
    save = Mock(side_effect=error)
    monkeypatch.setattr(docx, "create_docx", save)
    monkeypatch.setattr(base, "print", broken_timing_print, raising=False)
    source, output, template = (
        tmp_path / name for name in ("in.md", "out.docx", "t.docx")
    )
    with pytest.raises(error_type, match="required persistence failed") as raised:
        docx.run(source, output, template)
    assert raised.value is error
    save.assert_called_once_with(source, output, template)
    broken_timing_print.assert_called_once()


def test_every_task_uses_shared_timing_without_another_state_store() -> None:
    """全Taskの共通計測呼出と入口の計測表記、計測用状態File名の不在を静的検査する。"""

    task_modules = {
        path.stem: path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "translate_v1" / "tasks").glob("*.py")
        if path.stem not in {"__init__", "base"}
    }

    assert set(task_modules) == set(TASK_NAMES)
    assert all("perf_counter" not in source for source in task_modules.values())
    assert all("with self.measure():" in source for source in task_modules.values())
    assert "time.perf_counter()" in inspect.getsource(base)
    assert "translate_v1.common" not in inspect.getsource(base)
    assert "translate_v1.workflows" not in inspect.getsource(base)
    for entry_point in (PROJECT_ROOT / "cli_v1.py", PROJECT_ROOT / "main_v1.py"):
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

    module: ModuleType = importlib.import_module(f"translate_v1.tasks.{name}")
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
    """出力可能な環境で成功・例外時とも一行だけ計測し、同じ処理例外を伝える。"""

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

    module = importlib.import_module(f"translate_v1.tasks.{name}")
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
