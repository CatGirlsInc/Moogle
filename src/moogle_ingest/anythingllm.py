from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import requests

ProgressCallback = Callable[[int, int, Path], None]

DEFAULT_WORKSPACE_NAME = "BG Wiki"
DEFAULT_WORKSPACE_DESCRIPTION = "FFXI BG-Wiki reference material from the processed markdown corpus."
_IMAGE_MARKDOWN_SUFFIXES = (".png.md", ".jpg.md", ".jpeg.md", ".gif.md")
_ATTACHED_FILENAME_PATTERN = re.compile(r"^(?P<name>.+\.md)-[0-9a-fA-F-]{36}\.json$")


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    json_body=None,
    files=None,
    data=None,
    timeout: int = 120,
) -> dict | list:
    response = session.request(method=method, url=url, json=json_body, files=files, data=data, timeout=timeout)
    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("detail") or payload.get("message") or payload.get("error") or response.text
        except ValueError:
            pass
        raise RuntimeError(f"AnythingLLM request failed for {url}: {response.status_code} {detail}")

    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        # Some successful AnythingLLM routes return plain text/HTML despite 2xx status.
        return {}


def _request_sse_events(
    session: requests.Session,
    url: str,
    *,
    json_body: dict,
    timeout: int = 300,
) -> list[dict]:
    response = session.request("POST", url=url, json=json_body, timeout=timeout)
    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("detail") or payload.get("message") or payload.get("error") or response.text
        except ValueError:
            pass
        raise RuntimeError(f"AnythingLLM request failed for {url}: {response.status_code} {detail}")

    events: list[dict] = []
    for raw_line in response.text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            events.append(decoded)

    return events


def has_meaningful_markdown_content(file_path: Path) -> bool:
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        return False

    body = text
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end != -1:
            body = body[end + 5 :]

    body = body.strip()
    if body.startswith("# "):
        parts = body.split("\n", 1)
        if len(parts) > 1:
            body = parts[1].strip()
        else:
            body = ""

    return bool(body and any(ch.isalnum() for ch in body))


def collect_eligible_markdown_files(input_dir: Path) -> tuple[list[Path], int]:
    markdown_files = sorted(input_dir.rglob("*.md"))
    eligible: list[Path] = []

    for path in markdown_files:
        lowered = path.name.lower()
        if lowered.endswith(_IMAGE_MARKDOWN_SUFFIXES):
            continue
        if has_meaningful_markdown_content(path):
            eligible.append(path)

    skipped = len(markdown_files) - len(eligible)
    return eligible, skipped


def _find_workspace_by_name(session: requests.Session, base_url: str, name: str) -> dict | None:
    payload = _request_json(session, "GET", f"{base_url}/api/workspaces")
    workspaces = payload.get("workspaces", []) if isinstance(payload, dict) else []
    for workspace in workspaces:
        if isinstance(workspace, dict) and workspace.get("name") == name:
            return workspace
    return None


def _get_workspace_documents(session: requests.Session, base_url: str, workspace_slug: str) -> list[dict]:
    payload = _request_json(session, "GET", f"{base_url}/api/workspace/{workspace_slug}")
    workspace = payload.get("workspace") if isinstance(payload, dict) else None
    documents = workspace.get("documents", []) if isinstance(workspace, dict) else []
    return [doc for doc in documents if isinstance(doc, dict)]


def _extract_attached_markdown_names(documents: list[dict]) -> set[str]:
    names: set[str] = set()
    for document in documents:
        metadata = document.get("metadata")
        if isinstance(metadata, str):
            try:
                decoded = json.loads(metadata)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict):
                title = decoded.get("title")
                if isinstance(title, str) and title.lower().endswith(".md"):
                    names.add(title)
                    continue

        filename = document.get("filename")
        if isinstance(filename, str):
            match = _ATTACHED_FILENAME_PATTERN.match(filename)
            if match:
                names.add(match.group("name"))

    return names


def ensure_workspace(
    base_url: str,
    *,
    workspace_name: str,
    description: str,
    chat_provider: str = "ollama",
    chat_model: str = "llama3.2:3b",
    recreate: bool = True,
) -> str:
    base = _normalize_base_url(base_url)
    session = requests.Session()

    existing = _find_workspace_by_name(session, base, workspace_name)
    if existing and recreate:
        _request_json(session, "DELETE", f"{base}/api/workspace/{existing['slug']}")
        existing = None

    if not existing:
        created = _request_json(
            session,
            "POST",
            f"{base}/api/workspace/new",
            json_body={"name": workspace_name},
        )
        workspace = created.get("workspace") if isinstance(created, dict) else None
        if not isinstance(workspace, dict):
            raise RuntimeError("AnythingLLM workspace creation did not return a workspace payload")
        slug = str(workspace["slug"])
    else:
        slug = str(existing["slug"])

    _request_json(
        session,
        "POST",
        f"{base}/api/workspace/{slug}/update",
        json_body={
            "queryRefusalResponse": description,
            "chatProvider": chat_provider,
            "chatModel": chat_model,
            "chatMode": "chat",
        },
    )
    return slug


