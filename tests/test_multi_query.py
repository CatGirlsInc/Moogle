from __future__ import annotations

from moogle_ingest.cli import build_parser
from moogle_ingest.multi_query import build_context_block, dedupe_sources, parse_subqueries


def test_parse_subqueries_handles_json_array():
    raw = '["accuracy stats FFXI", "accuracy gear FFXI", "accuracy stats FFXI"]'
    assert parse_subqueries(raw) == ["accuracy stats FFXI", "accuracy gear FFXI"]


def test_parse_subqueries_handles_markdown_fenced_json():
    raw = '```json\n["one query", "two query"]\n```'
    assert parse_subqueries(raw) == ["one query", "two query"]


def test_parse_subqueries_falls_back_to_bulleted_lines():
    raw = "1. first query\n- second query\n* third query"
    assert parse_subqueries(raw) == ["first query", "second query", "third query"]


def test_parse_subqueries_respects_max_subqueries():
    raw = '["a", "b", "c", "d"]'
    assert parse_subqueries(raw, max_subqueries=2) == ["a", "b"]


def test_dedupe_sources_keeps_highest_score_and_sorts():
    sources_a = [{"id": "1", "title": "doc-a", "score": 0.5}]
    sources_b = [{"id": "1", "title": "doc-a", "score": 0.9}, {"id": "2", "title": "doc-b", "score": 0.7}]
    result = dedupe_sources([sources_a, sources_b])
    assert [s["id"] for s in result] == ["1", "2"]
    assert result[0]["score"] == 0.9


def test_dedupe_sources_truncates_to_max_total():
    sources = [{"id": str(i), "title": f"doc-{i}", "score": i} for i in range(5)]
    result = dedupe_sources([sources], max_total=2)
    assert [s["id"] for s in result] == ["4", "3"]


def test_build_context_block_labels_each_source():
    sources = [{"title": "819-Accuracy.md", "text": "Accuracy from DEX = floor(DEX * 0.75)"}]
    block = build_context_block(sources)
    assert "### Source: 819-Accuracy.md" in block
    assert "floor(DEX * 0.75)" in block


def test_cli_accepts_ask_and_set_chat_model_commands():
    parser = build_parser()
    args = parser.parse_args(["ask", "What is Blade Madrigal?"])
    assert args.command == "ask"
    assert args.synthesis_model == "qwen2.5:7b-instruct-q4_K_M"

    args = parser.parse_args(["set-chat-model", "--model", "qwen2.5:7b-instruct-q4_K_M"])
    assert args.command == "set-chat-model"
    assert args.workspace == "bg-wiki"
