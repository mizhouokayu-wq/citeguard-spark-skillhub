"""Deterministic anti-hallucination gate and SkillHub policy enforcer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from .parser import ParsedCitation
from .resolver import GroundTruthRecord, SEARCH_SCOPE_NOTE
from .spark_runner import SparkInferenceResult

STATUS_VERIFIED = "✅ 已核验存在"
STATUS_SUSPICIOUS = "⚠️ 存疑"
STATUS_FABRICATED = "❌ 疑似编造"
STATUS_UNVERIFIABLE = "⬜ 无法核验"

ALLOWED_ALIGNMENTS = {"支持", "部分支持", "无关", "矛盾", "未提供正文"}


@dataclass
class FieldDiff:
    field_name: str
    expected: str
    retrieved: str
    matched: bool


@dataclass
class AuditVerdict:
    ref_id: str
    status: str
    claim_alignment: str
    field_diffs: List[FieldDiff] = field(default_factory=list)
    hallucination_patterns: List[str] = field(default_factory=list)
    evidence_quote: Optional[str] = None
    evidence_quote_verified: Optional[bool] = None
    claim_quote: Optional[str] = None
    claim_quote_verified: Optional[bool] = None
    gate_overrides: List[str] = field(default_factory=list)
    spark_reasoning_zh: Optional[str] = None
    repair_suggestion: Optional[str] = None
    search_scope: str = SEARCH_SCOPE_NOTE


def normalize_ws_lower(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def similarity(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    na = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", a.lower()).strip()
    nb = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", b.lower()).strip()
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _last_name_tokens(authors: List[str]) -> set[str]:
    tokens: set[str] = set()
    for a in authors:
        parts = [p for p in re.split(r"[\s,]+", a.lower().strip(".")) if len(p) >= 2]
        if parts:
            # Handle both "Ashish Vaswani" and "Vaswani, A."
            tokens.add(parts[0])
            tokens.add(parts[-1])
    return tokens


def check_verbatim_quote(quote: Optional[str], corpus: Optional[str]) -> Optional[bool]:
    if not quote:
        return None
    if not corpus:
        return False
    nq = normalize_ws_lower(quote)
    nc = normalize_ws_lower(corpus)
    if len(nq) < 6:
        return False
    return nq in nc


def evaluate_citation(
    citation: ParsedCitation,
    gt: GroundTruthRecord,
    spark: Optional[SparkInferenceResult] = None,
) -> AuditVerdict:
    """Combine deterministic registry checks with Spark-X2.6-4B reasoning."""
    diffs: List[FieldDiff] = []
    patterns: List[str] = []
    overrides: List[str] = []

    # 1. Determine existence & metadata match deterministically first
    if not gt.found:
        if citation.doi and citation.doi_syntax_valid is False:
            status = STATUS_FABRICATED
            patterns.append("DOI 语法结构非法（不符合 10.<注册商>/<后缀> 规范）")
        elif citation.doi and gt.http_status == 404:
            status = STATUS_FABRICATED
            patterns.append("DOI 编号格式合法但 Crossref 未注册（HTTP 404，典型 LLM 编造 DOI 模式）")
        elif citation.arxiv_id and gt.http_status == 200:
            status = STATUS_FABRICATED
            patterns.append("arXiv ID 检索返回空记录（不存在对应预印本）")
        else:
            status = STATUS_UNVERIFIABLE
            patterns.append(f"检索边界外或网络受限：{gt.error or '无匹配元数据'}")

        if not citation.claim_text:
            alignment = "未提供正文"
        else:
            alignment = "未提供正文" if status == STATUS_UNVERIFIABLE else "无关"
            overrides.append("Gate: 目标文献未核验存在，禁止由模型宣称正文声明被支持")

        return AuditVerdict(
            ref_id=citation.ref_id,
            status=status,
            claim_alignment=alignment,
            field_diffs=diffs,
            hallucination_patterns=patterns,
            gate_overrides=overrides,
            spark_reasoning_zh=(spark.parsed_json or {}).get("reasoning_zh") if spark and spark.parsed_json else None,
            repair_suggestion="建议删除该条目或由作者核对原始文献后重新补录（任何替代题录需作者自行核验）"
            if status == STATUS_FABRICATED
            else "处于当前公开检索源边界之外，需人工核查原始馆藏/内部报告",
        )

    # Ground truth found -> field-by-field deterministic comparison
    title_sim = similarity(citation.title, gt.title)
    title_ok = title_sim >= 0.80 if citation.title else True
    if citation.title:
        diffs.append(
            FieldDiff(
                field_name="title",
                expected=citation.title,
                retrieved=gt.title or "",
                matched=title_ok,
            )
        )

    year_ok = True
    if citation.year and gt.year:
        year_ok = abs(citation.year - gt.year) <= 0
        diffs.append(
            FieldDiff(
                field_name="year",
                expected=str(citation.year),
                retrieved=str(gt.year),
                matched=year_ok,
            )
        )

    author_ok = True
    if citation.authors and gt.authors:
        cited_tokens = _last_name_tokens(citation.authors)
        gt_tokens = _last_name_tokens(gt.authors)
        overlap = cited_tokens & gt_tokens
        author_ok = len(overlap) > 0
        diffs.append(
            FieldDiff(
                field_name="author",
                expected=", ".join(citation.authors[:3]),
                retrieved=", ".join(gt.authors[:3]),
                matched=author_ok,
            )
        )

    if not title_ok or not year_ok or not author_ok:
        status = STATUS_SUSPICIOUS
        if not title_ok:
            patterns.append(f"标题与检索记录存在明显偏差（相似度 {title_sim:.2f}）")
        if not author_ok:
            patterns.append("张冠李戴风险：引用作者与检索文献作者无交集")
        if not year_ok:
            patterns.append(f"发表年份不一致（引用 {citation.year} vs 检索 {gt.year}）")
    else:
        status = STATUS_VERIFIED

    # 2. Evaluate Spark-X2.6-4B claim-alignment & verbatim quote gates
    spark_json: Dict[str, Any] = (spark.parsed_json if spark and spark.parsed_json else {}) or {}
    spark_reasoning = spark_json.get("reasoning_zh")

    if not citation.claim_text:
        alignment = "未提供正文"
        if spark_json.get("claim_alignment") and spark_json.get("claim_alignment") != "未提供正文":
            overrides.append("Gate: 未提供正文段落，禁止伪装成已完成声明对齐检查")
    else:
        raw_align = spark_json.get("claim_alignment", "未提供正文")
        alignment = raw_align if raw_align in ALLOWED_ALIGNMENTS else "未提供正文"

    ev_quote = spark_json.get("evidence_quote")
    cl_quote = spark_json.get("claim_quote")
    ev_verified = check_verbatim_quote(ev_quote, gt.evidence_corpus())
    cl_verified = check_verbatim_quote(cl_quote, citation.claim_text)

    if citation.claim_text and ev_quote and ev_verified is False:
        overrides.append("Gate: Spark 返回的 evidence_quote 未能在检索文献原文中精确命中，已标为未核实引用")
    if citation.claim_text and alignment == "支持" and ev_verified is not True:
        overrides.append("Gate: 缺乏可复核的原文逐字证据片段，建议人工复核支持关系")

    repair = None
    if status == STATUS_SUSPICIOUS and gt.title:
        repair = (
            f"待作者自行核验：检索到的真实题录为《{gt.title}》"
            f"（{', '.join(gt.authors[:3]) if gt.authors else '未知作者'}, {gt.year or '年份未知'}）"
        )

    return AuditVerdict(
        ref_id=citation.ref_id,
        status=status,
        claim_alignment=alignment,
        field_diffs=diffs,
        hallucination_patterns=patterns,
        evidence_quote=ev_quote,
        evidence_quote_verified=ev_verified,
        claim_quote=cl_quote,
        claim_quote_verified=cl_verified,
        gate_overrides=overrides,
        spark_reasoning_zh=spark_reasoning,
        repair_suggestion=repair,
    )
