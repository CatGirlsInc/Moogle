from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from moogle_ingest.wikitext import wikitext_to_markdown


NS = {"mw": "http://www.mediawiki.org/xml/export-0.11/"}


def _read_page_xml(path: Path) -> dict:
    root = ET.parse(path).getroot()
    page = root.find("mw:page", NS)
    if page is None:
        return {
            "title": "Untitled",
            "namespace": "0",
            "page_id": "0",
            "redirect": None,
            "text": "",
        }

    title = page.find("mw:title", NS)
    namespace = page.find("mw:ns", NS)
    redirect = page.find("mw:redirect", NS)
    revision = page.find("mw:revision", NS)
    text_elem = revision.find("mw:text", NS) if revision is not None else None
    page_id = page.find("mw:id", NS)

    return {
        "title": (title.text if title is not None else "Untitled"),
        "namespace": (namespace.text if namespace is not None else "0"),
        "page_id": (page_id.text if page_id is not None else "0"),
        "redirect": (redirect.attrib.get("title") if redirect is not None else None),
        "text": (text_elem.text if text_elem is not None else ""),
    }


def convert_pages_to_markdown(*, input_dir: Path, output_dir: Path, manifest_path: Path) -> list[dict]:
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    redirect_aliases: dict[str, str] = {}

    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return results

    manifest = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in manifest:
        source_path = Path(row["xml_path"])
        if not source_path.exists():
            continue

        page_data = _read_page_xml(source_path)
        if page_data["redirect"]:
            redirect_aliases[row["title"]] = page_data["redirect"]
            continue

        namespace = page_data["namespace"]
        if namespace not in {"0", "14"}:
            continue

        body = wikitext_to_markdown(page_data["text"] or "")
        title = page_data["title"]
        source_url = f"https://www.bg-wiki.com/ffxi/{title.replace(' ', '_')}"
        markdown = (
            "---\n"
            f"title: \"{title}\"\n"
            f"page_id: {page_data['page_id']}\n"
            f"namespace: {namespace}\n"
            f"source: \"{source_url}\"\n"
            "---\n\n"
            f"# {title}\n\n"
            f"{body.strip()}\n"
        )

        out_path = output_dir / (source_path.stem + ".md")
        out_path.write_text(markdown, encoding="utf-8")
        results.append({"title": title, "source_path": str(source_path), "output_path": str(out_path)})

    redirect_manifest = output_dir.parent / "metadata" / "redirects.json"
    redirect_manifest.parent.mkdir(parents=True, exist_ok=True)
    redirect_manifest.write_text(json.dumps(redirect_aliases, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Converted {len(results)} pages to markdown in {output_dir}")
    return results
