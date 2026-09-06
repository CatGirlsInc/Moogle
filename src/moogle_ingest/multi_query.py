"""Low-overhead multi-query retrieval for broad/enumeration-style questions.

Rationale: AnythingLLM's chat API always couples vector retrieval with LLM
generation (there is no standalone "similarity search" endpoint), and a single
embedded query for a broad question tends to collapse onto one dominant
document. This module works around both constraints without adding a new
database, reranker, or agent framework:

1. Ask a (fast) chat model to decompose the broad question into several
   focused sub-queries covering distinct angles.
2. Run each sub-query (plus the original question) through AnythingLLM's
   existing `mode="query"` chat endpoint purely to harvest the `sources`
   chunks it retrieved from the existing LanceDB index; the throwaway answer
   text from these calls is discarded.
3. Deduplicate/rank the combined chunks by similarity score.
4. Make one direct call to Ollama (bypassing AnythingLLM's own retrieval) to
   synthesize a final answer grounded only in the deduplicated context.

This keeps the existing AnythingLLM + LanceDB index untouched and reuses the
existing Ollama service; the only new moving part is this orchestration.
"""

from __future__ import annotations

import json
import re
import time

import requests

from moogle_ingest.anythingllm import query_workspace

DEFAULT_MAX_SUBQUERIES = 6
DEFAULT_TOP_K_PER_QUERY = 4
DEFAULT_MAX_CONTEXT_CHUNKS = 12
DEFAULT_MAX_CHARS_PER_CHUNK = 1500

_DECOMPOSITION_SYSTEM_PROMPT = (
    "You turn one broad enumeration-style question into a short list of "
    "focused search queries that, together, cover the distinct categories of "
    "evidence needed to answer it fully. Always produce exactly one query "
    "for EACH of these 6 category types, in this order, unless a category is "
    "clearly nonsensical for the question (then omit only that one): "
    "(1) core stats/mechanics, (2) equipment/gear, (3) food/consumables, "
    "(4) job abilities/traits, (5) spells/songs/buffs, (6) other bonuses or "
    "game systems. "
    "Reply with ONLY a JSON array of strings, no prose, no markdown fences. "
    "Each string should be a concise, specific search query (3-6 words) "
    "naming a concrete category, not a meta-query about guides, forums, "
    "patch notes, or discussion sites. Do not repeat the original question "
    "verbatim. Produce at most {max_subqueries} queries.\n\n"
    "Example:\n"
    'Question: "What are all ways to reduce a fever in humans?"\n'
    'Answer: ["fever reducing medication", "home remedies for fever", '
    '"when to see a doctor for fever", "fever treatment in children"]'
)

_SYNTHESIS_SYSTEM_PROMPT = (
    "You answer questions using ONLY the provided context excerpts from a "
    "wiki. Each excerpt is labeled with its source document title. "
    "Combine information across excerpts to give a complete answer, and "
    "mention which source document(s) support each claim. "
    "If the context does not contain enough information, say so explicitly. "
    "Do not invent facts, numbers, or effects that are not present in the "
    "context."
)

_BULLET_PREFIX_PATTERN = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s*")


def parse_subqueries(raw_text: str, *, max_subqueries: int = DEFAULT_MAX_SUBQUERIES) -> list[str]:
    """Parse an LLM's decomposition reply into a clean list of sub-queries."""
    text = raw_text.strip()

    # Strip markdown code fences if the model added them despite instructions.
    if text.startswith("```"):
        text = text.strip("`")
        newline = text.find("\n")
        if newline != -1 and not text[:newline].strip().startswith("["):
            text = text[newline + 1 :]

    candidates: list[str] = []
    try:
        decoded = json.loads(text)
        if isinstance(decoded, list):
            candidates = [str(item).strip() for item in decoded if str(item).strip()]
    except json.JSONDecodeError:
        pass

    if not candidates:
        for line in text.splitlines():
            cleaned = _BULLET_PREFIX_PATTERN.sub("", line).strip().strip('"')
            if cleaned:
                candidates.append(cleaned)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    return deduped[:max_subqueries]


