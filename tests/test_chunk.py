"""Stage 3 tests."""

from robodocs.chunk.chunker import blocks, chunk_document, pack, sections, split_oversized, thread_parts
from robodocs.config import get_settings
from robodocs.process.schema import Document

CFG = get_settings().chunking


def _doc(text, source_type="doc", **kw):
    base = dict(doc_id="doc:x:1:a.md", source_type=source_type, framework="isaac_sim", version="5.1",
                title="Install", text=text, url="https://x")
    base.update(kw)
    return Document(**base)


def test_code_block_is_one_block():
    bl = blocks("intro\n\n```bash\nline1\n\nline2\n```\n\nafter")
    assert bl == ["intro", "```bash\nline1\n\nline2\n```", "after"]


def test_sections_track_heading_path_and_ignore_hashes_in_code():
    secs = sections("# A\nx\n## B\n```\n# not heading\n```\n### C\ny")
    assert [p for p, _ in secs] == [["A"], ["A", "B"], ["A", "B", "C"]]


def test_pack_respects_max():
    out = pack(["a" * 1000, "b" * 1000, "c" * 300], CFG)
    assert all(len(c) <= CFG.max_chars for c in out) and len(out) == 2


def test_oversized_code_split_and_refenced():
    code = "```python\n" + "\n".join(f"x{i} = {i}" for i in range(600)) + "\n```"
    parts = split_oversized(code, CFG.max_chars)
    assert len(parts) > 1
    assert all(p.startswith("```python") and p.endswith("```") and len(p) <= CFG.max_chars for p in parts)


def test_doc_chunks_carry_context_and_merge_small_sections():
    text = "# Install\n\n## Prerequisites\n\nShort.\n\n## Steps\n\n" + ("Do the thing. " * 60)
    chunks = chunk_document(_doc(text), CFG)
    assert chunks[0].context.startswith("Isaac Sim 5.1 docs | Install")
    assert "Prerequisites" in chunks[0].text and "Steps" in chunks[0].text    # tiny section merged forward


def test_thread_answers_get_question_context():
    text = ("# Crash on start\n\n## Question (@a, 2025-01-01)\n\nIt crashes with error X.\n\n"
            "## Reply (maintainer @dev, 2025-01-02)\n\nSet headless=True.\n\n"
            "## Reply (@u, 2025-01-03)\n\nWorked for me too, thanks a lot for the hint here.")
    doc = _doc(text, source_type="issue", doc_id="gh:o/r#1", title="Crash on start")
    chunks = chunk_document(doc, CFG)
    assert chunks[0].role == "question"
    answer = next(c for c in chunks if c.by_maintainer)
    assert answer.role == "answer" and "Q: Crash on start" in answer.context and "error X" in answer.context
    assert "Set headless=True." in answer.text


def test_context_plus_text_stays_under_limit():
    text = "# T\n\n## Question (@a, 2025-01-01)\n\n" + "word " * 2000 + "\n\n## Reply (@b, 2025-01-02)\n\n" + "fix " * 2000
    chunks = chunk_document(_doc(text, source_type="issue", doc_id="gh:o/r#2", title="T"), CFG)
    assert all(len(c.embed_text) <= CFG.max_chars for c in chunks)
    assert sum(c.role == "question" for c in chunks) <= 3


def test_unclosed_user_fence_is_closed():
    text = "# T\n\n## Question (@a, 2025-01-01)\n\nError:\n```\nTraceback ...\n\n## Reply (@b, 2025-01-02)\n\nok then fine"
    chunks = chunk_document(_doc(text, source_type="issue", doc_id="gh:o/r#3", title="T"), CFG)
    assert all(c.text.count("```") % 2 == 0 for c in chunks)


def test_thread_parts():
    q, answers = thread_parts("# T\n\n## Question (x)\n\nQ body\n\n## Accepted answer (score 3)\n\nA body")
    assert q == "Q body" and answers == [("Accepted answer (score 3)", "A body")]
