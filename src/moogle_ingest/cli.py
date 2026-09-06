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

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
