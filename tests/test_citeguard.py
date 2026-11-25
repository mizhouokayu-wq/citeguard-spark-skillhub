"""Automated unit tests for CiteGuard (no LLM or live network required)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from citeguard.cli import main as cli_main
from citeguard.parser import parse_references, validate_doi_syntax
from citeguard.pipeline import load_input_bundle, run_pipeline
from citeguard.resolver import GroundTruthRecord, strip_xml_tags
from citeguard.spark_runner import SparkInferenceResult, extract_first_json_object
from citeguard.verifier import (
    STATUS_FABRICATED,
    STATUS_SUSPICIOUS,
    STATUS_UNVERIFIABLE,
    STATUS_VERIFIED,
    check_verbatim_quote,
    evaluate_citation,
)


class CiteGuardTests(unittest.TestCase):
    def test_doi_syntax_validation_separated_from_existence(self) -> None:
        self.assertTrue(validate_doi_syntax("10.1145/9999999.8888888"))
        self.assertTrue(validate_doi_syntax("10.1038/s41591-025-99999-z"))
        self.assertFalse(validate_doi_syntax("11.1234/invalid-prefix"))
        self.assertFalse(validate_doi_syntax("10.12/short"))
        self.assertIsNone(validate_doi_syntax(None))

    def test_bibtex_and_gbt_parsing(self) -> None:
        bib = """
