"""Stage 3 runner: documents.jsonl -> chunks.jsonl (+ chunk_report.json, chunk_sample.md).

    conda run -n robodocs python -m robodocs.chunk.run

Also measures the naive fixed-size baseline on the same documents, so the choice of strategy is
backed by numbers: how often code blocks get cut, how often an answer ends up without its question.
"""

import json
import random
import re
from collections import Counter

from tqdm import tqdm

from robodocs.chunk.chunker import FENCE, THREAD_TYPES, chunk_document, naive_chunks
from robodocs.config import get_settings
from robodocs.process.schema import Document

CHARS_PER_TOKEN = 3.5     # measured roughly for code-heavy technical text; refined in Stage 4
TOKEN_LIMIT = 512


def broken_fence(text: str) -> bool:
    return sum(1 for l in text.splitlines() if FENCE.match(l)) % 2 == 1


def pct(values: list[int], p: float) -> int:
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p))] if s else 0


def main() -> None:
    s = get_settings()
    proc = s.abs_path(s.paths.processed_data)
    cfg = s.chunking

    sizes, roles, kinds, too_long, broken = [], Counter(), Counter(), 0, 0
    per_doc = []
    naive = {"chunks": 0, "broken_code": 0, "answer_without_question": 0, "thread_answer_windows": 0}
    sample_pool = []
    rng = random.Random(11)

    with open(proc / "documents.jsonl", encoding="utf-8") as fin, \
         open(proc / "chunks.jsonl", "w", encoding="utf-8") as fout:
        for line in tqdm(fin, desc="chunking", unit="doc"):
            doc = Document.model_validate_json(line)
            chunks = chunk_document(doc, cfg)
            per_doc.append(len(chunks))
            for c in chunks:
                fout.write(c.model_dump_json() + "\n")
                n = len(c.embed_text)
                sizes.append(n)
                roles[c.role] += 1
                kinds[c.source_type] += 1
                too_long += n / CHARS_PER_TOKEN > TOKEN_LIMIT
                broken += broken_fence(c.text)
            if rng.random() < 0.0004:
                sample_pool.append((doc, chunks))

            # --- naive baseline on the same document
            for w in naive_chunks(doc.text):
                naive["chunks"] += 1
                naive["broken_code"] += broken_fence(w)
                if doc.source_type in THREAD_TYPES and re.search(r"(?m)^## (Reply|Answer|Accepted answer)", w):
                    naive["thread_answer_windows"] += 1
                    naive["answer_without_question"] += doc.title not in w

    total = len(sizes)
    report = {
        "documents": len(per_doc), "chunks": total,
        "chunks_per_doc": {"median": pct(per_doc, .5), "p95": pct(per_doc, .95), "max": max(per_doc)},
        "chars_per_chunk_incl_context": {"p5": pct(sizes, .05), "median": pct(sizes, .5),
                                         "p95": pct(sizes, .95), "max": max(sizes)},
        "est_over_512_tokens": f"{too_long} ({too_long / total:.2%})",
        "by_role": dict(roles), "by_source_type": dict(kinds),
        "comparison": {
            "content_aware": {"chunks": total, "code_blocks_cut": f"{broken} ({broken / total:.2%})",
                              "answers_without_question": "0 (question prepended by design)"},
            "naive_1200_overlap_200": {
                "chunks": naive["chunks"],
                "code_blocks_cut": f"{naive['broken_code']} ({naive['broken_code'] / naive['chunks']:.2%})",
                "answers_without_question": f"{naive['answer_without_question']} of "
                                            f"{naive['thread_answer_windows']} answer windows "
                                            f"({naive['answer_without_question'] / max(1, naive['thread_answer_windows']):.0%})"},
        },
    }
    (proc / "chunk_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    md = ["# Stage 3 chunk sample\n"]
    for doc, chunks in sample_pool[:6]:
        md.append(f"## {doc.doc_id} ({doc.source_type}, {len(doc.text)} chars -> {len(chunks)} chunks)\n")
        for c in chunks[:4]:
            md += [f"**chunk {c.chunk_index} · {c.role} · {len(c.text)} chars**", "```text",
                   c.embed_text[:700], "```", ""]
    (proc / "chunk_sample.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
