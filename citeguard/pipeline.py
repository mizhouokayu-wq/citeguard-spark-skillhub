"""End-to-end CiteGuard pipeline, Markdown report, and interactive HTML replay generator."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parser import ParsedCitation, parse_references
from .resolver import (
    GroundTruthRecord,
    SEARCH_SCOPE_NOTE,
    load_cache,
    resolve_citation,
    save_cache,
)
from .spark_runner import (
    DEFAULT_LLAMA_CLI,
    DEFAULT_LLAMA_SERVER,
    DEFAULT_MODEL_PATH,
    SparkInferenceResult,
    managed_llama_server,
    run_spark_step,
    run_spark_via_server,
)
from .verifier import (
    AuditVerdict,
    STATUS_FABRICATED,
    STATUS_SUSPICIOUS,
    STATUS_UNVERIFIABLE,
    STATUS_VERIFIED,
    evaluate_citation,
)


def load_input_bundle(input_path: Path) -> tuple[List[ParsedCitation], Dict[str, Any]]:
    """Load either JSON benchmark bundle or raw BibTeX/plain-text bibliography."""
    raw = input_path.read_text(encoding="utf-8")
    if input_path.suffix.lower() == ".json":
        data = json.loads(raw)
        if "references_text" in data:
            entries = parse_references(data["references_text"], data.get("claims_by_ref"))
            return entries, data.get("metadata", {})
        entries = []
        for item in data.get("items", []):
            parsed = parse_references(item["citation"], None)
            if parsed:
                c = parsed[0]
                c.ref_id = str(item.get("ref_id", c.ref_id))
                c.claim_text = item.get("claim_text")
                entries.append(c)
        return entries, data.get("metadata", {})
    return parse_references(raw), {}


def render_markdown_report(
    items: List[Dict[str, Any]],
    meta: Dict[str, Any],
) -> str:
    """Render report compliant with SkillHub citation-integrity-verifier SKILL.md."""
    total = len(items)
    counts = {
        STATUS_VERIFIED: sum(1 for x in items if x["verdict"]["status"] == STATUS_VERIFIED),
        STATUS_SUSPICIOUS: sum(1 for x in items if x["verdict"]["status"] == STATUS_SUSPICIOUS),
        STATUS_FABRICATED: sum(1 for x in items if x["verdict"]["status"] == STATUS_FABRICATED),
        STATUS_UNVERIFIABLE: sum(1 for x in items if x["verdict"]["status"] == STATUS_UNVERIFIABLE),
    }
    pass_rate = (counts[STATUS_VERIFIED] / total * 100.0) if total else 0.0
    suspicious_rate = ((counts[STATUS_SUSPICIOUS] + counts[STATUS_FABRICATED]) / total * 100.0) if total else 0.0

    lines = [
        "# CiteGuard 学术引用真实性与声明对齐核验报告",
        "",
        f"- **生成时间 (UTC)**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"- **SkillHub 技能**：`citation-integrity-verifier` (`v20261104.101003`)",
        f"- **本地推理模型**：`{meta.get('model', 'Spark-X2.6-4B-Q4_K_M')}`",
        f"- **检索源与范围声明**：{SEARCH_SCOPE_NOTE}（注：检索不到≠学术不端，未收录于上述公开库的会议报告或内部文献标为「无法核验」）",
        "",
        "## 1. 统计摘要",
        "",
        f"- 总核验条目：**{total}**",
        f"- {STATUS_VERIFIED}：**{counts[STATUS_VERIFIED]}**（通过率 {pass_rate:.1f}%）",
        f"- {STATUS_SUSPICIOUS}：**{counts[STATUS_SUSPICIOUS]}**",
        f"- {STATUS_FABRICATED}：**{counts[STATUS_FABRICATED]}**（疑点/疑似编造占比 {suspicious_rate:.1f}%）",
        f"- {STATUS_UNVERIFIABLE}：**{counts[STATUS_UNVERIFIABLE]}**",
        "",
        "## 2. 逐条验证状态表",
        "",
        "| ID | 状态 | DOI 语法 | 检索源/方式 | 声明对齐 | 耗时(s) | 核验摘要 |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]

    for x in items:
        c = x["citation"]
        gt = x["ground_truth"]
        v = x["verdict"]
        sp = x["spark"]
        doi_flag = (
            "合法" if c["doi_syntax_valid"] is True else ("非法" if c["doi_syntax_valid"] is False else "无DOI")
        )
        src_str = f"{gt['source']} ({gt['lookup_method']}, HTTP {gt['http_status'] or '-'})"
        summary = (v.get("spark_reasoning_zh") or gt.get("error") or "字段匹配通过").replace("\n", " ")[:70]
        lines.append(
            f"| `{c['ref_id']}` | {v['status']} | {doi_flag} | {src_str} | {v['claim_alignment']} | {sp['elapsed_sec']:.2f} | {summary} |"
        )

    lines += ["", "## 3. 差异明细、幻觉特征与证据链", ""]
    for x in items:
        c = x["citation"]
        gt = x["ground_truth"]
        v = x["verdict"]
        sp = x["spark"]
        lines.append(f"### [{c['ref_id']}] {v['status']} · 对齐：{v['claim_alignment']}")
        lines.append(f"- **原始引文**：`{c['raw_text']}`")
        if c.get("claim_text"):
            lines.append(f"- **正文声明**：{c['claim_text']}")
        lines.append(
            f"- **检索依据**：`{gt['source']}` / `{gt['lookup_method']}`"
            + (f" — [{gt['lookup_url']}]({gt['lookup_url']})" if gt.get("lookup_url") else "")
        )
        if v.get("field_diffs"):
            lines.append("- **字段比对**：")
            for d in v["field_diffs"]:
                mark = "一致" if d["matched"] else "**不匹配**"
                lines.append(f"  - `{d['field_name']}`：{mark}（引用：`{d['expected']}` vs 检索：`{d['retrieved']}`）")
        if v.get("hallucination_patterns"):
            lines.append(f"- **幻觉/风险特征**：{'; '.join(v['hallucination_patterns'])}")
        if v.get("evidence_quote"):
            q_mark = "✅ 原文命中" if v.get("evidence_quote_verified") else "⚠️ 未在原文命中"
            lines.append(f"- **文献原文证据片段**（{q_mark}）：> {v['evidence_quote']}")
        if v.get("gate_overrides"):
            lines.append(f"- **确定性门控拦截**：{'; '.join(v['gate_overrides'])}")
        if v.get("repair_suggestion"):
            lines.append(f"- **修复建议**：{v['repair_suggestion']}")
        if sp.get("raw_output"):
            lines.append(f"- **Spark 原始推理输出**：`{sp['raw_output'][:280].replace(chr(10), ' ')}`")
        lines.append("")

    lines += [
        "## 4. 合规与人工复核边界声明",
        "- 本报告仅提供技术性元数据检索与文本对齐核验结果，不作「学术不端」定性结论；最终定性由作者、审稿人或学术机构人工判断。",
        "- 本工具未改动用户原始参考文献列表；标注「待作者自行核验」的修复建议须由作者二次确认。",
    ]
    return "\n".join(lines)


def render_evidence_html(items: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
    """Generate a crisp, self-contained HTML evidence replay dashboard for walkthrough screenshots."""
    cards_html: List[str] = []
    for idx, x in enumerate(items, start=1):
        c = x["citation"]
        gt = x["ground_truth"]
        v = x["verdict"]
        sp = x["spark"]
        status = v["status"]
        badge_cls = (
            "ok"
            if status == STATUS_VERIFIED
            else ("warn" if status == STATUS_SUSPICIOUS else ("bad" if status == STATUS_FABRICATED else "muted"))
        )
        diffs_html = "".join(
            f"<li><code>{html.escape(d['field_name'])}</code>: "
            f"<span class='{'ok-t' if d['matched'] else 'bad-t'}'>{'MATCH' if d['matched'] else 'MISMATCH'}</span> "
            f"— cited <em>{html.escape(d['expected'][:70])}</em> vs registry <em>{html.escape(d['retrieved'][:70])}</em></li>"
            for d in v.get("field_diffs", [])
        )
        patterns_html = "".join(f"<li>{html.escape(p)}</li>" for p in v.get("hallucination_patterns", []))
        gates_html = "".join(f"<li>{html.escape(g)}</li>" for g in v.get("gate_overrides", []))
        ev_quote = html.escape(v.get("evidence_quote") or "N/A")
        ev_badge = (
            "VERBATIM_OK"
            if v.get("evidence_quote_verified") is True
            else ("UNVERIFIED_QUOTE" if v.get("evidence_quote_verified") is False else "NONE")
        )
        cards_html.append(
            f"""
        <section class="card" id="ref-{idx}">
          <div class="card-head">
            <span class="ref-id">[{html.escape(c['ref_id'])}]</span>
            <span class="badge {badge_cls}">{html.escape(status)}</span>
            <span class="align-pill">Claim Alignment: <strong>{html.escape(v['claim_alignment'])}</strong></span>
            <span class="time-pill">Spark: {sp['elapsed_sec']:.2f}s</span>
          </div>
          <div class="grid">
            <div class="pane">
              <h4>1. Parsed Citation &amp; Claim</h4>
              <p class="raw">{html.escape(c['raw_text'])}</p>
              <p class="claim"><strong>Manuscript Claim:</strong> {html.escape(c.get('claim_text') or '未提供正文')}</p>
            </div>
            <div class="pane">
              <h4>2. Ground Truth ({html.escape(gt['source'])} / HTTP {gt.get('http_status') or '-'})</h4>
              <p><strong>Title:</strong> {html.escape(gt.get('title') or gt.get('error') or 'N/A')}</p>
              <p><strong>Authors / Year:</strong> {html.escape(', '.join((gt.get('authors') or [])[:3]) or 'N/A')} ({gt.get('year') or '-'})</p>
              <ul class="diffs">{diffs_html or '<li>No comparable metadata fields</li>'}</ul>
            </div>
            <div class="pane">
              <h4>3. Spark-X2.6-4B Output &amp; Deterministic Gate</h4>
              <pre class="spark-raw">{html.escape((sp.get('raw_output') or sp.get('error') or '')[:420])}</pre>
              <p><strong>Evidence Quote [{ev_badge}]:</strong> <em>{ev_quote}</em></p>
              {'<ul class="warn-list">' + patterns_html + gates_html + '</ul>' if (patterns_html or gates_html) else ''}
            </div>
          </div>
        </section>"""
        )

    total = len(items)
    verified_n = sum(1 for x in items if x["verdict"]["status"] == STATUS_VERIFIED)
    suspicious_n = sum(1 for x in items if x["verdict"]["status"] == STATUS_SUSPICIOUS)
    fabricated_n = sum(1 for x in items if x["verdict"]["status"] == STATUS_FABRICATED)
    unverifiable_n = sum(1 for x in items if x["verdict"]["status"] == STATUS_UNVERIFIABLE)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>CiteGuard · Spark-X2.6-4B × SkillHub Evidence Replay</title>
<style>
  body {{ font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; background:#0b1020; color:#e5e7eb; margin:0; padding:24px; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-end; border-bottom:1px solid #24304a; padding-bottom:16px; margin-bottom:20px; }}
  h1 {{ margin:0; font-size:22px; color:#f8fafc; }}
  .sub {{ color:#94a3b8; font-size:13px; margin-top:4px; }}
  .stats {{ display:flex; gap:10px; flex-wrap:wrap; }}
  .stat {{ background:#131b31; border:1px solid #263352; border-radius:8px; padding:8px 14px; font-size:13px; }}
  .card {{ background:#11182c; border:1px solid #24304a; border-radius:10px; padding:16px; margin-bottom:14px; }}
  .card-head {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:12px; }}
  .ref-id {{ font-weight:700; color:#38bdf8; font-family:monospace; font-size:14px; }}
  .badge {{ padding:3px 10px; border-radius:999px; font-size:12px; font-weight:600; }}
  .badge.ok {{ background:#064e3b; color:#6ee7b7; }}
  .badge.warn {{ background:#78350f; color:#fcd34d; }}
  .badge.bad {{ background:#7f1d1d; color:#fca5a5; }}
  .badge.muted {{ background:#334155; color:#cbd5e1; }}
  .align-pill, .time-pill {{ background:#1e293b; color:#cbd5e1; padding:3px 10px; border-radius:6px; font-size:12px; }}
  .grid {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; }}
  .pane {{ background:#0b1222; border:1px solid #1e293b; border-radius:8px; padding:12px; font-size:12.5px; line-height:1.5; }}
  .pane h4 {{ margin:0 0 8px 0; font-size:12px; text-transform:uppercase; letter-spacing:0.04em; color:#7dd3fc; }}
  .raw {{ color:#cbd5e1; word-break:break-word; }}
  .claim {{ color:#fde68a; }}
  .spark-raw {{ background:#050914; border:1px solid #1e293b; padding:8px; border-radius:6px; overflow-x:auto; white-space:pre-wrap; word-break:break-word; font-size:11.5px; color:#a5f3fc; margin:0 0 8px 0; }}
  .ok-t {{ color:#34d399; font-weight:600; }}
  .bad-t {{ color:#f87171; font-weight:600; }}
  ul {{ margin:6px 0 0 18px; padding:0; }}
  .warn-list {{ color:#fca5a5; }}
</style>
</head>
<body>
  <header>
    <div>
      <h1>CiteGuard · Academic Citation &amp; Claim Integrity Auditor</h1>
      <div class="sub">SkillHub: <code>citation-integrity-verifier v20261104.101003</code> · Local Model: <code>{html.escape(meta.get('model', 'Spark-X2.6-4B-Q4_K_M'))}</code> · Registries: Crossref + arXiv</div>
    </div>
    <div class="stats">
      <div class="stat">Total: <strong>{total}</strong></div>
      <div class="stat">✅ Verified: <strong>{verified_n}</strong></div>
      <div class="stat">⚠️ Suspicious: <strong>{suspicious_n}</strong></div>
      <div class="stat">❌ Fabricated: <strong>{fabricated_n}</strong></div>
      <div class="stat">⬜ Unverifiable: <strong>{unverifiable_n}</strong></div>
    </div>
  </header>
  {''.join(cards_html)}
</body>
</html>"""


