"""Local Spark-X2.6-4B GGUF runner via llama.cpp (llama-cli)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .parser import ParsedCitation
from .resolver import GroundTruthRecord

DEFAULT_LLAMA_CLI = Path(
    os.environ.get(
        "CITEGUARD_LLAMA_CLI",
        str(Path.home() / ".cache" / "llama-cpp-b12671-vulkan" / "llama-cli.exe"),
    )
)
DEFAULT_LLAMA_SERVER = Path(
    os.environ.get(
        "CITEGUARD_LLAMA_SERVER",
        str(Path.home() / ".cache" / "llama-cpp-b12671-vulkan" / "llama-server.exe"),
    )
)
DEFAULT_MODEL_PATH = Path(
    os.environ.get(
        "CITEGUARD_SPARK_GGUF",
        str(
            Path.home()
            / ".cache"
            / "huggingface"
            / "spark-x26-4b-gguf"
            / "Spark-X2.6-4B-Q4_K_M.gguf"
        ),
    )
)

SYSTEM_PROMPT = (
    "You are an academic citation verification assistant guided by the SkillHub "
    "`citation-integrity-verifier` skill. "
    "You MUST rely ONLY on the provided [CITED_ENTRY], [MANUSCRIPT_CLAIM], and "
    "[RETRIEVED_GROUND_TRUTH] blocks. Never invent papers, DOIs, or quotes. "
    "Return ONLY one valid JSON object with keys: "
    "metadata_assessment (one of: exact_match, partial_mismatch, not_found, unverifiable), "
    "mismatch_fields (array of strings from: title, author, year, venue, doi), "
    "claim_alignment (one of: 支持, 部分支持, 无关, 矛盾, 未提供正文), "
    "evidence_quote (exact verbatim substring copied from RETRIEVED_GROUND_TRUTH title or abstract, or null), "
    "claim_quote (exact verbatim substring copied from MANUSCRIPT_CLAIM, or null), "
    "reasoning_zh (concise 1-2 sentence Chinese explanation)."
)


@dataclass
class SparkInferenceResult:
    """Raw output and timing/metadata from local Spark-X2.6-4B inference."""

    prompt: str
    raw_output: str
    parsed_json: Optional[Dict[str, Any]]
    elapsed_sec: float
    runtime_command: str
    error: Optional[str] = None


def build_verification_prompt(
    citation: ParsedCitation,
    ground_truth: GroundTruthRecord,
) -> str:
    """Construct the structured prompt sent to local Spark-X2.6-4B."""
    cited_block = {
        "ref_id": citation.ref_id,
        "raw_text": citation.raw_text,
        "parsed_title": citation.title,
        "parsed_authors": citation.authors,
        "parsed_year": citation.year,
        "parsed_venue": citation.venue,
        "parsed_doi": citation.doi,
        "parsed_arxiv_id": citation.arxiv_id,
    }
    gt_block = {
        "found": ground_truth.found,
        "source": ground_truth.source,
        "lookup_method": ground_truth.lookup_method,
        "http_status": ground_truth.http_status,
        "title": ground_truth.title,
        "authors": ground_truth.authors[:8],
        "year": ground_truth.year,
        "venue": ground_truth.venue,
        "doi": ground_truth.doi,
        "arxiv_id": ground_truth.arxiv_id,
        "abstract": (ground_truth.abstract or "")[:1800] if ground_truth.abstract else None,
        "error": ground_truth.error,
    }
    claim_text = citation.claim_text or "未提供正文"

    return (
        f"[CITED_ENTRY]\n{json.dumps(cited_block, ensure_ascii=False, indent=2)}\n\n"
        f"[MANUSCRIPT_CLAIM]\n{claim_text}\n\n"
        f"[RETRIEVED_GROUND_TRUTH]\n{json.dumps(gt_block, ensure_ascii=False, indent=2)}\n\n"
        "Output ONLY the JSON object:"
    )


def extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first valid JSON object from model output, ignoring markdown fences/think tags."""
    # Strip <think>...</think> blocks if any
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Try direct parse
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Scan for balanced {...}
    start_indices = [i for i, ch in enumerate(cleaned) if ch == "{"]
    for start in start_indices:
        depth = 0
        in_str = False
        escape = False
        for end in range(start, len(cleaned)):
            ch = cleaned[end]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[start : end + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict):
                                return obj
                        except json.JSONDecodeError:
                            break
    return None