def decompose_query(
    ollama_base_url: str,
    *,
    model: str,
    question: str,
    max_subqueries: int = DEFAULT_MAX_SUBQUERIES,
    timeout: int = 60,
) -> list[str]:
    base = ollama_base_url.rstrip("/")
    response = requests.post(
        f"{base}/api/chat",
        json={
            "model": model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": _DECOMPOSITION_SYSTEM_PROMPT.format(max_subqueries=max_subqueries),
                },
                {"role": "user", "content": question},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json().get("message", {}).get("content", "")
    return parse_subqueries(content, max_subqueries=max_subqueries)


def _source_key(source: dict) -> str:
    identifier = source.get("id")
    if identifier:
        return str(identifier)
    return f"{source.get('title', '')}:{hash(source.get('text', ''))}"


def dedupe_sources(source_lists: list[list[dict]], *, max_total: int = DEFAULT_MAX_CONTEXT_CHUNKS) -> list[dict]:
    """Flatten, deduplicate by chunk id, and rank by similarity score."""
    best_by_key: dict[str, dict] = {}
    for sources in source_lists:
        for source in sources:
            if not isinstance(source, dict):
                continue
            key = _source_key(source)
            score = source.get("score") or 0
            existing = best_by_key.get(key)
            if existing is None or score > (existing.get("score") or 0):
                best_by_key[key] = source

    ranked = sorted(best_by_key.values(), key=lambda s: s.get("score") or 0, reverse=True)
    return ranked[:max_total]


def build_context_block(sources: list[dict], *, max_chars_per_chunk: int = DEFAULT_MAX_CHARS_PER_CHUNK) -> str:
    blocks = []
    for source in sources:
        title = source.get("title", "unknown source")
        text = (source.get("text") or "").strip()[:max_chars_per_chunk]
        blocks.append(f"### Source: {title}\n{text}")
    return "\n\n".join(blocks)


def synthesize_answer(
    ollama_base_url: str,
    *,
    model: str,
    question: str,
    sources: list[dict],
    timeout: int = 180,
) -> dict:
    base = ollama_base_url.rstrip("/")
    context = build_context_block(sources)
    start = time.monotonic()
    response = requests.post(
        f"{base}/api/chat",
        json={
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    elapsed = time.monotonic() - start
    answer = response.json().get("message", {}).get("content", "").strip()
    return {"answer": answer, "latency_s": round(elapsed, 2)}


def answer_broad_query(
    *,
    anythingllm_base_url: str,
    workspace_slug: str,
    ollama_base_url: str,
    question: str,
    decompose_model: str,
    synthesis_model: str,
    max_subqueries: int = DEFAULT_MAX_SUBQUERIES,
    top_k_per_query: int = DEFAULT_TOP_K_PER_QUERY,
    max_context_chunks: int = DEFAULT_MAX_CONTEXT_CHUNKS,
) -> dict:
    """Decompose, fan out retrieval, dedupe, and synthesize a grounded answer."""
    subqueries = decompose_query(
        ollama_base_url,
        model=decompose_model,
        question=question,
        max_subqueries=max_subqueries,
    )
    all_queries = [question] + [q for q in subqueries if q.lower() != question.lower()]

    per_query_sources: list[list[dict]] = []
    retrieval_calls: list[dict] = []
    for query in all_queries:
        result = query_workspace(anythingllm_base_url, workspace_slug=workspace_slug, prompt=query, mode="query")
        sources = result["sources"][:top_k_per_query]
        per_query_sources.append(sources)
        retrieval_calls.append({"query": query, "source_count": len(sources), "titles": [s.get("title") for s in sources]})

    deduped_sources = dedupe_sources(per_query_sources, max_total=max_context_chunks)
    synthesis = synthesize_answer(
        ollama_base_url,
        model=synthesis_model,
        question=question,
        sources=deduped_sources,
    )

    return {
        "question": question,
        "subqueries": subqueries,
        "retrieval_calls": retrieval_calls,
        "deduped_source_titles": [s.get("title") for s in deduped_sources],
        "deduped_source_count": len(deduped_sources),
        "answer": synthesis["answer"],
        "latency_s": synthesis["latency_s"],
        "synthesis_model": synthesis_model,
        "decompose_model": decompose_model,
    }
