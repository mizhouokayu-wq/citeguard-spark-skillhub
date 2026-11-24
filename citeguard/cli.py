"""CLI entrypoint for CiteGuard."""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import run_pipeline
from .spark_runner import DEFAULT_LLAMA_CLI, DEFAULT_MODEL_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CiteGuard: SkillHub citation-integrity-verifier + local Spark-X2.6-4B"
    )
    parser.add_argument("--input", required=True, type=Path, help="Input JSON or BibTeX/txt file")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output directory for report artifacts")
    parser.add_argument("--cache", type=Path, default=None, help="Optional Crossref/arXiv JSON cache path")
    parser.add_argument("--offline", action="store_true", help="Use only cached ground truth (no network)")
    parser.add_argument("--skip-spark", action="store_true", help="Skip local Spark inference (deterministic only)")
    parser.add_argument("--llama-cli", type=Path, default=DEFAULT_LLAMA_CLI, help="Path to llama-cli executable")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH, help="Path to Spark-X2.6-4B GGUF")

    args = parser.parse_args()
    results = run_pipeline(
        input_path=args.input,
        out_dir=args.out_dir,
        cache_path=args.cache,
        offline_only=args.offline,
        skip_spark=args.skip_spark,
        llama_cli=args.llama_cli,
        model_path=args.model,
    )
    print(f"Processed {len(results['items'])} citations -> {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
