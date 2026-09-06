from __future__ import annotations

import json
from pathlib import Path

import zstandard as zstd

from moogle_ingest.anythingllm import collect_eligible_markdown_files, ensure_workspace, ingest_markdown, query_workspace
from moogle_ingest.bootstrap import run_bootstrap
from moogle_ingest.cli import build_parser
from moogle_ingest.convert import convert_pages_to_markdown
from moogle_ingest.decompress import decompress_archive
from moogle_ingest.downselect import downselect_markdown
from moogle_ingest.split import split_mediawiki_xml

SAMPLE_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/" version="0.11" xml:lang="en">
  <siteinfo>
    <sitename>Test Wiki</sitename>
    <base>https://example.com/wiki/Main_Page</base>
    <generator>MediaWiki 1.39.11</generator>
    <case>first-letter</case>
    <namespaces>
      <namespace key="-2" case="first-letter">Media</namespace>
      <namespace key="0" case="first-letter">Main</namespace>
      <namespace key="14" case="first-letter">Category</namespace>
    </namespaces>
  </siteinfo>
  <page>
    <title>Test Page</title>
    <ns>0</ns>
    <id>10</id>
    <revision>
      <id>100</id>
      <timestamp>2025-02-13T05:45:23Z</timestamp>
      <contributor>
        <username>Tester</username>
        <id>1</id>
      </contributor>
      <text bytes="10" sha1="abc" xml:space="preserve">== Heading ==\n\nThis is a test page.</text>
    </revision>
  </page>