def ingest_markdown(
    input_dir: str | Path = "data/processed/markdown",
    base_url: str = "http://localhost:3001",
    workspace_name: str = DEFAULT_WORKSPACE_NAME,
    description: str = DEFAULT_WORKSPACE_DESCRIPTION,
    chat_model: str = "llama3.2:3b",
    embedding_model: str = "mxbai-embed-large",
    recreate_workspace: bool = True,
    skip_existing: bool = False,
    progress: ProgressCallback | None = None,
) -> dict:
    source_dir = Path(input_dir)
    if not source_dir.exists():
        raise FileNotFoundError(f"Prepared markdown directory not found: {source_dir}")

    eligible_files, skipped = collect_eligible_markdown_files(source_dir)
    if not eligible_files:
        raise FileNotFoundError(f"No eligible Markdown files found under: {source_dir}")

    base = _normalize_base_url(base_url)
    workspace_slug = ensure_workspace(
        base,
        workspace_name=workspace_name,
        description=description,
        chat_provider="ollama",
        chat_model=chat_model,
        recreate=recreate_workspace,
    )

    session = requests.Session()
    already_attached_names: set[str] = set()
    if skip_existing:
        documents = _get_workspace_documents(session, base, workspace_slug)
        already_attached_names = _extract_attached_markdown_names(documents)

    embedded_documents = 0
    failures: list[dict] = []
    total_files = len(eligible_files)
    skipped_existing = 0

    for index, markdown_file in enumerate(eligible_files, start=1):
        rel_path = markdown_file.relative_to(source_dir)
        if skip_existing and markdown_file.name in already_attached_names:
            skipped_existing += 1
            if progress is not None:
                progress(index, total_files, markdown_file)
            continue

        try:
            with markdown_file.open("rb") as handle:
                parse_result = _request_json(
                    session,
                    "POST",
                    f"{base}/api/workspace/{workspace_slug}/parse",
                    files={"file": (markdown_file.name, handle, "text/markdown")},
                )

            parsed_files = parse_result.get("files", []) if isinstance(parse_result, dict) else []
            if not parsed_files:
                raise RuntimeError("parse endpoint returned no files")

            for parsed in parsed_files:
                file_id = parsed.get("id") if isinstance(parsed, dict) else None
                if file_id is None:
                    continue
                _request_json(
                    session,
                    "POST",
                    f"{base}/api/workspace/{workspace_slug}/embed-parsed-file/{file_id}",
                )
                embedded_documents += 1

            if progress is not None:
                progress(index, total_files, markdown_file)
        except Exception as exc:  # pragma: no cover - exercised via result accounting
            failures.append({"path": str(rel_path), "error": str(exc)})

    return {
        "workspace_name": workspace_name,
        "workspace_slug": workspace_slug,
        "embedding_model": embedding_model,
        "chat_model": chat_model,
        "total_markdown_files": len(list(source_dir.rglob("*.md"))),
        "eligible_files": total_files,
        "skipped_files": skipped,
        "skipped_existing_files": skipped_existing,
        "uploaded_files": embedded_documents,
        "failed_files": len(failures),
        "failures": failures,
    }


def query_workspace(
    base_url: str,
    *,
    workspace_slug: str,
    prompt: str,
    mode: str = "query",
) -> dict:
    base = _normalize_base_url(base_url)
    session = requests.Session()
    events = _request_sse_events(
        session,
        f"{base}/api/workspace/{workspace_slug}/stream-chat",
        json_body={"message": prompt, "mode": mode},
        timeout=300,
    )
    if not events:
        raise RuntimeError("AnythingLLM stream-chat returned no events")

    answer_parts: list[str] = []
    sources: list[dict] = []
    chat_id = None
    metrics: dict = {}

    for event in events:
        event_type = event.get("type")
        if event_type == "textResponseChunk":
            chunk = event.get("textResponse")
            if isinstance(chunk, str):
                answer_parts.append(chunk)
            event_sources = event.get("sources")
            if isinstance(event_sources, list):
                sources = [source for source in event_sources if isinstance(source, dict)]
        elif event_type == "finalizeResponseStream":
            chat_id = event.get("chatId")
            event_metrics = event.get("metrics")
            if isinstance(event_metrics, dict):
                metrics = event_metrics

    return {
        "workspace_slug": workspace_slug,
        "prompt": prompt,
        "answer": "".join(answer_parts).strip(),
        "sources": sources,
        "chat_id": chat_id,
        "metrics": metrics,
    }
