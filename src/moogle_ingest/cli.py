from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BG-Wiki ingestion and markdown conversion pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="Download, preprocess, and downselect the BG-Wiki corpus")
    bootstrap.add_argument("--archive", default="data/raw/www.bg-wiki.com-20250225-current.xml.zst")
    bootstrap.add_argument("--output", default="data/processed")
    bootstrap.add_argument("--force", action="store_true", help="Clear prior raw/processed outputs and rebuild from scratch")

    ingest = subparsers.add_parser("ingest", help="Import prepared markdown files into an AnythingLLM workspace")
    ingest.add_argument("--input", default="data/processed/markdown")
    ingest.add_argument("--base-url", default="http://localhost:3001")
    ingest.add_argument("--name", default="BG Wiki")
    ingest.add_argument("--description", default="FFXI BG-Wiki reference material from the processed markdown corpus.")
    ingest.add_argument("--dry-run", action="store_true", help="Preview the files that would be uploaded without creating the knowledge base or uploading content")
    ingest.add_argument("--chat-model", default="llama3.2:3b")
    ingest.add_argument("--embedding-model", default="mxbai-embed-large")
    ingest.add_argument(
        "--preserve-workspace",
        action="store_true",
        help="Do not recreate the workspace before ingest. Default behavior recreates it for idempotent rebuilds.",
    )
    ingest.add_argument(
        "--resume",
        action="store_true",
        help="Resume a prior ingest by preserving the workspace and skipping markdown files already attached to it.",
    )

    up = subparsers.add_parser("up", help="Start the Docker compose stack (alias for `docker compose up -d --wait`)")
    up.add_argument("--gpu", action="store_true", help="Also apply the compose.gpu.yaml GPU override")
    up.add_argument("--no-wait", action="store_true", help="Do not wait for services to report healthy")

    down = subparsers.add_parser("down", help="Stop the Docker compose stack (alias for `docker compose down`)")
    down.add_argument("--gpu", action="store_true", help="Also apply the compose.gpu.yaml GPU override")
    down.add_argument("--volumes", action="store_true", help="Also remove named volumes (destroys runtime state)")

    set_chat_model = subparsers.add_parser(
        "set-chat-model", help="Switch a workspace's chat model without touching its documents/vectors"
    )
    set_chat_model.add_argument("--base-url", default="http://localhost:3001")
    set_chat_model.add_argument("--workspace", default="bg-wiki", help="Workspace slug")
    set_chat_model.add_argument("--model", required=True, help="Ollama model tag, e.g. qwen2.5:7b-instruct-q4_K_M")

    ask = subparsers.add_parser(
        "ask",
        help="Answer a broad question via multi-query retrieval against an AnythingLLM workspace",
    )
    ask.add_argument("question")
    ask.add_argument("--base-url", default="http://localhost:3001", help="AnythingLLM base URL")
    ask.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama base URL")
    ask.add_argument("--workspace", default="bg-wiki", help="Workspace slug")
    ask.add_argument("--decompose-model", default="qwen2.5:7b-instruct-q4_K_M", help="Model used for query decomposition")
    ask.add_argument("--synthesis-model", default="qwen2.5:7b-instruct-q4_K_M", help="Model used for the final grounded answer")
    ask.add_argument("--fanout-model", default="llama3.2:3b", help="Cheap/fast model temporarily set on the workspace for throwaway per-subquery retrieval calls")
    ask.add_argument("--max-subqueries", type=int, default=6)
    ask.add_argument("--top-k-per-query", type=int, default=4)
    ask.add_argument("--max-context-chunks", type=int, default=12)
    ask.add_argument("--concurrency", type=int, default=3, help="Max concurrent AnythingLLM fan-out retrieval calls (anythingllm backend only)")
    ask.add_argument(
        "--backend",
        choices=["anythingllm", "direct-lancedb"],
        default="anythingllm",
        help="Fan-out retrieval backend: 'anythingllm' (mode=query calls, baseline) or 'direct-lancedb' (bypasses AnythingLLM generation for retrieval)",
    )
    ask.add_argument("--embedding-model", default="mxbai-embed-large", help="Embedding model used for direct-lancedb query vectors")
    ask.add_argument("--container", default="moogle-anythingllm", help="AnythingLLM container name (direct-lancedb backend only)")
    ask.add_argument("--storage-dir", default="/app/server/storage/lancedb", help="LanceDB storage dir inside the container (direct-lancedb backend only)")
    ask.add_argument("--similarity-threshold", type=float, default=0.25, help="Minimum similarity score to keep a chunk (direct-lancedb backend only)")
    ask.add_argument("--verbose", action="store_true", help="Print per-stage timing breakdown and diagnostics")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "bootstrap":
        from moogle_ingest.bootstrap import run_bootstrap

        run_bootstrap(archive_path=Path(args.archive), output_dir=Path(args.output), force=args.force)
        return

    if args.command == "ingest":
        from moogle_ingest.anythingllm import collect_eligible_markdown_files, ingest_markdown

        input_dir = Path(args.input)
        if args.dry_run:
            eligible_files, skipped = collect_eligible_markdown_files(input_dir)
            if not eligible_files:
                raise FileNotFoundError(f"No eligible Markdown files found under: {input_dir}")
            print(f"Would ingest {len(eligible_files)} markdown files from {input_dir}")
            print(f"Skipped {skipped} markdown files (empty/title-only or image-sidecar markdown)")
            for markdown_file in eligible_files[:10]:
                print(f" - {markdown_file}")
            if len(eligible_files) > 10:
                print(f" - ... and {len(eligible_files) - 10} more")
            return

        def _print_progress(index: int, total: int, markdown_file: Path) -> None:
            print(f"[{index}/{total}] {markdown_file.name}", flush=True)

        result = ingest_markdown(
            input_dir=input_dir,
            base_url=args.base_url,
            workspace_name=args.name,
            description=args.description,
            chat_model=args.chat_model,
            embedding_model=args.embedding_model,
            recreate_workspace=not (args.preserve_workspace or args.resume),
            skip_existing=args.resume,
            progress=_print_progress,
        )

        print(
            f"workspace={result['workspace_name']} slug={result['workspace_slug']} "
            f"eligible={result['eligible_files']} uploaded={result['uploaded_files']} "
            f"failed={result['failed_files']} skipped={result['skipped_files']} "
            f"already_attached={result.get('skipped_existing_files', 0)}"
        )
        return

    if args.command == "up":
        from moogle_ingest.docker_stack import run_up

        sys.exit(run_up(gpu=args.gpu, wait=not args.no_wait))

    if args.command == "down":
        from moogle_ingest.docker_stack import run_down

        sys.exit(run_down(gpu=args.gpu, volumes=args.volumes))

    if args.command == "set-chat-model":
        from moogle_ingest.anythingllm import set_workspace_chat_model

        set_workspace_chat_model(args.base_url, workspace_slug=args.workspace, chat_model=args.model)
        print(f"workspace={args.workspace} chat_model={args.model}")
        return

    if args.command == "ask":
        if args.backend == "direct-lancedb":
            from moogle_ingest.multi_query import answer_broad_query_direct

            try:
                result = answer_broad_query_direct(
                    workspace_slug=args.workspace,
                    ollama_base_url=args.ollama_url,
                    question=args.question,
                    decompose_model=args.decompose_model,
                    synthesis_model=args.synthesis_model,
                    embedding_model=args.embedding_model,
                    container=args.container,
                    storage_dir=args.storage_dir,
                    max_subqueries=args.max_subqueries,
                    top_k_per_query=args.top_k_per_query,
                    max_context_chunks=args.max_context_chunks,
                    similarity_threshold=args.similarity_threshold,
                )
            except RuntimeError as exc:
                parser.error(str(exc))
        else:
            from moogle_ingest.multi_query import answer_broad_query

            result = answer_broad_query(
                anythingllm_base_url=args.base_url,
                workspace_slug=args.workspace,
                ollama_base_url=args.ollama_url,
                question=args.question,
                decompose_model=args.decompose_model,
                synthesis_model=args.synthesis_model,
                fanout_model=args.fanout_model,
                max_subqueries=args.max_subqueries,
                top_k_per_query=args.top_k_per_query,
                max_context_chunks=args.max_context_chunks,
                fanout_concurrency=args.concurrency,
            )

        if args.verbose:
            print(f"backend: {args.backend}")
            print(f"subqueries ({len(result['subqueries'])}): {result['subqueries']}")
            print(f"queries run: {result['queries_run']}")
            for call in result["retrieval_calls"]:
                elapsed = f"{call['elapsed_s']}s " if "elapsed_s" in call else ""
                print(f"  {elapsed}{call['query']!r} -> {call['source_count']} sources")
            print(
                f"chunks retrieved={result['total_chunks_retrieved']} "
                f"deduped={result['deduped_source_count']} "
                f"unique_documents={result['unique_document_count']}"
            )
            model_summary = f"decompose={result['decompose_model']} synthesis={result['synthesis_model']}"
            if "fanout_model" in result:
                model_summary += f" fanout={result['fanout_model']}"
            if "embedding_model" in result:
                model_summary += f" embedding={result['embedding_model']}"
            print(f"models: {model_summary}")
            print(f"\n{result['timing_report']}\n")
        else:
            print(f"subqueries: {result['subqueries']}")
            print(f"retrieved {result['deduped_source_count']} deduped chunks ({result['unique_document_count']} unique documents):")
            for title in result["deduped_source_titles"]:
                print(f"  - {title}")
        print(f"\n[{result['synthesis_model']}, {result['total_latency_s']}s total]\n{result['answer']}")
        return

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