@inproceedings{vaswani2017attention,
  title={Attention Is All You Need},
  author={Vaswani, Ashish and Shazeer, Noam},
  booktitle={NeurIPS},
  year={2017},
  eprint={1706.03762}
}
"""
        parsed = parse_references(bib, {"vaswani2017attention": "Transformers use attention."})
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].arxiv_id, "1706.03762")
        self.assertEqual(parsed[0].year, 2017)
        self.assertEqual(parsed[0].claim_text, "Transformers use attention.")

        gbt = "[1] Vaswani A, Shazeer N. Attention Is All You Need[C]//NeurIPS. 2017. doi:10.5555/3295222.3295349"
        parsed_gbt = parse_references(gbt)
        self.assertEqual(parsed_gbt[0].format_detected, "GB/T 7714")
        self.assertEqual(parsed_gbt[0].title, "Attention Is All You Need")
        self.assertEqual(parsed_gbt[0].doi, "10.5555/3295222.3295349")

        gbt_arxiv = "[3] Lewis P, Perez E. Retrieval-Augmented Generation[C]//NeurIPS. 2020. arXiv:2005.11401"
        parsed_ax = parse_references(gbt_arxiv)
        self.assertEqual(parsed_ax[0].title, "Retrieval-Augmented Generation")
        self.assertEqual(parsed_ax[0].year, 2020)

    def test_strip_xml_and_json_extraction(self) -> None:
        raw_xml = "<jats:p>We propose <jats:italic>LoRA</jats:italic> for adaptation.</jats:p>"
        self.assertEqual(strip_xml_tags(raw_xml), "We propose LoRA for adaptation.")

        raw_model = '<think>reasoning...</think>\n```json\n{"claim_alignment": "支持", "evidence_quote": "We propose LoRA"}\n```'
        obj = extract_first_json_object(raw_model)
        self.assertIsNotNone(obj)
        self.assertEqual(obj["claim_alignment"], "支持")

    def test_fabricated_doi_gate_blocks_false_verified(self) -> None:
        c = parse_references("[8] Chen X. Fake Paper[J]. 2024. doi:10.1145/9999999.8888888")[0]
        c.claim_text = "Demonstrated 98.4% reduction."
        gt = GroundTruthRecord(
            found=False,
            source="Crossref",
            lookup_method="doi_exact",
            lookup_url="https://api.crossref.org/works/10.1145%2F9999999.8888888",
            http_status=404,
            error="DOI not registered in Crossref (HTTP 404)",
        )
        # Even if a faulty model tried to claim support, gate must enforce ❌ 疑似编造 + 无关
        bad_spark = SparkInferenceResult(
            prompt="p",
            raw_output='{"claim_alignment": "支持"}',
            parsed_json={"claim_alignment": "支持"},
            elapsed_sec=1.0,
            runtime_command="mock",
        )
        v = evaluate_citation(c, gt, bad_spark)
        self.assertEqual(v.status, STATUS_FABRICATED)
        self.assertEqual(v.claim_alignment, "无关")
        self.assertTrue(len(v.gate_overrides) > 0)

    def test_author_year_mismatch_forces_suspicious(self) -> None:
        c = parse_references("[6] Touvron H. Attention Is All You Need[J]. Nature, 2023. arXiv:1706.03762")[0]
        gt = GroundTruthRecord(
            found=True,
            source="arXiv",
            lookup_method="arxiv_id_exact",
            lookup_url="https://export.arxiv.org/api/query?id_list=1706.03762",
            http_status=200,
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            year=2017,
            abstract="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
        )
        v = evaluate_citation(c, gt, None)
        self.assertEqual(v.status, STATUS_SUSPICIOUS)
        self.assertEqual(v.claim_alignment, "未提供正文")

    def test_verbatim_quote_gate_catches_invented_quote(self) -> None:
        c = parse_references("[1] Vaswani A. Attention Is All You Need[C]. 2017. arXiv:1706.03762")[0]
        c.claim_text = "Transformers dispense with recurrence entirely."
        gt = GroundTruthRecord(
            found=True,
            source="arXiv",
            lookup_method="arxiv_id_exact",
            lookup_url="https://export.arxiv.org/api/query?id_list=1706.03762",
            http_status=200,
            title="Attention Is All You Need",
            authors=["Ashish Vaswani"],
            year=2017,
            abstract="We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
        )
        good_quote = "based solely on attention mechanisms, dispensing with recurrence and convolutions entirely"
        self.assertTrue(check_verbatim_quote(good_quote, gt.evidence_corpus()))
        self.assertFalse(check_verbatim_quote("invented quote not in abstract", gt.evidence_corpus()))

        spark_bad_quote = SparkInferenceResult(
            prompt="p",
            raw_output="{}",
            parsed_json={
                "claim_alignment": "支持",
                "evidence_quote": "completely fabricated sentence from thin air",
            },
            elapsed_sec=0.5,
            runtime_command="mock",
        )
        v = evaluate_citation(c, gt, spark_bad_quote)
        self.assertEqual(v.status, STATUS_VERIFIED)
        self.assertFalse(v.evidence_quote_verified)
        self.assertTrue(any("evidence_quote" in g for g in v.gate_overrides))

    def test_offline_pipeline_writes_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            inp = tmp_dir / "refs.json"
            cache = tmp_dir / "cache.json"
            out = tmp_dir / "out"
            inp.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "ref_id": "R10",
                                "citation": "[10] Internal Lab. Whitepaper[R]. 2025.",
                                "claim_text": None,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            cache.write_text("{}", encoding="utf-8")
            res = run_pipeline(inp, out, cache_path=cache, offline_only=True, skip_spark=True)
            self.assertEqual(res["items"][0]["verdict"]["status"], STATUS_UNVERIFIABLE)
            self.assertTrue((out / "report.md").exists())
            self.assertTrue((out / "results.json").exists())
            self.assertTrue((out / "evidence_replay.html").exists())

    def test_apa_and_quoted_title_parsing(self) -> None:
        apa = (
            "Dettmers, T., Pagnoni, A., Holtzman, A., & Zettlemoyer, L. (2023). "
            "QLoRA: Efficient Finetuning of Quantized LLMs. arXiv:2305.14314"
        )
        parsed_apa = parse_references(apa)
        self.assertEqual(len(parsed_apa), 1)
        self.assertEqual(parsed_apa[0].format_detected, "APA")
        self.assertEqual(parsed_apa[0].title, "QLoRA: Efficient Finetuning of Quantized LLMs")
        self.assertEqual(parsed_apa[0].year, 2023)
        self.assertEqual(parsed_apa[0].arxiv_id, "2305.14314")

        quoted = '[2] Dao T. "FlashAttention: Fast and Memory-Efficient Exact Attention". NeurIPS 2022. arXiv:2205.14135'
        parsed_q = parse_references(quoted)
        self.assertEqual(parsed_q[0].title, "FlashAttention: Fast and Memory-Efficient Exact Attention")
        self.assertEqual(parsed_q[0].year, 2022)
        self.assertEqual(parsed_q[0].arxiv_id, "2205.14135")

    def test_title_mismatch_forces_suspicious(self) -> None:
        c = parse_references("[4] Vaswani A. Completely Unrelated Paper Title[C]. 2017. arXiv:1706.03762")[0]
        gt = GroundTruthRecord(
            found=True,
            source="arXiv",
            lookup_method="arxiv_id_exact",
            lookup_url="https://export.arxiv.org/api/query?id_list=1706.03762",
            http_status=200,
            title="Attention Is All You Need",
            authors=["Ashish Vaswani"],
            year=2017,
            abstract="The dominant sequence transduction models are based on attention.",
        )
        v = evaluate_citation(c, gt, None)
        self.assertEqual(v.status, STATUS_SUSPICIOUS)
        self.assertTrue(any("标题" in p for p in v.hallucination_patterns))

    def test_load_bibtex_file_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bib_path = Path(tmp) / "refs.bib"
            bib_path.write_text(
                "@article{hu2021lora,\n  title={LoRA: Low-Rank Adaptation of Large Language Models},\n"
                "  author={Hu, Edward J. and Wallis, Phillip},\n  journal={ICLR},\n  year={2022},\n"
                "  eprint={2106.09685}\n}\n",
                encoding="utf-8",
            )
            entries, meta = load_input_bundle(bib_path)
            self.assertEqual(meta, {})
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].ref_id, "hu2021lora")
            self.assertEqual(entries[0].arxiv_id, "2106.09685")

    def test_cli_offline_benchmark_smoke(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sample_inp = root / "benchmarks" / "sample_manuscript.json"
        cache_path = root / "benchmarks" / "ground_truth_cache.json"
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "cli_out"
            argv = [
                "citeguard",
                "--input",
                str(sample_inp),
                "--out-dir",
                str(out_dir),
                "--cache",
                str(cache_path),
                "--offline",
                "--skip-spark",
            ]
            with patch.object(sys, "argv", argv):
                rc = cli_main()
            self.assertEqual(rc, 0)
            data = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["items"]), 10)
            self.assertTrue((out_dir / "report.md").exists())
            self.assertTrue((out_dir / "evidence_replay.html").exists())


if __name__ == "__main__":
    unittest.main()
