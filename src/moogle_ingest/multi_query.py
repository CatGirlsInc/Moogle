"""Low-overhead multi-query retrieval for broad/enumeration-style questions.

Rationale: AnythingLLM's chat API always couples vector retrieval with LLM
generation (there is no standalone "similarity search" endpoint), and a single
embedded query for a broad question tends to collapse onto one dominant
document. This module works around both constraints without adding a new
database, reranker, or agent framework:

1. Ask a chat model to decompose the question into sub-queries that maximize
   coverage of distinct aspects, mechanics, or terminology -- generically,
   not tied to any fixed category list. Narrow single-entity lookups may
   decompose to nothing extra.
2. Run each sub-query (plus the original question) through AnythingLLM's
   existing `mode="query"` chat endpoint purely to harvest the `sources`
   chunks it retrieved from the existing LanceDB index; the throwaway answer
   text from these calls is discarded. These fan-out calls run concurrently
   (bounded) and are pinned to a cheap/fast model, since only their
   `sources` are used.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

import requests

from moogle_ingest.anythingllm import get_workspace_chat_model, query_workspace, set_workspace_chat_model

DEFAULT_MAX_SUBQUERIES = 6
DEFAULT_TOP_K_PER_QUERY = 4
DEFAULT_MAX_CONTEXT_CHUNKS = 12
DEFAULT_MAX_CHARS_PER_CHUNK = 1500
DEFAULT_FANOUT_CONCURRENCY = 3
REDUNDANCY_JACCARD_THRESHOLD = 0.7

_DECOMPOSITION_SYSTEM_PROMPT = (
    "Generate up to {max_subqueries} independent retrieval queries that "
    "together maximize coverage of the user's question.\n\n"
    "Explore distinct mechanics, sources, categories, named effects, "
    "synonyms, and related terminology, but only when relevant to the "
    "question -- do not force categories that do not apply.\n\n"
    "If the question already names ONE single specific entity (a named "
    "item, spell, ability, monster, quest, etc.) and just asks what it is "
    "or does -- NOT a broad list/enumeration across many things -- then no "
    "further queries are needed: return an empty JSON array `[]`.\n\n"
    "Reply with ONLY a JSON array of strings, no prose, no markdown fences. "
    "Each string should be a concise, specific search query (3-6 words), "
    "not a full sentence, question, or meta-query about guides, forums, "
    "patch notes, or discussion sites. Do not repeat the original question "
    "verbatim, and do not return near-duplicate variants of the same query.\n\n"
    "Examples:\n"
    'Question: "What are all ways to reduce a fever in humans?"\n'
    'Answer: ["fever reducing medication", "home remedies for fever", '
    '"when to see a doctor for fever", "fever treatment in children"]\n\n'
    'Question: "What is ibuprofen used for?"\n'
    "Answer: [] (a single named entity, no decomposition needed)"
)

_SYNTHESIS_SYSTEM_PROMPT = (
    "You answer questions using ONLY the provided context excerpts from a "
    "wiki. Each excerpt is labeled with its source document title. "
    "Combine information across excerpts to give a complete answer, and "
    "mention which source document(s) support each claim. "
    "If the context does not contain enough information, say so explicitly. "
    "Do not invent facts, numbers, or effects that are not present in the "
    "context. Do not conflate distinct mechanics (e.g. different variants of "
    "the same broad stat) unless the context itself relates them."
)

_BULLET_PREFIX_PATTERN = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s*")
_WORD_PATTERN = re.compile(r"[a-z0-9]+")


class Stopwatch:
    """Collects (label, elapsed_seconds) timings for a multi-stage pipeline."""

    def __init__(self) -> None:
        self.stages: list[tuple[str, float]] = []

    @contextmanager
    def track(self, label: str):
        start = time.monotonic()
        try:
            yield
        finally:
            self.stages.append((label, time.monotonic() - start))

    def total(self) -> float:
        return sum(elapsed for _, elapsed in self.stages)

    def report(self) -> str:
        width = max((len(label) for label, _ in self.stages), default=0)
        lines = [f"{label.ljust(width)}: {elapsed:.2f}s" for label, elapsed in self.stages]
        lines.append("-" * (width + 10))
        lines.append(f"{'total'.ljust(width)}: {self.total():.2f}s")
        return "\n".join(lines)


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
    parsed_as_json_list = False
    try:
        decoded = json.loads(text)
        if isinstance(decoded, list):
            parsed_as_json_list = True
            candidates = [str(item).strip() for item in decoded if str(item).strip()]
    except json.JSONDecodeError:
        pass

    if not candidates and not parsed_as_json_list:
        # Model sometimes emits several bracket groups instead of one array,
        # e.g. `["a"] ["b"] ["c"]`. Parse each bracket group independently.
        bracket_groups = re.findall(r"\[[^\[\]]*\]", text)
        if len(bracket_groups) > 1:
            for group in bracket_groups:
                try:
                    decoded_group = json.loads(group)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded_group, list):
                    parsed_as_json_list = True
                    candidates.extend(str(item).strip() for item in decoded_group if str(item).strip())
                else:
                    candidates.append(str(decoded_group).strip())

    if not candidates and not parsed_as_json_list and text:
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


def _token_set(text: str) -> set[str]:
    return set(_WORD_PATTERN.findall(text.lower()))


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def filter_redundant_queries(original_question: str, subqueries: list[str]) -> list[str]:
    """Drop sub-queries that are near-duplicates of the original question or of each other."""
    accepted: list[str] = []
    accepted_tokens: list[set[str]] = [_token_set(original_question)]
    for query in subqueries:
        tokens = _token_set(query)
        if any(_jaccard_similarity(tokens, existing) >= REDUNDANCY_JACCARD_THRESHOLD for existing in accepted_tokens):
            continue
        accepted.append(query)
        accepted_tokens.append(tokens)
    return accepted


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
    subqueries = parse_subqueries(content, max_subqueries=max_subqueries)
    return filter_redundant_queries(question, subqueries)


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
) -> str:
    base = ollama_base_url.rstrip("/")
    context = build_context_block(sources)
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
    return response.json().get("message", {}).get("content", "").strip()


def _run_fanout_query(anythingllm_base_url: str, workspace_slug: str, query: str, top_k: int) -> tuple[str, list[dict], float]:
    start = time.monotonic()
    result = query_workspace(anythingllm_base_url, workspace_slug=workspace_slug, prompt=query, mode="query")
    elapsed = time.monotonic() - start
    return query, result["sources"][:top_k], elapsed


def answer_broad_query(
    *,
    anythingllm_base_url: str,
    workspace_slug: str,
    ollama_base_url: str,
    question: str,
    decompose_model: str,
    synthesis_model: str,
    fanout_model: str = "llama3.2:3b",
    max_subqueries: int = DEFAULT_MAX_SUBQUERIES,
    top_k_per_query: int = DEFAULT_TOP_K_PER_QUERY,
    max_context_chunks: int = DEFAULT_MAX_CONTEXT_CHUNKS,
    fanout_concurrency: int = DEFAULT_FANOUT_CONCURRENCY,
) -> dict:
    """Decompose, fan out retrieval, dedupe, and synthesize a grounded answer."""
    stopwatch = Stopwatch()

    with stopwatch.track("decomposition"):
        subqueries = decompose_query(
            ollama_base_url,
            model=decompose_model,
            question=question,
            max_subqueries=max_subqueries,
        )
    all_queries = [question] + subqueries

    # Pin the workspace to a cheap/fast model for the fan-out calls, since
    # their generated answer text is discarded and only `sources` is used.
    # Restore whatever the workspace was previously configured with after.
    original_fanout_model = get_workspace_chat_model(anythingllm_base_url, workspace_slug=workspace_slug)
    if original_fanout_model != fanout_model:
        set_workspace_chat_model(anythingllm_base_url, workspace_slug=workspace_slug, chat_model=fanout_model)

    per_query_sources: list[list[dict]] = []
    retrieval_calls: list[dict] = []
    try:
        with stopwatch.track("retrieval fan-out (total)"):
            with ThreadPoolExecutor(max_workers=max(1, fanout_concurrency)) as executor:
                futures = {
                    executor.submit(_run_fanout_query, anythingllm_base_url, workspace_slug, query, top_k_per_query): query
                    for query in all_queries
                }
                per_query_results: dict[str, tuple[list[dict], float]] = {}
                for future in as_completed(futures):
                    query, sources, elapsed = future.result()
                    per_query_results[query] = (sources, elapsed)

            # Preserve original query order for readability in the report.
            for query in all_queries:
                sources, elapsed = per_query_results[query]
                per_query_sources.append(sources)
                retrieval_calls.append(
                    {
                        "query": query,
                        "elapsed_s": round(elapsed, 2),
                        "source_count": len(sources),
                        "titles": [s.get("title") for s in sources],
                    }
                )
    finally:
        if original_fanout_model and original_fanout_model != fanout_model:
            set_workspace_chat_model(anythingllm_base_url, workspace_slug=workspace_slug, chat_model=original_fanout_model)

    with stopwatch.track("dedupe/rank"):
        deduped_sources = dedupe_sources(per_query_sources, max_total=max_context_chunks)

    with stopwatch.track("synthesis"):
        answer = synthesize_answer(
            ollama_base_url,
            model=synthesis_model,
            question=question,
            sources=deduped_sources,
        )

    unique_documents = {s.get("title") for s in deduped_sources if s.get("title")}
    total_chunks_retrieved = sum(len(sources) for sources in per_query_sources)

    return {
        "question": question,
        "subqueries": subqueries,
        "queries_run": len(all_queries),
        "retrieval_calls": retrieval_calls,
        "total_chunks_retrieved": total_chunks_retrieved,
        "deduped_source_titles": [s.get("title") for s in deduped_sources],
        "deduped_source_count": len(deduped_sources),
        "unique_document_count": len(unique_documents),
        "answer": answer,
        "decompose_model": decompose_model,
        "fanout_model": fanout_model,
        "synthesis_model": synthesis_model,
        "fanout_concurrency": fanout_concurrency,
        "timings": stopwatch.stages,
        "total_latency_s": round(stopwatch.total(), 2),
        "timing_report": stopwatch.report(),
    }


def answer_broad_query_direct(
    *,
    workspace_slug: str,
    ollama_base_url: str,
    question: str,
    decompose_model: str,
    synthesis_model: str,
    embedding_model: str = "mxbai-embed-large",
    container: str = "moogle-anythingllm",
    storage_dir: str = "/app/server/storage/lancedb",
    max_subqueries: int = DEFAULT_MAX_SUBQUERIES,
    top_k_per_query: int = DEFAULT_TOP_K_PER_QUERY,
    max_context_chunks: int = DEFAULT_MAX_CONTEXT_CHUNKS,
    similarity_threshold: float = 0.25,
) -> dict:
    """Same pipeline as answer_broad_query(), but retrieval goes straight to
    the existing AnythingLLM LanceDB table instead of through AnythingLLM's
    mode=query chat endpoint -- eliminating the throwaway LLM generation that
    dominates fan-out latency in the AnythingLLM-backed path.
    """
    from moogle_ingest.direct_retrieval import direct_vector_search, embed_texts

    stopwatch = Stopwatch()

    with stopwatch.track("decomposition"):
        subqueries = decompose_query(
            ollama_base_url,
            model=decompose_model,
            question=question,
            max_subqueries=max_subqueries,
        )
    all_queries = [question] + subqueries

    with stopwatch.track("embedding"):
        vectors = embed_texts(ollama_base_url, model=embedding_model, texts=all_queries)

    with stopwatch.track("lancedb search"):
        results_by_query = direct_vector_search(
            container=container,
            storage_dir=storage_dir,
            namespace=workspace_slug,
            queries=[(query, vector, top_k_per_query) for query, vector in zip(all_queries, vectors)],
            similarity_threshold=similarity_threshold,
        )

    per_query_sources: list[list[dict]] = []
    retrieval_calls: list[dict] = []
    for query in all_queries:
        sources = results_by_query.get(query, [])
        per_query_sources.append(sources)
        retrieval_calls.append(
            {
                "query": query,
                "source_count": len(sources),
                "titles": [s.get("title") for s in sources],
            }
        )

    with stopwatch.track("dedupe/rank"):
        deduped_sources = dedupe_sources(per_query_sources, max_total=max_context_chunks)

    with stopwatch.track("synthesis"):
        answer = synthesize_answer(
            ollama_base_url,
            model=synthesis_model,
            question=question,
            sources=deduped_sources,
        )

    unique_documents = {s.get("title") for s in deduped_sources if s.get("title")}
    total_chunks_retrieved = sum(len(sources) for sources in per_query_sources)

    return {
        "question": question,
        "subqueries": subqueries,
        "queries_run": len(all_queries),
        "retrieval_calls": retrieval_calls,
        "total_chunks_retrieved": total_chunks_retrieved,
        "deduped_source_titles": [s.get("title") for s in deduped_sources],
        "deduped_source_count": len(deduped_sources),
        "unique_document_count": len(unique_documents),
        "answer": answer,
        "decompose_model": decompose_model,
        "embedding_model": embedding_model,
        "synthesis_model": synthesis_model,
        "backend": "direct-lancedb",
        "timings": stopwatch.stages,
        "total_latency_s": round(stopwatch.total(), 2),
        "timing_report": stopwatch.report(),
    }
