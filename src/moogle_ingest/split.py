from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {"mw": "http://www.mediawiki.org/xml/export-0.11/"}


def _safe_title(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[\\/:*?\"<>|]+", "-", value)
    value = re.sub(r"\s+", "-", value)
    return value[:180] or "untitled"


def split_mediawiki_xml(*, input_path: Path, output_dir: Path, manifest_path: Path) -> list[dict]:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    manifest_path = Path(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    siteinfo = None
    current_page = None
    page_count = 0
    manifest_rows: list[dict] = []

    for event, elem in ET.iterparse(str(input_path), events=("start", "end")):
        if event == "start" and elem.tag == "{http://www.mediawiki.org/xml/export-0.11/}siteinfo":
            siteinfo = ET.fromstring(ET.tostring(elem))
            continue

        if event == "start" and elem.tag == "{http://www.mediawiki.org/xml/export-0.11/}page":
            current_page = elem
            continue

        if current_page is not None and event == "end" and elem.tag == "{http://www.mediawiki.org/xml/export-0.11/}page":
            title = None
            ns = None
            page_id = None
            redirect = None
            text = ""

            for child in current_page:
                if child.tag == "{http://www.mediawiki.org/xml/export-0.11/}title":
                    title = child.text or ""
                elif child.tag == "{http://www.mediawiki.org/xml/export-0.11/}ns":
                    ns = child.text or "0"
                elif child.tag == "{http://www.mediawiki.org/xml/export-0.11/}id":
                    page_id = child.text or ""
                elif child.tag == "{http://www.mediawiki.org/xml/export-0.11/}redirect":
                    redirect = child.attrib.get("title")
                elif child.tag == "{http://www.mediawiki.org/xml/export-0.11/}revision":
                    for rev_child in child:
                        if rev_child.tag == "{http://www.mediawiki.org/xml/export-0.11/}text":
                            text = rev_child.text or ""

            if title:
                safe_title = _safe_title(title)
                file_name = f"{page_id or page_count}-{safe_title}.xml"
                xml_path = output_dir / file_name

                root = ET.Element("mediawiki", {"xmlns": "http://www.mediawiki.org/xml/export-0.11/", "version": "0.11", "xml:lang": "en"})
                if siteinfo is not None:
                    root.append(ET.fromstring(ET.tostring(siteinfo)))
                root.append(ET.fromstring(ET.tostring(current_page)))
                ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)

                manifest_rows.append({
                    "page_id": page_id,
                    "title": title,
                    "namespace": ns,
                    "redirect": redirect,
                    "source_path": str(input_path),
                    "xml_path": str(xml_path),
                    "text_length": len(text),
                })
                page_count += 1

            current_page = None
            elem.clear()

    with manifest_path.open("w", encoding="utf-8") as fh:
        for row in manifest_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Split {page_count} pages into {output_dir}")
    return manifest_rows
