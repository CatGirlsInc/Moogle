from __future__ import annotations

import json

from moogle_ingest.direct_retrieval import direct_vector_search, embed_texts


def test_embed_texts_orders_by_index(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [
                    {"index": 1, "embedding": [0.2, 0.2]},
                    {"index": 0, "embedding": [0.1, 0.1]},
                ]
            }

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("moogle_ingest.direct_retrieval.requests.post", fake_post)

    vectors = embed_texts("http://localhost:11434", model="mxbai-embed-large", texts=["a", "b"])

    assert vectors == [[0.1, 0.1], [0.2, 0.2]]
    assert captured["url"] == "http://localhost:11434/v1/embeddings"
    assert captured["json"] == {"model": "mxbai-embed-large", "input": ["a", "b"]}


def test_direct_vector_search_builds_request_and_parses_response(monkeypatch):
    monkeypatch.setattr("moogle_ingest.direct_retrieval.shutil.which", lambda name: "/usr/bin/docker")

    calls = []

    class FakeCompletedProcess:
        def __init__(self, stdout="", returncode=0, stderr=""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(cmd, check=False, capture_output=False, text=False, timeout=None):
        calls.append(cmd)
        if cmd[:2] == ["docker", "cp"]:
            return FakeCompletedProcess()
        if cmd[:2] == ["docker", "exec"]:
            response = [{"query": "accuracy", "sources": [{"title": "819-Accuracy.md", "score": 0.9}]}]
            return FakeCompletedProcess(stdout=json.dumps(response))
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("moogle_ingest.direct_retrieval.subprocess.run", fake_run)

    result = direct_vector_search(
        namespace="bg-wiki",
        queries=[("accuracy", [0.1, 0.2], 4)],
        similarity_threshold=0.25,
    )

    assert result == {"accuracy": [{"title": "819-Accuracy.md", "score": 0.9}]}
    docker_exec_calls = [c for c in calls if c[:2] == ["docker", "exec"]]
    assert len(docker_exec_calls) == 1


def test_direct_vector_search_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr("moogle_ingest.direct_retrieval.shutil.which", lambda name: "/usr/bin/docker")

    class FakeCompletedProcess:
        def __init__(self, stdout="", returncode=0, stderr=""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(cmd, check=False, capture_output=False, text=False, timeout=None):
        if cmd[:2] == ["docker", "cp"]:
            return FakeCompletedProcess()
        return FakeCompletedProcess(returncode=1, stderr="boom")

    monkeypatch.setattr("moogle_ingest.direct_retrieval.subprocess.run", fake_run)

    try:
        direct_vector_search(namespace="bg-wiki", queries=[("q", [0.1], 4)])
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "boom" in str(exc)
