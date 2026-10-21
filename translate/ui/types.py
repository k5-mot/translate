"""Streamlit UI types module."""

from __future__ import annotations

import re
from importlib import import_module
from typing import Literal

from translate.models.artifacts import (
    RegistrationRecord,
    ReviewRecord,
    TaskName,
    TranslationRecord,
)
from translate.models.upgrade import (
    UpgradeRecord,
)

ProcessingKind = Literal["translate", "review", "register", "upgrade"]

StructureResponse = import_module("translate.tasks.13_structure").StructureResponse

TaskStage = tuple[str, TaskName, str | None]

StructurePatch = import_module("translate.tasks.13_structure").StructurePatch

TranslationResponse = import_module("translate.tasks.30_translate").TranslationResponse

_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

_REGISTER_SUFFIXES = {".pdf"}

_MARKDOWN_IMAGE_BLOCK = re.compile(
    r"(?m)^!\[(?P<caption>(?:\\.|[^\]])*)\]"
    r"\((?P<target>[^)]+)\)(?:\{[^\n]*\})?[ \t\r]*$"
)

ProcessingRecord = TranslationRecord | ReviewRecord | RegistrationRecord | UpgradeRecord
