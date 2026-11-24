"""Bibliography and manuscript claim parser with syntax-only DOI validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# Crossref / ISO 26324 general DOI syntax: prefix 10.<registrant>/<suffix>
DOI_REGEX = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
ARXIV_REGEX = re.compile(
    r"(?:arXiv[:\s]*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)
YEAR_REGEX = re.compile(r"\b((?:19|20)\d{2})\b")
NUMBERED_LINE_REGEX = re.compile(r"^\s*\[(\d+)\]\s*(.+)$")
BIBTEX_ENTRY_REGEX = re.compile(
    r"@(\w+)\s*\{\s*([^,]+)\s*,(.+?)\n\}",
    re.DOTALL,
)


@dataclass
class ParsedCitation:
    """Normalized representation of a single bibliography entry."""

    ref_id: str
    raw_text: str
    format_detected: str
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    doi_syntax_valid: Optional[bool] = None
    arxiv_id: Optional[str] = None
    claim_text: Optional[str] = None
    parse_warnings: List[str] = field(default_factory=list)


def clean_doi(raw_doi: str) -> str:
    """Strip trailing punctuation commonly attached in prose/citations."""
    return raw_doi.strip().rstrip(".,;)]}\"'")


def validate_doi_syntax(doi: Optional[str]) -> Optional[bool]:
    """Validate DOI syntax separately from existence in any registry."""
    if not doi:
        return None
    cleaned = clean_doi(doi)
    if not re.fullmatch(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", cleaned):
        return False
    prefix, suffix = cleaned.split("/", 1)
    registrant = prefix.split(".", 1)[1]
    if not registrant.isdigit() or len(suffix) < 2:
        return False
    return True


def _extract_bibtex_field(body: str, field_name: str) -> Optional[str]:
    pattern = re.compile(
        rf"\b{field_name}\s*=\s*(?:\{{([^{{}}]*(?:\{{[^{{}}]*\}}[^{{}}]*)*)\}}|\"([^\"]*)\"|(\d+))",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(body)
    if not m:
        return None
    val = m.group(1) or m.group(2) or m.group(3) or ""
    val = re.sub(r"\s+", " ", val).replace("{", "").replace("}", "").strip()
    return val or None


def parse_bibtex_entries(text: str) -> List[ParsedCitation]:
    """Parse BibTeX entries into ParsedCitation objects."""
    results: List[ParsedCitation] = []
    for idx, match in enumerate(BIBTEX_ENTRY_REGEX.finditer(text), start=1):
        entry_type, key, body = match.group(1), match.group(2).strip(), match.group(3)
        title = _extract_bibtex_field(body, "title")
        author_raw = _extract_bibtex_field(body, "author")
        year_raw = _extract_bibtex_field(body, "year")
        venue = (
            _extract_bibtex_field(body, "booktitle")
            or _extract_bibtex_field(body, "journal")
            or _extract_bibtex_field(body, "publisher")
        )
        doi_raw = _extract_bibtex_field(body, "doi")
        eprint = _extract_bibtex_field(body, "eprint")
        url_raw = _extract_bibtex_field(body, "url")

        doi = clean_doi(doi_raw) if doi_raw else None
        if not doi and url_raw:
            dm = DOI_REGEX.search(url_raw)
            if dm:
                doi = clean_doi(dm.group(1))

        arxiv_id = None
        for candidate in (eprint, url_raw, body):
            if candidate:
                am = ARXIV_REGEX.search(candidate)
                if am:
                    arxiv_id = am.group(1)
                    break
        if not arxiv_id and eprint and re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", eprint.strip()):
            arxiv_id = eprint.strip()

        authors = (
            [a.strip() for a in re.split(r"\s+and\s+", author_raw) if a.strip()]
            if author_raw
            else []
        )
        year = int(year_raw) if year_raw and year_raw.isdigit() else None
        results.append(
            ParsedCitation(
                ref_id=key or f"ref-{idx}",
                raw_text=match.group(0).strip(),
                format_detected=f"BibTeX (@{entry_type})",
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                doi=doi,
                doi_syntax_valid=validate_doi_syntax(doi),
                arxiv_id=arxiv_id,
            )
        )
    return results


def _split_authors_and_title(text: str) -> tuple[List[str], Optional[str], Optional[str]]:
    """Heuristic extraction for GB/T 7714, APA, and plain-text entries."""
    # Remove leading [1] or 1.
    cleaned = re.sub(r"^\s*(?:\[\d+\]|\d+\.)\s*", "", text).strip()
    # Remove trailing DOI / URL / arXiv tags before segmenting
    core = re.sub(r"https?://\S+", "", cleaned)
    core = re.sub(r"doi:\s*\S+", "", core, flags=re.IGNORECASE).strip()

    # Check quoted title first: "Title" or “Title”
    qm = re.search(r"[\"“]([^\"”]{8,})[\"”]", core)
    if qm:
        title = qm.group(1).strip().rstrip(".,")
        prefix = core[: qm.start()].strip(" .,;")
        suffix = core[qm.end() :].strip(" .,;")
        authors_part = re.sub(r"\(\d{4}\)", "", prefix).strip(" .,;")
        authors = [a.strip() for a in re.split(r"[,;、]| and ", authors_part) if a.strip()]
        return authors[:8], title, suffix or None

    # GB/T 7714 style: Author. Title[C]//Venue. Year... or Author. Title[J]. Venue, Year...
    gb = re.match(
        r"^([^.]+?)\.\s*([^.\[]+?)\s*\[[A-Z/]+\](?://[^.]+)?\.\s*(.*)$",
        core,
    )
    if gb:
        authors_part, title_part, rest = gb.group(1), gb.group(2), gb.group(3)
        authors = [a.strip() for a in re.split(r"[,;、]| and ", authors_part) if a.strip()]
        return authors[:8], title_part.strip(), rest.strip() or None

    # APA style: Author, A. (2020). Title. Venue.
    apa = re.match(r"^(.+?)\((?:19|20)\d{2}[a-z]?\)\.\s*([^.]+)\.\s*(.*)$", core)
    if apa:
        authors_part, title_part, rest = apa.group(1), apa.group(2), apa.group(3)
        authors = [a.strip() for a in re.split(r";|&| and ", authors_part) if a.strip()]
        return authors[:8], title_part.strip(), rest.strip() or None

    # Fallback: split by periods
    parts = [p.strip() for p in core.split(".") if len(p.strip()) > 3]
    if len(parts) >= 2:
        authors = [a.strip() for a in re.split(r"[,;、]| and ", parts[0]) if a.strip()]
        return authors[:8], parts[1], ". ".join(parts[2:]) or None
    return [], core or None, None


def parse_plain_line(line: str, ref_id: str) -> ParsedCitation:
    """Parse a single plain-text / GB/T 7714 / APA citation line."""
    doi_match = DOI_REGEX.search(line)
    doi = clean_doi(doi_match.group(1)) if doi_match else None
    arxiv_match = ARXIV_REGEX.search(line)
    arxiv_id = arxiv_match.group(1) if arxiv_match else None
    # Strip identifiers/URLs before extracting publication year (avoid matching arXiv:2005.11401 as year 2005)
    line_for_year = re.sub(r"https?://\S+|doi:\s*\S+|arXiv[:\s]*\d{4}\.\d{4,5}(?:v\d+)?", "", line, flags=re.IGNORECASE)
    year_matches = YEAR_REGEX.findall(line_for_year)
    year = int(year_matches[-1]) if year_matches else None

    if "[" in line and ("]" in line) and re.search(r"\[[JCMDBPR]/[A-Z]+\]|\[[JCMDBPR]\]", line):
        fmt = "GB/T 7714"
    elif re.search(r"\((?:19|20)\d{2}[a-z]?\)\.", line):
        fmt = "APA"
    elif NUMBERED_LINE_REGEX.match(line):
        fmt = "Numbered Reference"
    else:
        fmt = "Plain Citation"

    authors, title, venue = _split_authors_and_title(line)
    warnings: List[str] = []
    if not doi and "10." in line:
        warnings.append("Detected '10.' substring that failed strict DOI syntax match")
    if doi and validate_doi_syntax(doi) is False:
        warnings.append(f"Invalid DOI syntax: {doi}")

    return ParsedCitation(
        ref_id=ref_id,
        raw_text=line.strip(),
        format_detected=fmt,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        doi_syntax_valid=validate_doi_syntax(doi),
        arxiv_id=arxiv_id,
        parse_warnings=warnings,
    )


def parse_references(text: str, claims_by_ref: Optional[dict[str, str]] = None) -> List[ParsedCitation]:
    """Parse BibTeX or line-separated citations and attach optional claims."""
    claims = claims_by_ref or {}
    if "@" in text and BIBTEX_ENTRY_REGEX.search(text):
        entries = parse_bibtex_entries(text)
    else:
        entries = []
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for idx, line in enumerate(lines, start=1):
            num_m = NUMBERED_LINE_REGEX.match(line)
            ref_id = num_m.group(1) if num_m else str(idx)
            entries.append(parse_plain_line(line, ref_id=ref_id))

    for entry in entries:
        if entry.ref_id in claims:
            entry.claim_text = claims[entry.ref_id]
    return entries