def run_spark_step(
    citation: ParsedCitation,
    ground_truth: GroundTruthRecord,
    llama_cli: Path = DEFAULT_LLAMA_CLI,
    model_path: Path = DEFAULT_MODEL_PATH,
    ngl: int = 99,
    ctx_size: int = 4096,
    max_tokens: int = 512,
    timeout_sec: int = 120,
) -> SparkInferenceResult:
    """Invoke local Spark-X2.6-4B GGUF via llama-cli in deterministic single-turn mode."""
    user_prompt = build_verification_prompt(citation, ground_truth)
    if not llama_cli.exists():
        return SparkInferenceResult(
            prompt=user_prompt,
            raw_output="",
            parsed_json=None,
            elapsed_sec=0.0,
            runtime_command=str(llama_cli),
            error=f"llama-cli not found at {llama_cli}",
        )
    if not model_path.exists():
        return SparkInferenceResult(
            prompt=user_prompt,
            raw_output="",
            parsed_json=None,
            elapsed_sec=0.0,
            runtime_command=str(model_path),
            error=f"Spark GGUF model not found at {model_path}",
        )

    cmd = [
        str(llama_cli),
        "-m",
        str(model_path),
        "-ngl",
        str(ngl),
        "-c",
        str(ctx_size),
        "-n",
        str(max_tokens),
        "--temp",
        "0",
        "--seed",
        "42",
        "--reasoning",
        "off",
        "--reasoning-budget",
        "0",
        "--no-display-prompt",
        "-st",
        "-sys",
        SYSTEM_PROMPT,
        "-p",
        user_prompt,
    ]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        elapsed = round(time.perf_counter() - t0, 2)
    except subprocess.TimeoutExpired:
        elapsed = round(time.perf_counter() - t0, 2)
        return SparkInferenceResult(
            prompt=user_prompt,
            raw_output="",
            parsed_json=None,
            elapsed_sec=elapsed,
            runtime_command=" ".join(cmd[:6]),
            error=f"Inference timed out after {timeout_sec}s",
        )

    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 and not raw:
        return SparkInferenceResult(
            prompt=user_prompt,
            raw_output=proc.stderr or "",
            parsed_json=None,
            elapsed_sec=elapsed,
            runtime_command=" ".join(cmd[:6]),
            error=f"llama-cli exited with code {proc.returncode}",
        )

    parsed = extract_first_json_object(raw)
    err = None if parsed is not None else "Spark output did not contain valid JSON"
    return SparkInferenceResult(
        prompt=user_prompt,
        raw_output=raw,
        parsed_json=parsed,
        elapsed_sec=elapsed,
        runtime_command=" ".join(cmd[:6]),
        error=err,
    )


@contextmanager
def managed_llama_server(
    llama_server: Path = DEFAULT_LLAMA_SERVER,
    model_path: Path = DEFAULT_MODEL_PATH,
    port: int = 18931,
    ngl: int = 99,
    ctx_size: int = 4096,
    startup_timeout_sec: int = 90,
) -> Iterator[str]:
    """Start llama-server once for batch inference and shut it down cleanly."""
    if not llama_server.exists():
        raise FileNotFoundError(f"llama-server not found at {llama_server}")
    if not model_path.exists():
        raise FileNotFoundError(f"Spark GGUF model not found at {model_path}")

    cmd = [
        str(llama_server),
        "-m",
        str(model_path),
        "-ngl",
        str(ngl),
        "-c",
        str(ctx_size),
        "--port",
        str(port),
        "--reasoning",
        "off",
        "--reasoning-budget",
        "0",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + startup_timeout_sec
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"llama-server exited prematurely with code {proc.returncode}")
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=2) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)
        if not ready:
            raise TimeoutError(f"llama-server did not become healthy within {startup_timeout_sec}s")
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_spark_via_server(
    citation: ParsedCitation,
    ground_truth: GroundTruthRecord,
    base_url: str,
    max_tokens: int = 512,
    timeout_sec: int = 90,
) -> SparkInferenceResult:
    """Call an already-loaded llama-server /v1/chat/completions endpoint."""
    user_prompt = build_verification_prompt(citation, ground_truth)
    payload = {
        "model": "Spark-X2.6-4B-Q4_K_M",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            body = json.loads(r.read().decode("utf-8"))
        elapsed = round(time.perf_counter() - t0, 2)
    except Exception as exc:  # noqa: BLE001
        elapsed = round(time.perf_counter() - t0, 2)
        return SparkInferenceResult(
            prompt=user_prompt,
            raw_output="",
            parsed_json=None,
            elapsed_sec=elapsed,
            runtime_command=f"POST {base_url}/v1/chat/completions",
            error=str(exc),
        )

    raw = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    parsed = extract_first_json_object(raw)
    err = None if parsed is not None else "Spark output did not contain valid JSON"
    return SparkInferenceResult(
        prompt=user_prompt,
        raw_output=raw,
        parsed_json=parsed,
        elapsed_sec=elapsed,
        runtime_command=f"POST {base_url}/v1/chat/completions (temp=0, seed=42, reasoning=off)",
        error=err,
    )
