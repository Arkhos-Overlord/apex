"""
Multi-modal content generation engine.

Provides diagram generation (SVG), code example generation, TTS voice
synthesis, PDF handout rendering, and markdown-to-exercise parsing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 1. Diagram generation
# ---------------------------------------------------------------------------

DIAGRAM_TYPE_KEYWORDS: dict[str, list[str]] = {
    "flowchart": ["flow", "process", "sequence", "pipeline", "workflow"],
    "tree": ["tree", "hierarchy", "nested", "org chart", "taxonomy"],
    "mindmap": ["mind", "map", "brainstorm", "concept", "relationship"],
}

DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "outputs"


def _detect_diagram_type(topic: str) -> str:
    """Map a topic string to a diagram type label."""
    lowered = topic.lower()
    for diagram_type, keywords in DIAGRAM_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in lowered:
                return diagram_type
    return "flowchart"


def _build_flowchart_svg(topic: str) -> str:
    """Return a simple flowchart SVG as a raw string."""
    title = topic or "Process"
    node_count = min(4, max(2, len(title) % 5 + 2))
    svg_lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 80 + {node_count * 60}" width="400" height="{80 + node_count * 60}">',
        "  <style>",
        "    .node { fill: #e3f2fd; stroke: #1565c0; stroke-width: 2; rx: 8; ry: 8; }",
        "    .label { font-family: sans-serif; font-size: 14px; fill: #0d47a1; text-anchor: middle; }",
        "    .arrow { stroke: #555; stroke-width: 2; marker-end: url(#arrowhead); }",
        "  </style>",
        "  <defs>",
        '    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">',
        "      <polygon points='0 0, 8 3, 0 6' fill='#555' />",
        "    </marker>",
        "  </defs>",
        f'  <text x="200" y="25" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle" fill="#0d47a1">{title}</text>',
    ]
    y = 50
    for i in range(node_count):
        label = f"Step {i + 1}"
        svg_lines.append(f'  <rect class="node" x="50" y="{y}" width="300" height="40" />')
        svg_lines.append(f'  <text class="label" x="200" y="{y + 25}">{label}</text>')
        if i < node_count - 1:
            svg_lines.append(
                f'  <line class="arrow" x1="200" y1="{y + 40}" x2="200" y2="{y + 60}" />'
            )
        y += 60
    svg_lines.append("</svg>")
    return "\n".join(svg_lines)


def _build_tree_svg(topic: str) -> str:
    """Return a simple tree/hierarchy SVG as a raw string."""
    title = topic or "Hierarchy"
    levels = min(3, max(2, len(title) % 3 + 2))
    svg_lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100 + {levels * 60}" width="400" height="{100 + levels * 60}">',
        "  <style>",
        "    .node { fill: #fff3e0; stroke: #e65100; stroke-width: 2; }",
        "    .label { font-family: sans-serif; font-size: 12px; fill: #bf360c; text-anchor: middle; }",
        "    .line { stroke: #ff9800; stroke-width: 1.5; fill: none; }",
        "  </style>",
        f'  <text x="200" y="20" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle" fill="#bf360c">{title}</text>',
    ]
    cx = 200
    y = 40
    svg_lines.append(f'  <circle class="node" cx="{cx}" cy="{y}" r="20" />')
    svg_lines.append(f'  <text class="label" x="{cx}" y="{y + 4}">Root</text>')
    y += 40

    node_id = 1
    for level in range(1, levels):
        spread = 2**level
        spacing = 300 / (spread + 1) if spread > 0 else 100
        for branch in range(1, spread + 1):
            child_x = 50 + branch * spacing
            svg_lines.append(
                f'  <line class="line" x1="{cx}" y1="{y - 20}" x2="{child_x}" y2="{y}" />'
            )
            svg_lines.append(f'  <circle class="node" cx="{child_x}" cy="{y}" r="14" />')
            svg_lines.append(f'  <text class="label" x="{child_x}" y="{y + 3}">N{node_id}</text>')
            node_id += 1
        y += 60

    svg_lines.append("</svg>")
    return "\n".join(svg_lines)


def _build_mindmap_svg(topic: str) -> str:
    """Return a simple mind-map SVG as a raw string."""
    title = topic or "Concept Map"
    branches = min(5, max(3, len(title) % 4 + 3))
    colors = ["#e91e63", "#9c27b0", "#3f51b5", "#009688", "#ff9800"]
    svg_lines: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 250" width="400" height="250">',
        "  <style>",
        "    .center { fill: #2196f3; stroke: #0d47a1; stroke-width: 2; }",
        "    .branch { fill: #f5f5f5; stroke: #616161; stroke-width: 1.5; }",
        "    .label { font-family: sans-serif; font-size: 11px; fill: #212121; text-anchor: middle; }",
        "    .title { font-family: sans-serif; font-size: 14px; font-weight: bold; fill: #0d47a1; text-anchor: middle; }",
        "  </style>",
        f'  <text class="title" x="200" y="20">{title}</text>',
        '  <circle class="center" cx="200" cy="60" r="28" />',
        '  <text class="label" x="200" y="64">Core</text>',
    ]
    for i in range(branches):
        bx = 200 + 90 * 1.2 * (1 if i % 2 == 0 else -1) * (0.5 + (i % 3) * 0.25)
        by = 60 + 60 + i * 30
        bx = max(30, min(370, bx))
        svg_lines.append(
            f'  <line x1="200" y1="60" x2="{bx}" y2="{by}" stroke="{colors[i % len(colors)]}" stroke-width="2" />'
        )
        svg_lines.append(
            f'  <rect class="branch" x="{bx - 35}" y="{by - 12}" width="70" height="24" rx="6" />'
        )
        svg_lines.append(f'  <text class="label" x="{bx}" y="{by + 4}">{title[:8]} {i + 1}</text>')

    svg_lines.append("</svg>")
    return "\n".join(svg_lines)


def generate_diagram(topic: str, style: str = "svg") -> str:
    """Generate an SVG diagram for the given topic.

    Parameters
    ----------
    topic:
        The concept or subject to diagram. Embedded keywords (``flow``,
        ``tree``, ``hierarchy``, ``mind``, ``map``) influence the layout
        algorithm automatically.
    style:
        Graphical style hint. Only ``"svg"`` is implemented; other values
        are treated as ``"svg"``.

    Returns
    -------
    str
        A complete SVG document as a unicode string.
    """
    if not topic:
        topic = "Default Diagram"

    diagram_type = _detect_diagram_type(topic)

    builders: dict[str, Any] = {
        "flowchart": _build_flowchart_svg,
        "tree": _build_tree_svg,
        "mindmap": _build_mindmap_svg,
    }

    svg_string: str
    try:
        import svgwrite

        _svgwrite_available = True
    except ImportError:
        _svgwrite_available = False

    if _svgwrite_available:
        import svgwrite

        dwg = svgwrite.Drawing(
            filename="diagram.svg",
            size=("400px", "200px"),
            profile="tiny",
        )
        dwg.add(dwg.text(topic or "Diagram", insert=("200", "20"), fill="#0d47a1", font_size="16"))
        dwg.add(
            dwg.rect(
                insert=("50", "40"),
                size=("300", "40"),
                fill="#e3f2fd",
                stroke="#1565c0",
                rx=8,
                ry=8,
            )
        )
        dwg.add(
            dwg.text(
                "Node", insert=("200", "65"), fill="#0d47a1", font_size="14", text_anchor="middle"
            )
        )
        try:
            svg_string = dwg.tostring()
        except AttributeError:
            svg_string = dwg.tostring()
    else:
        svg_string = builders.get(diagram_type, _build_flowchart_svg)(topic)

    if not svg_string or not svg_string.strip():
        svg_string = _build_flowchart_svg(topic or "Fallback")

    return svg_string


# ---------------------------------------------------------------------------
# 2. Code example generation
# ---------------------------------------------------------------------------

_CODE_EXAMPLE_REGISTRY: dict[str, dict[str, Any]] = {
    "loop": {
        "code": "for i in range(5):\n    print(f'Iteration {i}')\n\n# while-loop variant\ncount = 0\nwhile count < 5:\n    print(f'Count: {count}')\n    count += 1",
        "explanation": "Demonstrates both for and while loops in Python. The for-loop iterates over a range of numbers; the while-loop continues until a condition becomes false.",
        "difficulty": "beginner",
        "tags": ["loop", "iteration", "control-flow"],
    },
    "function": {
        "code": "def greet(name: str, greeting: str = 'Hello') -> str:\n    '''Return a personalized greeting.'''\n    return f'{greeting}, {name}!'\n\n\nprint(greet('Alice'))\nprint(greet('Bob', greeting='Hi'))",
        "explanation": "Shows a function with positional and default parameters, type hints, and a docstring. Functions encapsulate reusable logic.",
        "difficulty": "beginner",
        "tags": ["function", "parameter", "return", "type-hint"],
    },
    "class": {
        "code": "class Rectangle:\n    '''A simple rectangle model.'''\n\n    def __init__(self, width: float, height: float) -> None:\n        self.width = width\n        self.height = height\n\n    @property\n    def area(self) -> float:\n        return self.width * self.height\n\n    def __str__(self) -> str:\n        return f'Rectangle({self.width} x {self.height})'\n\n\nr = Rectangle(3.0, 4.0)\nprint(r)\nprint(f'Area: {r.area}')",
        "explanation": "Defines a class with an initializer, a computed property, and a string representation. Demonstrates basic OOP principles in Python.",
        "difficulty": "intermediate",
        "tags": ["class", "oop", "property", "dunder"],
    },
    "recursion": {
        "code": "def factorial(n: int) -> int:\n    '''Return n! computed recursively.'''\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)\n\n\ndef fibonacci(n: int) -> int:\n    '''Return the n-th Fibonacci number.'''\n    if n < 2:\n        return n\n    return fibonacci(n - 1) + fibonacci(n - 2)\n\n\nprint(factorial(5))\nprint(fibonacci(10))",
        "explanation": "Two classic recursion examples: factorial (linear recursion) and Fibonacci (tree recursion). Each calls itself with a smaller input until a base case is reached.",
        "difficulty": "intermediate",
        "tags": ["recursion", "base-case", "factorial", "fibonacci"],
    },
    "sort": {
        "code": "# Built-in sort\nnums = [3, 1, 4, 1, 5, 9]\nnums.sort()\nprint(f'sorted in-place: {nums}')\n\n# sorted() returns a new list\nwords = ['banana', 'apple', 'cherry']\nprint(f'sorted copy: {sorted(words)}')\n\n# Custom key\nprint(f'by length: {sorted(words, key=len)}')",
        "explanation": "Python's list.sort() sorts in-place; sorted() returns a new list. Both accept a key function for custom ordering (e.g., by string length).",
        "difficulty": "beginner",
        "tags": ["sort", "list", "key-function"],
    },
    "search": {
        "code": "def linear_search(items: list[int], target: int) -> int | None:\n    '''Return the index of target or None.'''\n    for idx, val in enumerate(items):\n        if val == target:\n            return idx\n    return None\n\n\ndef binary_search(items: list[int], target: int) -> int | None:\n    '''Return the index of target in a sorted list.'''\n    lo, hi = 0, len(items) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if items[mid] == target:\n            return mid\n        elif items[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return None\n\n\ndata = [2, 4, 6, 8, 10]\nprint(linear_search(data, 6))\nprint(binary_search(data, 6))",
        "explanation": "Linear search scans every element (O(n)); binary search halves the search space each step (O(log n)) but requires a sorted list.",
        "difficulty": "intermediate",
        "tags": ["search", "linear", "binary", "algorithm"],
    },
    "file_io": {
        "code": "# Writing to a file\nwith open('example.txt', 'w', encoding='utf-8') as f:\n    f.write('Hello, world!\\n')\n\n# Reading the whole file\nwith open('example.txt', 'r', encoding='utf-8') as f:\n    content = f.read()\n    print(content)\n\n# Reading line by line\nwith open('example.txt', 'r', encoding='utf-8') as f:\n    for line in f:\n        print(f'Line: {line.strip()}')",
        "explanation": "Uses context managers (``with``) to safely open files. Demonstrates write, read, and line-by-line iteration modes.",
        "difficulty": "beginner",
        "tags": ["file-io", "context-manager", "with"],
    },
    "api": {
        "code": "import urllib.request\nimport json\n\n\ndef fetch_json(url: str) -> dict:\n    '''Fetch JSON from a URL and return the parsed dict.'''\n    with urllib.request.urlopen(url) as resp:\n        data = resp.read()\n    return json.loads(data)\n\n\n# Example usage (commented out to avoid network dependency):\n# result = fetch_json('https://api.github.com/repos/python/cpython')\n# print(result['full_name'])",
        "explanation": "Demonstrates an HTTP GET request using only the standard library. Parses the response body as JSON. For production use, the ``requests`` library is recommended.",
        "difficulty": "intermediate",
        "tags": ["api", "http", "json", "urllib"],
    },
    "database": {
        "code": "import sqlite3\n\n\ndef demo_database() -> None:\n    '''Create an in-memory SQLite DB, insert rows, and query them.'''\n    conn = sqlite3.connect(':memory:')\n    cursor = conn.cursor()\n    cursor.execute(\"CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)\")\n    cursor.executemany(\n        'INSERT INTO users (name) VALUES (?)',\n        [('Alice',), ('Bob',), ('Charlie',)],\n    )\n    conn.commit()\n    cursor.execute('SELECT * FROM users WHERE name LIKE ?', ('A%',))\n    for row in cursor.fetchall():\n        print(row)\n    conn.close()\n\n\ndemo_database()",
        "explanation": "Shows SQLite in-memory database usage: create a table, insert multiple rows with ``executemany``, query with a parameterised statement, and close the connection.",
        "difficulty": "intermediate",
        "tags": ["database", "sqlite", "sql", "cursor"],
    },
}


def generate_code_example(concept: str, language: str = "python") -> dict[str, Any]:
    """Generate a working code example for the given concept and language.

    Parameters
    ----------
    concept:
        The programming concept to illustrate (e.g. ``"loop"``, ``"class"``,
        ``"recursion"``, ``"api"``). Unknown concepts fall back to a generic
        Python example.
    language:
        Target language. Only ``"python"`` returns full content today;
        ``"javascript"``, ``"java"``, and ``"cpp"`` return structured stubs
        so callers can extend them later.

    Returns
    -------
    dict
        ``{"code": str, "explanation": str, "difficulty": str, "tags": list[str]}``
    """
    normalized = concept.strip().lower() if concept else ""

    if not normalized or normalized not in _CODE_EXAMPLE_REGISTRY:
        code = "# Generic example: replace with a concept-specific snippet\nprint('Hello from a generic code example')\n"
        explanation = f"No specific example registered for '{concept}'. This placeholder demonstrates the expected output shape."
        difficulty = "beginner"
        tags: list[str] = ["generic", "placeholder"]
    else:
        entry = _CODE_EXAMPLE_REGISTRY[normalized]
        code = entry["code"]
        explanation = entry["explanation"]
        difficulty = entry["difficulty"]
        tags = entry["tags"]

    if language != "python":
        lang_note = {
            "javascript": "// JavaScript stub – implement when needed\nconsole.log('Hello');\n",
            "java": '// Java stub – implement when needed\npublic class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello");\n    }\n}\n',
            "cpp": '// C++ stub – implement when needed\n#include <iostream>\nint main() {\n    std::cout << "Hello" << std::endl;\n    return 0;\n}\n',
        }.get(language, f"// {language} stub – not yet implemented\n")
        code = lang_note

    return {
        "code": code,
        "explanation": explanation,
        "difficulty": difficulty,
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# 3. Voice generation (TTS)
# ---------------------------------------------------------------------------


def generate_voice(text: str, voice: str = "default") -> str:
    """Synthesize speech for *text* and return the path to the audio file.

    When the environment variable ``HERMES_TTS_AVAILABLE`` is set to ``"1"``
    the function delegates to the Hermes ``text_to_speech`` tool.  Otherwise a
    warning is printed and the text is persisted as a ``.txt`` file so the
    function still returns a valid path.

    Parameters
    ----------
    text:
        The text to speak.
    voice:
        Voice identifier (reserved for future use).

    Returns
    -------
    str
        Absolute path to the generated audio / stub file.
    """
    if not text:
        text = "(empty voice request)"

    tts_available = os.environ.get("HERMES_TTS_AVAILABLE", "0") == "1"

    if tts_available:
        try:
            import hermes_tools

            result = hermes_tools.text_to_speech(text=text, voice=voice)
            return str(result)
        except Exception as exc:  # noqa: BLE001  # noqa: BLE001 – fall back to stub on any failure
            import warnings

            warnings.warn(
                f"Her pay TTS raised {exc!r}; falling back to text stub.",
                stacklevel=2,
            )
            tts_available = False

    import warnings

    warnings.warn(
        "HERMES_TTS_AVAILABLE is not set to 1 — writing text to a .txt stub instead of audio.",
        stacklevel=2,
    )
    out_dir = DEFAULT_TEMPLATE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = text[:32].replace(" ", "_").replace("/", "_") or "silence"
    stub_path = out_dir / f"{safe_name}.txt"
    stub_path.write_text(text, encoding="utf-8")
    return str(stub_path)


# ---------------------------------------------------------------------------
# 4. PDF generation
# ---------------------------------------------------------------------------

_TEMPLATE_CSS: dict[str, str] = {
    "handout": """
        body { font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.5;
               padding: 2cm; color: #222; }
        h1 { color: #0d47a1; border-bottom: 2px solid #0d47a1; padding-bottom: 4px; }
        h2 { color: #1565c0; margin-top: 1.2em; }
        pre { background: #f5f5f5; border: 1px solid #ddd; padding: 8px;
              font-family: 'Courier New', monospace; font-size: 9pt; overflow-x: auto; }
        code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px;
               font-family: 'Courier New', monospace; font-size: 10pt; }
        blockquote { border-left: 4px solid #2196f3; margin: 0; padding-left: 12px;
                     color: #555; }
    """,
    "cheat_sheet": """
        body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 8pt; line-height: 1.3;
               columns: 2; column-gap: 1.5cm; padding: 1cm; color: #212121; }
        h1 { font-size: 14pt; color: #0d47a1; border-bottom: 3px solid #0d47a1;
             padding-bottom: 2px; column-span: all; }
        h2 { font-size: 10pt; color: #1565c0; margin-top: 0.6em;
             border-bottom: 1px solid #bbb; padding-bottom: 1px; }
        pre { background: #eceff1; border: 1px solid #90a4ae; padding: 4px;
              font-family: 'Consolas', 'Courier New', monospace; font-size: 7pt;
              white-space: pre-wrap; word-wrap: break-word; }
        code { background: #eceff1; padding: 0 3px; font-family: 'Consolas', monospace;
               font-size: 7.5pt; }
        table { border-collapse: collapse; width: 100%; font-size: 7.5pt; }
        th, td { border: 1px solid #b0bec5; padding: 2px 4px; text-align: left; }
        th { background: #e3f2fd; }
    """,
    "lesson_plan": """
        body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt;
               line-height: 1.6; padding: 2cm; color: #212121; }
        h1 { color: #0d47a1; font-size: 18pt; border-bottom: 3px solid #0d47a1;
             padding-bottom: 6px; margin-bottom: 0.4cm; }
        h2 { color: #1565c0; font-size: 13pt; margin-top: 0.8cm; }
        .meta { background: #e3f2fd; border: 1px solid #90caf9; padding: 8px;
                margin-bottom: 1em; font-size: 9pt; }
        .meta strong { color: #0d47a1; }
        ul, ol { margin-left: 1em; }
        .objective { background: #fff8e1; border-left: 4px solid #ffc107; padding: 6px 10px; margin: 0.4cm 0; }
        pre { background: #f5f5f5; border: 1px solid #ddd; padding: 8px;
              font-family: 'Courier New', monospace; font-size: 9pt; }
        footer { margin-top: 1cm; padding-top: 4px; border-top: 1px solid #ccc;
                 font-size: 8pt; color: #888; text-align: center; }
    """,
}


def generate_pdf(content: str, template: str = "handout") -> str:
    """Render *content* (markdown) into a styled PDF handout.

    Parameters
    ----------
    content:
        Markdown source text.
    template:
        One of ``"handout"``, ``"cheat_sheet"``, ``"lesson_plan"``.  Falls
        back to ``"handout"`` for any other value.

    Returns
    -------
    str
        Absolute path to the generated PDF file.
    """
    if not content:
        content = "_No content provided._"

    css = _TEMPLATE_CSS.get(template, _TEMPLATE_CSS["handout"])

    try:
        import markdown

        html_body = markdown.markdown(content, extensions=["tables", "fenced_code"])
    except ImportError:
        html_body = content.replace("\\n", "<br/>")

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<style>{css}</style>
</head>
<body>
{html_body}
</body>
</html>"""

    out_dir = DEFAULT_TEMPLATE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"handout_{abs(hash(content)) % 1_000_000}.pdf"

    try:
        from fpdf import FPDF

        pdf = FPDF(orientation="P", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_margins(15, 15, 15)
        pdf.add_page()
        pdf.set_font("Courier", size=8)
        pdf.write_html(html_body)
        pdf.output(str(pdf_path))
        return str(pdf_path)
    except Exception as exc:  # noqa: BLE001
        import warnings as _warnings
        _warnings.warn(f'PDF generation failed: {exc}')
        pdf_path.write_text(html_doc, encoding='utf-8')
        return str(pdf_path)

    try:
        from reportlab.lib.pagesizes import A4  # noqa: I001
        from reportlab.platypus import SimpleDocTemplate, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet

        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
        styles = getSampleStyleSheet()
        flowables: list[Any] = []
        for line in html_body.split("<br/>"):
            flowables.append(Paragraph(line.strip(), styles["Normal"]))
        doc.build(flowables)
        return str(pdf_path)
    except ImportError:
        pdf_path.write_text(html_doc, encoding="utf-8")
        return str(pdf_path)


def markdown_to_exercise(md: str) -> list[dict[str, str]]:
    """Parse markdown lesson content into structured exercises.

    Recognised patterns
    -------------------
    * ``??? question`` → fill-in-the-blank
    * ``>>> code``     → coding exercise
    * ``Q: … A: …``   → multiple-choice / short-answer question
    * ``---``          → exercise boundary (ignored in output, only separates blocks)

    Parameters
    ----------
    md:
        Raw markdown text.

    Returns
    -------
    list[dict[str, str]]
        Each dict has keys ``type``, ``question``, ``answer``, ``explanation``.
    """
    if not md:
        return []

    exercises: list[dict[str, str]] = []
    lines = md.splitlines()

    def _flush_mcq(question_text: str, answer_text: str) -> None:
        q = question_text.strip()
        a = answer_text.strip()
        if q and a:
            exercises.append(
                {
                    "type": "mcq",
                    "question": q,
                    "answer": a,
                    "explanation": "",
                }
            )

    pending_question: str = ""
    pending_answer: str = ""
    in_mcq: bool = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line == "---":
            pending_question = ""
            pending_answer = ""
            in_mcq = False
            continue

        if line.startswith("Q:"):
            # Check if A: is on the same line
            q_part = line[2:].strip()
            a_idx = q_part.find(" A: ")
            if a_idx >= 0:
                question = q_part[:a_idx].strip()
                answer = q_part[a_idx + 4 :].strip()
                if question and answer:
                    exercises.append(
                        {
                            "type": "mcq",
                            "question": question,
                            "answer": answer,
                            "explanation": "",
                        }
                    )
                in_mcq = False
                continue
            pending_question = q_part
            pending_answer = ""
            in_mcq = True
            continue

        if in_mcq and line.startswith("A:"):
            pending_answer = line[2:].strip()
            in_mcq = False
            _flush_mcq(pending_question, pending_answer)
            continue

        if in_mcq:
            pending_question += " " + line
            continue

        if line.startswith("???"):
            question = line[3:].strip()
            if question:
                exercises.append(
                    {
                        "type": "fill_blank",
                        "question": question,
                        "answer": "",
                        "explanation": "",
                    }
                )
            continue

        if line.startswith(">>>"):
            code = line[3:].strip()
            if code:
                exercises.append(
                    {
                        "type": "coding",
                        "question": f"Write code to: {code}",
                        "answer": "",
                        "explanation": "",
                    }
                )
            continue

    if in_mcq:
        _flush_mcq(pending_question, pending_answer)

    return exercises
