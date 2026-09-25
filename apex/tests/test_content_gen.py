"""
Tests for apex.engine.content_gen — all five generation functions.

Run with::

    pytest tests/test_content_gen.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure apex is importable from the repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from typing import Self

from apex.engine import (
    generate_code_example,
    generate_diagram,
    generate_pdf,
    generate_voice,
    markdown_to_exercise,
)

OUTPUT_DIR = REPO_ROOT / "outputs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _EnvVar:
    """Context manager that sets an environment variable temporarily."""

    def __init__(self, name: str, value: str | None) -> None:
        self.name = name
        self.value = value
        self.old: str | None = None

    def __enter__(self) -> Self:
        self.old = os.environ.get(self.name)
        if self.value is None:
            os.environ.pop(self.name, None)
        else:
            os.environ[self.name] = self.value
        return self

    def __exit__(self, *args: object) -> None:
        if self.old is None:
            os.environ.pop(self.name, None)
        else:
            os.environ[self.name] = self.old


# ---------------------------------------------------------------------------
# 1. generate_diagram
# ---------------------------------------------------------------------------


class TestGenerateDiagram:
    def test_returns_non_empty_svg(self) -> None:
        result = generate_diagram("test topic")
        assert isinstance(result, str)
        assert len(result) > 0
        assert "<svg" in result
        assert "</svg>" in result

    def test_returns_svg_with_viewbox(self) -> None:
        result = generate_diagram("flow of data")
        assert "viewBox" in result or "viewbox" in result.lower() or "xmlns" in result

    def test_empty_topic_returns_default(self) -> None:
        result = generate_diagram("")
        assert isinstance(result, str)
        assert len(result) > 0
        assert "<svg" in result

    def test_style_param_ignored(self) -> None:
        result_default = generate_diagram("foo")
        result_alt = generate_diagram("foo", style="png")
        assert isinstance(result_default, str)
        assert isinstance(result_alt, str)

    def test_valid_svg_structure(self) -> None:
        result = generate_diagram("hierarchy of life")
        assert result.startswith(("<svg", "<svg"))
        assert result.rstrip().endswith("</svg>")


# ---------------------------------------------------------------------------
# 2. generate_code_example
# ---------------------------------------------------------------------------

KNOWN_CONCEPTS = [
    "loop",
    "function",
    "class",
    "recursion",
    "sort",
    "search",
    "file_io",
    "api",
    "database",
]


class TestGenerateCodeExample:
    def _assert_structure(self, result: dict[str, object], concept: str) -> None:
        assert isinstance(result, dict)
        assert set(result.keys()) == {"code", "explanation", "difficulty", "tags"}
        assert isinstance(result["code"], str)
        assert len(result["code"]) > 0
        assert isinstance(result["explanation"], str)
        assert isinstance(result["difficulty"], str)
        assert isinstance(result["tags"], list)
        assert all(isinstance(t, str) for t in result["tags"])

    @pytest.mark.parametrize("concept", KNOWN_CONCEPTS)
    def test_known_concepts_return_valid_structure(self, concept: str) -> None:
        result = generate_code_example(concept)
        self._assert_structure(result, concept)

    def test_python_code_contains_keywords(self) -> None:
        result = generate_code_example("loop", language="python")
        assert "for" in result["code"] or "while" in result["code"]

    def test_unknown_concept_returns_generic(self) -> None:
        result = generate_code_example("nonexistent_concept_xyz")
        self._assert_structure(result, "nonexistent_concept_xyz")
        assert "generic" in result["tags"][0].lower() or "placeholder" in result["tags"][0].lower()

    @pytest.mark.parametrize("lang", ["javascript", "java", "cpp"])
    def test_non_python_language_returns_stub(self, lang: str) -> None:
        result = generate_code_example("loop", language=lang)
        self._assert_structure(result, "loop")
        assert lang in result["code"].lower() or "stub" in result["code"].lower()

    def test_empty_concept_returns_generic(self) -> None:
        result = generate_code_example("")
        self._assert_structure(result, "")
        assert len(result["code"]) > 0

    def test_whitespace_concept_treated_as_unknown(self) -> None:
        result = generate_code_example("   \t  ")
        self._assert_structure(result, "   \t  ")
        assert any(t in result["tags"] for t in ["generic", "placeholder"])


# ---------------------------------------------------------------------------
# 3. generate_voice
# ---------------------------------------------------------------------------


class TestGenerateVoice:
    def test_returns_path_with_tts_disabled(self, tmp_path: Path) -> None:
        with _EnvVar("HERMES_TTS_AVAILABLE", "0"):
            result = generate_voice("Hello world")
        assert isinstance(result, str)
        assert len(result) > 0
        assert Path(result).exists()
        assert Path(result).suffix == ".txt"

    def test_returns_path_for_empty_text(self, tmp_path: Path) -> None:
        with _EnvVar("HERMES_TTS_AVAILABLE", "0"):
            result = generate_voice("")
        assert isinstance(result, str)
        assert Path(result).exists()

    def test_stub_file_contains_original_text(self, tmp_path: Path) -> None:
        with _EnvVar("HERMES_TTS_AVAILABLE", "0"):
            result = generate_voice("Sample text for verification")
        content = Path(result).read_text(encoding="utf-8")
        assert "Sample text for verification" in content

    def test_voice_param_accepted(self, tmp_path: Path) -> None:
        with _EnvVar("HERMES_TTS_AVAILABLE", "0"):
            result = generate_voice("test", voice="female")
        assert isinstance(result, str)
        assert Path(result).exists()


# ---------------------------------------------------------------------------
# 4. generate_pdf
# ---------------------------------------------------------------------------

MARKDOWN_DOC = """# Test Handout

