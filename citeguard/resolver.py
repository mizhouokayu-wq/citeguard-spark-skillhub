"""Deterministic ground-truth metadata & abstract retrieval from Crossref and arXiv."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parser import ParsedCitation, clean_doi

USER_AGENT = "CiteGuard-SparkSkillHub/0.1 (mailto:research-audit@example.org)"
SEARCH_SCOPE_NOTE = "Crossref REST API + arXiv API (export.arxiv.org) + OpenAlex Works API"


@dataclass
class GroundTruthRecord:
    """Normalized scholarly metadata retrieved from external authoritative registries."""

    found: bool
    source: str
    lookup_method: str
    lookup_url: str
    http_status: Optional[int] = None
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    abstract: Optional[str] = None
    error: Optional[str] = None
    raw_snippet: Optional[str] = None

    def evidence_corpus(self) -> str:
        """Return concatenated text against which verbatim Spark quotes are checked."""
        parts = [
            self.title or "",
            " ".join(self.authors),
            str(self.year) if self.year else "",
            self.venue or "",
            self.doi or "",
            self.arxiv_id or "",
            self.abstract or "",
        ]
        return "\n".join(p for p in parts if p).strip()


def strip_xml_tags(text: Optional[str]) -> Optional[str]:
    """Remove JATS/HTML tags from Crossref abstracts."""
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _http_get(url: str, timeout: int = 20, retries: int = 2) -> tuple[int, str]:
    import time

    last_code, last_body = 0, ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_code = exc.code
            last_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code == 429 and attempt < retries:
                time.sleep(2.5 * (attempt + 1))
                continue
            return last_code, last_body
        except Exception:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    return last_code, last_body


def _reconstruct_openalex_abstract(inv_idx: Optional[Dict[str, List[int]]]) -> Optional[str]:
    if not inv_idx:
        return None
    positions: List[tuple[int, str]] = []
    for word, idxs in inv_idx.items():
        for pos in idxs:
            positions.append((pos, word))
    if not positions:
        return None
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


def fetch_openalex_by_doi(doi: str) -> GroundTruthRecord:
    cleaned = clean_doi(doi)
    url = f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(cleaned, safe='')}"
    try:
        status, body = _http_get(url, timeout=15, retries=1)
    except Exception as exc:  # noqa: BLE001
        return GroundTruthRecord(
            found=False,
            source="OpenAlex",
            lookup_method="openalex_doi",
            lookup_url=url,
            error=f"Network error: {exc}",
        )
    if status != 200:
        return GroundTruthRecord(
            found=False,
            source="OpenAlex",
            lookup_method="openalex_doi",
            lookup_url=url,
            http_status=status,
            error=f"OpenAlex HTTP {status}",
        )
    data = json.loads(body)
    authors = [
        ((a.get("author") or {}).get("display_name") or "").strip()
        for a in (data.get("authorships") or [])
        if (a.get("author") or {}).get("display_name")
    ]
    loc = ((data.get("primary_location") or {}).get("source") or {}).get("display_name")
    abstract = _reconstruct_openalex_abstract(data.get("abstract_inverted_index"))
    return GroundTruthRecord(
        found=True,
        source="OpenAlex",
        lookup_method="openalex_doi",
        lookup_url=url,
        http_status=status,
        title=data.get("title"),
        authors=authors,
        year=data.get("publication_year"),
        venue=loc,
        doi=cleaned,
        abstract=abstract,
    )


def _parse_crossref_work(msg: Dict[str, Any], lookup_method: str, lookup_url: str, status: int) -> GroundTruthRecord:
    titles = msg.get("title") or []
    title = titles[0] if titles else None
    authors: List[str] = []
    for a in msg.get("author") or []:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        full = f"{given} {family}".strip() or (a.get("name") or "").strip()
        if full:
            authors.append(full)

    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and isinstance(parts[0][0], int):
            year = parts[0][0]
            break

    containers = msg.get("container-title") or []
    venue = containers[0] if containers else msg.get("publisher")
    abstract = strip_xml_tags(msg.get("abstract"))

    return GroundTruthRecord(
        found=True,
        source="Crossref",
        lookup_method=lookup_method,
        lookup_url=lookup_url,
        http_status=status,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=msg.get("DOI"),
        abstract=abstract,
    )


def fetch_crossref_by_doi(doi: str) -> GroundTruthRecord:
    cleaned = clean_doi(doi)
    encoded = urllib.parse.quote(cleaned, safe="")
    url = f"https://api.crossref.org/works/{encoded}"
    try:
        status, body = _http_get(url)
    except Exception as exc:  # noqa: BLE001
        return GroundTruthRecord(
            found=False,
            source="Crossref",
            lookup_method="doi_exact",
            lookup_url=url,
            error=f"Network error: {exc}",
        )
    if status == 404:
        return GroundTruthRecord(
            found=False,
            source="Crossref",
            lookup_method="doi_exact",
            lookup_url=url,
            http_status=404,
            error="DOI not registered in Crossref (HTTP 404)",
        )
    if status != 200:
        return GroundTruthRecord(
            found=False,
            source="Crossref",
            lookup_method="doi_exact",
            lookup_url=url,
            http_status=status,
            error=f"Crossref HTTP {status}",
        )
    data = json.loads(body)
    return _parse_crossref_work(data["message"], "doi_exact", url, status)


def _title_overlap_ok(query_title: str, candidate_title: Optional[str]) -> bool:
    if not candidate_title:
        return False
    from difflib import SequenceMatcher

    na = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", query_title.lower()).strip()
    nb = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", candidate_title.lower()).strip()
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= 0.50


def fetch_crossref_by_title(title: str) -> GroundTruthRecord:
    q = urllib.parse.quote(title)
    url = f"https://api.crossref.org/works?query.bibliographic={q}&rows=3"
    try:
        status, body = _http_get(url)
    except Exception as exc:  # noqa: BLE001
        return GroundTruthRecord(
            found=False,
            source="Crossref",
            lookup_method="title_search",
            lookup_url=url,
            error=f"Network error: {exc}",
        )
    if status != 200:
        return GroundTruthRecord(
            found=False,
            source="Crossref",
            lookup_method="title_search",
            lookup_url=url,
            http_status=status,
            error=f"Crossref HTTP {status}",
        )
    items = (json.loads(body).get("message") or {}).get("items") or []
    for item in items:
        rec = _parse_crossref_work(item, "title_search", url, status)
        if _title_overlap_ok(title, rec.title):
            return rec
    return GroundTruthRecord(
        found=False,
        source="Crossref",
        lookup_method="title_search",
        lookup_url=url,
        http_status=status,
        error="No matching Crossref record for title query (low title similarity)",
    )


def fetch_arxiv(arxiv_id: Optional[str] = None, title: Optional[str] = None) -> GroundTruthRecord:
    if arxiv_id:
        clean_id = re.sub(r"v\d+$", "", arxiv_id.strip())
        url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(clean_id)}"
        method = "arxiv_id_exact"
    elif title:
        if any(ord(ch) > 127 for ch in title):
            return GroundTruthRecord(
                found=False,
                source="arXiv",
                lookup_method="arxiv_title_search",
                lookup_url="",
                http_status=None,
                error="Skipped arXiv title search for non-ASCII / Chinese title (out of arXiv scope)",
            )
        q = urllib.parse.quote(f'ti:"{title}"')
        url = f"https://export.arxiv.org/api/query?search_query={q}&max_results=3"
        method = "arxiv_title_search"
    else:
        return GroundTruthRecord(
            found=False,
            source="arXiv",
            lookup_method="none",
            lookup_url="",
            error="No arXiv ID or title provided",
        )

    try:
        status, body = _http_get(url)
    except Exception as exc:  # noqa: BLE001
        return GroundTruthRecord(
            found=False,
            source="arXiv",
            lookup_method=method,
            lookup_url=url,
            error=f"Network error: {exc}",
        )
    if status != 200:
        return GroundTruthRecord(
            found=False,
            source="arXiv",
            lookup_method=method,
            lookup_url=url,
            http_status=status,
            error=f"arXiv HTTP {status}",
        )

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(body)
    entries = root.findall("atom:entry", ns)
    if not entries:
        return GroundTruthRecord(
            found=False,
            source="arXiv",
            lookup_method=method,
            lookup_url=url,
            http_status=status,
            error="No entry returned by arXiv API",
        )
    entry = entries[0]
    title_el = entry.find("atom:title", ns)
    summary_el = entry.find("atom:summary", ns)
    published_el = entry.find("atom:published", ns)
    id_el = entry.find("atom:id", ns)
    entry_title = re.sub(r"\s+", " ", (title_el.text or "")).strip() if title_el is not None else None
    if not entry_title or entry_title.lower() == "error":
        return GroundTruthRecord(
            found=False,
            source="arXiv",
            lookup_method=method,
            lookup_url=url,
            http_status=status,
            error="arXiv returned error/empty entry",
        )

    authors = [
        (a.find("atom:name", ns).text or "").strip()
        for a in entry.findall("atom:author", ns)
        if a.find("atom:name", ns) is not None
    ]
    year = None
    if published_el is not None and published_el.text and len(published_el.text) >= 4:
        year = int(published_el.text[:4])
    abstract = re.sub(r"\s+", " ", (summary_el.text or "")).strip() if summary_el is not None else None
    resolved_arxiv = arxiv_id
    if id_el is not None and id_el.text:
        m = re.search(r"/abs/([^/]+)$", id_el.text.strip())
        if m:
            resolved_arxiv = m.group(1)

    return GroundTruthRecord(
        found=True,
        source="arXiv",
        lookup_method=method,
        lookup_url=url,
        http_status=status,
        title=entry_title,
        authors=authors,
        year=year,
        venue="arXiv preprint",
        arxiv_id=resolved_arxiv,
        abstract=abstract,
    )


def resolve_citation(
    citation: ParsedCitation,
    cache_map: Optional[Dict[str, Dict[str, Any]]] = None,
    offline_only: bool = False,
) -> GroundTruthRecord:
    """Resolve ground-truth metadata for a parsed citation."""
    if cache_map and citation.ref_id in cache_map:
        cached = GroundTruthRecord(**cache_map[citation.ref_id])
        err_str = cached.error or ""
        transient = (not cached.found) and (
            "Network error" in err_str or "429" in err_str
        )
        if offline_only or not transient:
            return cached

    if offline_only:
        return GroundTruthRecord(
            found=False,
            source="OfflineCache",
            lookup_method="cache_miss",
            lookup_url="",
            error="Offline mode enabled and citation not in snapshot cache",
        )

    # 1. Exact identifier priority: DOI -> arXiv ID
    if citation.doi:
        if citation.doi_syntax_valid is False:
            return GroundTruthRecord(
                found=False,
                source="DOI-SyntaxGate",
                lookup_method="syntax_check",
                lookup_url="",
                error=f"Invalid DOI syntax: {citation.doi}",
            )
        rec = fetch_crossref_by_doi(citation.doi)
        if rec.found:
            # Enrich missing abstract from arXiv if arXiv ID is also known or title matches
            if not rec.abstract and citation.arxiv_id:
                ax = fetch_arxiv(arxiv_id=citation.arxiv_id)
                if ax.found and ax.abstract:
                    rec.abstract = ax.abstract
            return rec
        # If DOI failed (404), do NOT silently replace with title search as verified —
        # record the failed DOI lookup explicitly so fabricated DOIs are caught!
        return rec

    if citation.arxiv_id:
        ax = fetch_arxiv(arxiv_id=citation.arxiv_id)
        if ax.found:
            return ax
        clean_id = re.sub(r"v\d+$", "", citation.arxiv_id.strip())
        oa = fetch_openalex_by_doi(f"10.48550/arXiv.{clean_id}")
        if oa.found:
            oa.arxiv_id = clean_id
            return oa
        return ax

    # 2. Title fallback when no identifier is present
    if citation.title and len(citation.title.strip()) >= 8:
        cr = fetch_crossref_by_title(citation.title)
        if cr.found and not cr.abstract:
            ax = fetch_arxiv(title=citation.title)
            if ax.found and ax.abstract and ax.title and cr.title:
                if ax.title.lower().strip() == cr.title.lower().strip():
                    cr.abstract = ax.abstract
        if cr.found:
            return cr
        return fetch_arxiv(title=citation.title)

    return GroundTruthRecord(
        found=False,
        source="None",
        lookup_method="insufficient_fields",
        lookup_url="",
        error="No DOI, arXiv ID, or searchable title extracted",
    )


def load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(path: Path, records: Dict[str, GroundTruthRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {k: vars(v) for k, v in records.items()}
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