</mediawiki>
'''


def test_split_mediawiki_xml_creates_page_files(tmp_path: Path):
    xml_path = tmp_path / "sample.xml"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    output_dir = tmp_path / "xml"
    manifest_path = tmp_path / "metadata" / "pages.jsonl"

    rows = split_mediawiki_xml(input_path=xml_path, output_dir=output_dir, manifest_path=manifest_path)

    assert len(rows) == 1
    assert output_dir.exists()
    assert any(p.name.endswith(".xml") for p in output_dir.iterdir())
    assert manifest_path.exists()


def test_convert_pages_to_markdown_creates_markdown(tmp_path: Path):
    xml_path = tmp_path / "sample.xml"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    output_dir = tmp_path / "xml"
    manifest_path = tmp_path / "metadata" / "pages.jsonl"
    split_mediawiki_xml(input_path=xml_path, output_dir=output_dir, manifest_path=manifest_path)

    markdown_dir = tmp_path / "markdown"
    rows = convert_pages_to_markdown(input_dir=output_dir, output_dir=markdown_dir, manifest_path=manifest_path)

    assert rows
    assert any(p.suffix == ".md" for p in markdown_dir.iterdir())
    assert "# Test Page" in (markdown_dir / "10-Test-Page.md").read_text(encoding="utf-8")


def test_downselect_markdown_removes_empty_documents(tmp_path: Path):
    markdown_dir = tmp_path / "markdown"
    markdown_dir.mkdir()
    (markdown_dir / "real.md").write_text("---\ntitle: \"Real\"\n---\n\n# Real\n\nThis has content.\n", encoding="utf-8")
    (markdown_dir / "stub.md").write_text("---\ntitle: \"Untitled\"\n---\n\n# Untitled\n\n", encoding="utf-8")

    result = downselect_markdown(input_dir=markdown_dir)

    assert result == {"kept": 1, "removed": 1}
    assert (markdown_dir / "real.md").exists()
    assert not (markdown_dir / "stub.md").exists()


def test_run_bootstrap_skips_completed_stages_and_still_downselects(tmp_path: Path, monkeypatch):
    raw_dir = tmp_path / "data" / "raw"
    processed_dir = tmp_path / "data" / "processed"
    archive_path = raw_dir / "www.bg-wiki.com-20250225-current.xml.zst"
    xml_path = raw_dir / "www.bg-wiki.com-20250225-current.xml"
    xml_dir = processed_dir / "xml"
    markdown_dir = processed_dir / "markdown"
    manifest_path = processed_dir / "metadata" / "pages.jsonl"

    raw_dir.mkdir(parents=True)
    xml_dir.mkdir(parents=True)
    markdown_dir.mkdir(parents=True)
    manifest_path.parent.mkdir(parents=True)
    archive_path.write_text("archive", encoding="utf-8")
    xml_path.write_text("xml", encoding="utf-8")
    (xml_dir / "10-Test-Page.xml").write_text("<xml/>", encoding="utf-8")
    manifest_path.write_text('{"page_id": "10"}\n', encoding="utf-8")
    (markdown_dir / "10-Test-Page.md").write_text("# Real\n\nBody\n", encoding="utf-8")
    (markdown_dir / "11-Stub.md").write_text("# Untitled\n\n", encoding="utf-8")

    calls: list[str] = []

    monkeypatch.setattr("moogle_ingest.bootstrap.download_archive", lambda **kwargs: calls.append("download"))
    monkeypatch.setattr("moogle_ingest.bootstrap.decompress_archive", lambda **kwargs: calls.append("decompress"))
    monkeypatch.setattr("moogle_ingest.bootstrap.split_mediawiki_xml", lambda **kwargs: calls.append("split"))
    monkeypatch.setattr("moogle_ingest.bootstrap.convert_pages_to_markdown", lambda **kwargs: calls.append("convert"))

    run_bootstrap(archive_path=archive_path, output_dir=processed_dir, force=False)

    assert calls == []
    assert (markdown_dir / "10-Test-Page.md").exists()
    assert not (markdown_dir / "11-Stub.md").exists()


def test_decompress_large_zstd_archive(tmp_path: Path):
    source = tmp_path / "large.txt"
    payload = ("BG-Wiki test payload\n" * 5000).encode("utf-8")
    source.write_bytes(payload)

    compressed = tmp_path / "large.txt.zst"
    with compressed.open("wb") as fh:
        fh.write(zstd.ZstdCompressor().compress(payload))

    extracted = tmp_path / "large.out.txt"
    result = decompress_archive(input_path=compressed, output=extracted)

    assert result == extracted
    assert extracted.read_bytes() == payload


def test_collect_eligible_markdown_files_skips_image_sidecars_and_empty(tmp_path: Path):
    md_dir = tmp_path / "markdown"
    md_dir.mkdir()
    (md_dir / "real.md").write_text("# Real\n\nContent\n", encoding="utf-8")
    (md_dir / "title-only.md").write_text("# Untitled\n\n", encoding="utf-8")
    (md_dir / "icon.png.md").write_text("# icon\n\nContent\n", encoding="utf-8")

    eligible, skipped = collect_eligible_markdown_files(md_dir)

    assert [p.name for p in eligible] == ["real.md"]
    assert skipped == 2


def test_cli_ingest_defaults():
    args = build_parser().parse_args(["ingest"])

    assert args.command == "ingest"
    assert args.input == "data/processed/markdown"
    assert args.base_url == "http://localhost:3001"
    assert args.chat_model == "llama3.2:3b"
    assert args.embedding_model == "mxbai-embed-large"
    assert args.resume is False


def test_ingest_markdown_uploads_and_updates_embeddings(monkeypatch, tmp_path: Path):
    md_dir = tmp_path / "markdown"
    md_dir.mkdir()
    (md_dir / "one.md").write_text("# One\n\nAlpha\n", encoding="utf-8")
    (md_dir / "two.md").write_text("# Two\n\nBeta\n", encoding="utf-8")

    calls = []

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self.payload = payload
            self.status_code = status_code
            self.content = json.dumps(payload).encode("utf-8")
            self.text = json.dumps(payload)

        def json(self):
            return self.payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def request(self, method, url, json=None, files=None, data=None, timeout=None):
            calls.append({"method": method, "url": url, "json": json, "data": data, "files": files})

            if url.endswith("/api/workspaces"):
                return FakeResponse({"workspaces": []})
            if url.endswith("/api/workspace/new"):
                return FakeResponse({"workspace": {"name": "BG Wiki", "slug": "bg-wiki"}})
            if url.endswith("/api/workspace/bg-wiki/update"):
                return FakeResponse({"workspace": {"slug": "bg-wiki"}, "message": None})
            if url.endswith("/api/workspace/bg-wiki/parse"):
                filename = files["file"][0]
                return FakeResponse({"success": True, "files": [{"id": 10, "filename": filename}]})
            if url.endswith("/api/workspace/bg-wiki/embed-parsed-file/10"):
                return FakeResponse({"success": True, "document": {"docpath": "bg-wiki/doc.json"}})
            raise AssertionError(f"Unexpected request {method} {url}")

    monkeypatch.setattr("moogle_ingest.anythingllm.requests.Session", lambda: FakeSession())

    result = ingest_markdown(input_dir=md_dir, base_url="http://localhost:3001")

    assert result["workspace_slug"] == "bg-wiki"
    assert result["eligible_files"] == 2
    assert result["uploaded_files"] == 2
    assert result["failed_files"] == 0
    parse_calls = [call for call in calls if call["url"].endswith("/api/workspace/bg-wiki/parse")]
    embed_calls = [call for call in calls if "/api/workspace/bg-wiki/embed-parsed-file/" in call["url"]]
    assert len(parse_calls) == 2
    assert len(embed_calls) == 2


def test_ingest_markdown_resume_skips_already_attached(monkeypatch, tmp_path: Path):
    md_dir = tmp_path / "markdown"
    md_dir.mkdir()
    (md_dir / "one.md").write_text("# One\n\nAlpha\n", encoding="utf-8")
    (md_dir / "two.md").write_text("# Two\n\nBeta\n", encoding="utf-8")

    calls = []

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self.payload = payload
            self.status_code = status_code
            self.content = json.dumps(payload).encode("utf-8")
            self.text = json.dumps(payload)

        def json(self):
            return self.payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def request(self, method, url, json=None, files=None, data=None, timeout=None):
            calls.append({"method": method, "url": url, "json": json, "data": data, "files": files})

            if url.endswith("/api/workspaces"):
                return FakeResponse({"workspaces": [{"name": "BG Wiki", "slug": "bg-wiki"}]})
            if url.endswith("/api/workspace/bg-wiki/update"):
                return FakeResponse({"workspace": {"slug": "bg-wiki"}, "message": None})
            if url.endswith("/api/workspace/bg-wiki") and method == "GET":
                return FakeResponse(
                    {
                        "workspace": {
                            "documents": [
                                {
                                    "filename": "one.md-01234567-89ab-cdef-0123-456789abcdef.json",
                                    "metadata": '{"title": "one.md"}',
                                }
                            ]
                        }
                    }
                )
            if url.endswith("/api/workspace/bg-wiki/parse"):
                filename = files["file"][0]
                return FakeResponse({"success": True, "files": [{"id": 10, "filename": filename}]})
            if url.endswith("/api/workspace/bg-wiki/embed-parsed-file/10"):
                return FakeResponse({"success": True, "document": {"docpath": "bg-wiki/doc.json"}})
            raise AssertionError(f"Unexpected request {method} {url}")

    monkeypatch.setattr("moogle_ingest.anythingllm.requests.Session", lambda: FakeSession())

    result = ingest_markdown(
        input_dir=md_dir,
        base_url="http://localhost:3001",
        recreate_workspace=False,
        skip_existing=True,
    )

    assert result["uploaded_files"] == 1
    assert result["skipped_existing_files"] == 1
    parse_calls = [call for call in calls if call["url"].endswith("/api/workspace/bg-wiki/parse")]
    assert len(parse_calls) == 1


def test_query_workspace_parses_stream_chat_sse(monkeypatch):
    sse = "\n".join(
        [
            'data: {"type":"textResponseChunk","textResponse":"Answer: ","sources":[{"title":"819-Accuracy.md"}],"close":false,"error":false}',
            'data: {"type":"textResponseChunk","textResponse":"floor(DEX * 0.75)","sources":[{"title":"819-Accuracy.md"}],"close":true,"error":false}',
            'data: {"type":"finalizeResponseStream","close":true,"error":false,"chatId":7,"metrics":{"total_tokens":42}}',
        ]
    )

    class FakeResponse:
        def __init__(self, text, status_code=200):
            self.status_code = status_code
            self.text = text
            self.content = text.encode("utf-8")

        def json(self):
            return json.loads(self.text)

    class FakeSession:
        def request(self, method, url, json=None, files=None, data=None, timeout=None):
            assert method == "POST"
            assert url.endswith("/api/workspace/bg-wiki/stream-chat")
            assert json == {"message": "dex formula?", "mode": "query"}
            return FakeResponse(sse)

    monkeypatch.setattr("moogle_ingest.anythingllm.requests.Session", lambda: FakeSession())

    result = query_workspace(
        "http://localhost:3001",
        workspace_slug="bg-wiki",
        prompt="dex formula?",
        mode="query",
    )

    assert result["answer"] == "Answer: floor(DEX * 0.75)"
    assert result["chat_id"] == 7
    assert result["metrics"]["total_tokens"] == 42
    assert result["sources"][0]["title"] == "819-Accuracy.md"


def test_ensure_workspace_handles_non_json_delete_success(monkeypatch):
    class FakeResponse:
        def __init__(self, text: str = "", status_code: int = 200, payload=None):
            self.status_code = status_code
            self.payload = payload
            if payload is not None:
                self.text = json.dumps(payload)
                self.content = self.text.encode("utf-8")
            else:
                self.text = text
                self.content = text.encode("utf-8")

        def json(self):
            if self.payload is not None:
                return self.payload
            return json.loads(self.text)

    class FakeSession:
        def request(self, method, url, json=None, files=None, data=None, timeout=None):
            if method == "GET" and url.endswith("/api/workspaces"):
                return FakeResponse(payload={"workspaces": [{"name": "BG Wiki", "slug": "bg-wiki"}]})
            if method == "DELETE" and url.endswith("/api/workspace/bg-wiki"):
                return FakeResponse(text="ok")
            if method == "POST" and url.endswith("/api/workspace/new"):
                return FakeResponse(payload={"workspace": {"name": "BG Wiki", "slug": "bg-wiki"}})
            if method == "POST" and url.endswith("/api/workspace/bg-wiki/update"):
                return FakeResponse(payload={"workspace": {"slug": "bg-wiki"}})
            raise AssertionError(f"Unexpected request {method} {url}")

    monkeypatch.setattr("moogle_ingest.anythingllm.requests.Session", lambda: FakeSession())

    slug = ensure_workspace(
        "http://localhost:3001",
        workspace_name="BG Wiki",
        description="test",
        recreate=True,
    )

    assert slug == "bg-wiki"