def run_pipeline(
    input_path: Path,
    out_dir: Path,
    cache_path: Optional[Path] = None,
    offline_only: bool = False,
    skip_spark: bool = False,
    use_server: bool = True,
    llama_cli: Path = DEFAULT_LLAMA_CLI,
    llama_server: Path = DEFAULT_LLAMA_SERVER,
    model_path: Path = DEFAULT_MODEL_PATH,
) -> Dict[str, Any]:
    """Run the full CiteGuard audit pipeline and write report artifacts."""
    citations, meta = load_input_bundle(input_path)
    cache_map = load_cache(cache_path) if cache_path else {}
    resolved_records: Dict[str, GroundTruthRecord] = {}
    for c in citations:
        resolved_records[c.ref_id] = resolve_citation(c, cache_map=cache_map, offline_only=offline_only)

    if cache_path and not offline_only:
        save_cache(cache_path, resolved_records)

    items_out: List[Dict[str, Any]] = []
    if skip_spark:
        for c in citations:
            gt = resolved_records[c.ref_id]
            spark_res = SparkInferenceResult(
                prompt="(skipped)",
                raw_output="{}",
                parsed_json={},
                elapsed_sec=0.0,
                runtime_command="skipped",
            )
            verdict: AuditVerdict = evaluate_citation(c, gt, spark_res)
            items_out.append(
                {
                    "citation": asdict(c),
                    "ground_truth": asdict(gt),
                    "spark": asdict(spark_res),
                    "verdict": asdict(verdict),
                }
            )
    elif use_server:
        with managed_llama_server(llama_server=llama_server, model_path=model_path) as base_url:
            for c in citations:
                gt = resolved_records[c.ref_id]
                spark_res = run_spark_via_server(c, gt, base_url=base_url)
                verdict = evaluate_citation(c, gt, spark_res)
                items_out.append(
                    {
                        "citation": asdict(c),
                        "ground_truth": asdict(gt),
                        "spark": asdict(spark_res),
                        "verdict": asdict(verdict),
                    }
                )
    else:
        for c in citations:
            gt = resolved_records[c.ref_id]
            spark_res = run_spark_step(c, gt, llama_cli=llama_cli, model_path=model_path)
            verdict = evaluate_citation(c, gt, spark_res)
            items_out.append(
                {
                    "citation": asdict(c),
                    "ground_truth": asdict(gt),
                    "spark": asdict(spark_res),
                    "verdict": asdict(verdict),
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    results_obj = {"metadata": meta, "items": items_out}
    (out_dir / "results.json").write_text(
        json.dumps(results_obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(
        render_markdown_report(items_out, meta),
        encoding="utf-8",
    )
    (out_dir / "evidence_replay.html").write_text(
        render_evidence_html(items_out, meta),
        encoding="utf-8",
    )
    return results_obj