This is a **sample** document with some `code`.

## Section

- item 1
- item 2
"""


class TestGeneratePdf:
    def test_produces_pdf_over_zero_bytes(self, tmp_path: Path) -> None:
        with _EnvVar("APEX_OUTPUT_DIR", str(tmp_path)):
            result = generate_pdf(MARKDOWN_DOC)
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_pdf_has_pdf_magic_bytes(self, tmp_path: Path) -> None:
        with _EnvVar("APEX_OUTPUT_DIR", str(tmp_path)):
            result = generate_pdf(MARKDOWN_DOC)
        magic = Path(result).read_bytes()[:5]
        assert magic == b"%PDF-", f"Expected PDF magic bytes, got {magic!r}"

    @pytest.mark.parametrize("template", ["handout", "cheat_sheet", "lesson_plan"])
    def test_all_templates_produce_pdf(self, template: str, tmp_path: Path) -> None:
        with _EnvVar("APEX_OUTPUT_DIR", str(tmp_path)):
            result = generate_pdf(MARKDOWN_DOC, template=template)
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_unknown_template_falls_back(self, tmp_path: Path) -> None:
        with _EnvVar("APEX_OUTPUT_DIR", str(tmp_path)):
            result = generate_pdf(MARKDOWN_DOC, template="nonexistent")
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_empty_content_produces_pdf(self, tmp_path: Path) -> None:
        with _EnvVar("APEX_OUTPUT_DIR", str(tmp_path)):
            result = generate_pdf("")
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0


# ---------------------------------------------------------------------------
# 5. markdown_to_exercise
# ---------------------------------------------------------------------------


class TestMarkdownToExercise:
    def test_fill_blank_pattern(self) -> None:
        md = "??? The capital of France is ______."
        result = markdown_to_exercise(md)
        assert len(result) == 1
        ex = result[0]
        assert ex["type"] == "fill_blank"
        assert "capital of France" in ex["question"]

    def test_coding_pattern(self) -> None:
        md = ">>> write a function to add two numbers"
        result = markdown_to_exercise(md)
        assert len(result) == 1
        ex = result[0]
        assert ex["type"] == "coding"
        assert "add two numbers" in ex["question"]

    def test_mcq_pattern(self) -> None:
        md = "Q: What is 2+2? A: 4"
        result = markdown_to_exercise(md)
        assert len(result) == 1
        ex = result[0]
        assert ex["type"] == "mcq"
        assert "2+2" in ex["question"]
        assert "4" in ex["answer"]

    def test_separator_produces_multiple_exercises(self) -> None:
        md = "??? first blank\n---\n??? second blank"
        result = markdown_to_exercise(md)
        assert len(result) == 2
        assert result[0]["type"] == "fill_blank"
        assert result[1]["type"] == "fill_blank"

    def test_mixed_patterns(self) -> None:
        md = """??? fill in the blank
>>> write hello world
Q: Capital of Italy? A: Rome
"""
        result = markdown_to_exercise(md)
        assert len(result) == 3
        types = [ex["type"] for ex in result]
        assert "fill_blank" in types
        assert "coding" in types
        assert "mcq" in types

    def test_empty_input_returns_empty_list(self) -> None:
        assert markdown_to_exercise("") == []
        assert markdown_to_exercise("   \n\n  ") == []

    def test_only_separators_returns_empty(self) -> None:
        assert markdown_to_exercise("---") == []
        assert markdown_to_exercise("---\n---\n---") == []

    def test_question_without_answer_ignored(self) -> None:
        md = "Q: unanswered question"
        result = markdown_to_exercise(md)
        assert len(result) == 0

    def test_mcq_multiline_question(self) -> None:
        md = "Q: What is the largest planet?\nIt orbits the sun.\nA: Jupiter"
        result = markdown_to_exercise(md)
        assert len(result) == 1
        assert "largest planet" in result[0]["question"]

    def test_stripped_fill_blank_prefix(self) -> None:
        md = "    ??? indented blank"
        result = markdown_to_exercise(md)
        assert len(result) == 1
        assert result[0]["type"] == "fill_blank"

    def test_stripped_coding_prefix(self) -> None:
        md = "    >>> indented code"
        result = markdown_to_exercise(md)
        assert len(result) == 1
        assert result[0]["type"] == "coding"

    def test_all_exercises_have_required_keys(self) -> None:
        md = """??? blank
>>> code
Q: Q? A: A
"""
        result = markdown_to_exercise(md)
        for ex in result:
            assert set(ex.keys()) == {"type", "question", "answer", "explanation"}
            assert isinstance(ex["type"], str)
            assert isinstance(ex["question"], str)
            assert isinstance(ex["answer"], str)
            assert isinstance(ex["explanation"], str)

    def test_mcq_with_colon_in_question(self) -> None:
        md = "Q: What does print() do? A: Outputs text"
        result = markdown_to_exercise(md)
        assert len(result) == 1
        assert "print()" in result[0]["question"]


# ---------------------------------------------------------------------------
# Integration / smoke test
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline(self, tmp_path: Path) -> None:
        with _EnvVar("HERMES_TTS_AVAILABLE", "0"), _EnvVar("APEX_OUTPUT_DIR", str(tmp_path)):
            svg = generate_diagram("flow of data")
            assert "<svg" in svg

            code = generate_code_example("function")
            assert "def " in code["code"]

            voice = generate_voice("hello")
            assert Path(voice).exists()

            pdf = generate_pdf("# Hi", template="handout")
            assert Path(pdf).stat().st_size > 0

            exercises = markdown_to_exercise("??? test")
            assert len(exercises) == 1
