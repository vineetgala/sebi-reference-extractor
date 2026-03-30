"""URL resolution for SEBI-referenced documents.

Attempts to find a sebi.gov.in page URL for each referenced document produced
by the extractor, using SEBI's internal listing API.

Resolution strategy by type
───────────────────────────
  act              → search acts listing (ssid=1); title keyword match
  regulations      → search regulations listing (ssid=3); parenthetical keyword match;
                     skip amendment / corrigendum entries
  master_circular  → search master-circular listing (ssid=6); title keyword match + date filter
  circular         → search circulars listing (ssid=7); date-exact filter first, then title;
                     if only one result on that date, accept as probable match
  notification     → not resolvable (date-only, no identifier); always returns unresolved

Resolution status values
────────────────────────
  resolved          high-confidence exact or near-exact title match (score ≥ 0.60)
  resolved_approx   low-confidence: single result on the right date, or weak title match
  unresolved        no match found or type not resolvable
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from extract_references import DocumentRecord


# ─── SEBI API ──────────────────────────────────────────────────────────────

_API = "https://www.sebi.gov.in/sebiweb/ajax/home/getnewslistinfo.jsp"
_BASE = "https://www.sebi.gov.in"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SEBI-Reference-Extractor/1.0)",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Legal section = sid 1; category ssids within it
_SSID = {
    "act":             "1",
    "regulations":     "3",
    "master_circular": "6",
    "circular":        "7",
}

# Short sleep between API calls to be polite
_RATE_SLEEP = 0.4   # seconds


# ─── MONTHS ────────────────────────────────────────────────────────────────

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "oct": "10", "october": "10",
    "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "nov": "11", "dec": "12",
}


def _parse_date_ddmmyyyy(date_str: str | None) -> str | None:
    """Convert 'August 27, 2013' or '27 Aug 2013' → '27-08-2013' for the API."""
    if not date_str:
        return None
    # "Month DD, YYYY"
    m = re.match(
        r"(\w+)\s+(\d{1,2}),\s*(\d{4})",
        date_str.strip(),
        re.IGNORECASE,
    )
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            return f"{int(m.group(2)):02d}-{mon}-{m.group(3)}"
    # "DD Month YYYY" or "DD Mon YYYY"
    m = re.match(
        r"(\d{1,2})\s+(\w+)\s+(\d{4})",
        date_str.strip(),
        re.IGNORECASE,
    )
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            return f"{int(m.group(1)):02d}-{mon}-{m.group(3)}"
    return None


# ─── SEBI LISTING API ──────────────────────────────────────────────────────

def _sebi_search(
    query: str,
    ssid: str,
    from_date: str | None = None,
    to_date: str | None = None,
    max_pages: int = 3,
) -> list[dict]:
    """
    Call SEBI's listing AJAX endpoint.

    Returns a list of {title, url} dicts, newest first.
    Never raises — returns [] on any network or parse error.
    """
    results: list[dict] = []
    next_value = 1
    seen_urls: set[str] = set()

    for _ in range(max_pages):
        params = {
            "nextValue": str(next_value),
            "next": "1",
            "search": query,
            "fromDate": from_date or "",
            "toDate": to_date or "",
            "sid": "1",
            "ssid": ssid,
            "smid": "0",
            "doDirect": "0",
        }
        body = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(_API, data=body, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", "ignore").split("#@#")[0]
        except (urllib.error.URLError, OSError):
            break

        rows = re.findall(
            r"href='(https://[^']+\.html)'\s+[^>]*title=\"([^\"]+)\"",
            html,
        )
        for url, title in rows:
            if url not in seen_urls:
                seen_urls.add(url)
                results.append({"title": title.strip(), "url": url})

        # Advance pagination
        nv_m = re.search(r"name='nextValue' value=(\d+)", html)
        next_value = int(nv_m.group(1)) if nv_m else 0
        if next_value == 0:
            break
        time.sleep(_RATE_SLEEP)

    return results


# ─── TITLE MATCHING ────────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "a an the and or of in on to for by with as at from its their under "
    "dated issued pursuant read also such other further etc sebi".split()
)

_SKIP_PREFIXES = (
    "amendment to", "amendment in", "corrigendum to", "corrigendum in",
    "addendum to", "notification under", "notifications under",
)


def _normalize(text: str) -> set[str]:
    """Lower, strip punctuation, remove stop words, return word set."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return {w for w in text.split() if w and w not in _STOP_WORDS and len(w) > 1}


def _title_score(candidate: str, target: str) -> float:
    """Jaccard-style word overlap score between two title strings."""
    a = _normalize(candidate)
    b = _normalize(target)
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def _is_amendment(title: str) -> bool:
    low = title.lower()
    return any(low.startswith(p) for p in _SKIP_PREFIXES)


def _best_match(
    results: list[dict],
    target_title: str,
    threshold: float,
    skip_amendments: bool = True,
) -> tuple[dict | None, float]:
    """Return (best_result, score) or (None, 0)."""
    best, best_score = None, 0.0
    for item in results:
        if skip_amendments and _is_amendment(item["title"]):
            continue
        score = _title_score(item["title"], target_title)
        if score > best_score:
            best, best_score = item, score
    if best_score >= threshold:
        return best, best_score
    return None, 0.0


# ─── KEYWORD EXTRACTION ────────────────────────────────────────────────────

def _search_keywords(record: "DocumentRecord") -> str:
    """
    Derive a short search query from the record for use with the SEBI listing API.
    Returns a string of the most distinctive keywords.
    """
    title = record.title or record.short_title or ""

    if record.document_type == "regulations":
        # "SEBI (Custodian) Regulations, 1996" → "Custodian"
        # "Securities and Exchange Board of India (RTA) Regulations, 2025" → "RTA"
        m = re.search(r"\(([^)]+)\)", title)
        if m:
            return m.group(1).strip()
        return re.sub(r"\b(SEBI|regulations?|securities|exchange|board|india)\b", "", title, flags=re.I).strip()

    if record.document_type == "master_circular":
        # "Master Circular for Registrars to an Issue and Share Transfer Agents" → "Registrars Issue Share Transfer"
        m = re.match(r"(?:SEBI'?s?\s+)?Master\s+Circular\s+(?:for\s+)?(.+)", title, re.I)
        core = m.group(1) if m else title
        # Take first 5 significant words
        words = [w for w in core.split() if w.lower() not in _STOP_WORDS][:5]
        return " ".join(words)

    if record.document_type == "act":
        # Strip year and amendment suffixes
        cleaned = re.sub(r",\s*(19|20)\d{2}.*", "", title).strip()
        return cleaned

    if record.document_type == "circular":
        # Last resort: identifier only (often not searchable, but worth trying)
        return record.identifier or ""

    return title


# ─── PER-TYPE RESOLUTION ───────────────────────────────────────────────────

def _resolve_act(record: "DocumentRecord") -> tuple[str | None, str]:
    query = _search_keywords(record)
    if not query:
        return None, "unresolved"
    results = _sebi_search(query, ssid=_SSID["act"], max_pages=2)
    # Acts listing is small; only accept /legal/acts/ URLs
    acts_results = [r for r in results if "/legal/acts/" in r["url"]]
    item, score = _best_match(acts_results, record.title or query, threshold=0.35)
    if item:
        status = "resolved" if score >= 0.55 else "resolved_approx"
        return item["url"], status
    return None, "unresolved"


def _resolve_regulations(record: "DocumentRecord") -> tuple[str | None, str]:
    query = _search_keywords(record)
    if not query:
        return None, "unresolved"
    results = _sebi_search(query, ssid=_SSID["regulations"], max_pages=3)
    regs_results = [r for r in results if "/legal/regulations/" in r["url"]]
    item, score = _best_match(regs_results, record.title or query, threshold=0.35)
    if item:
        status = "resolved" if score >= 0.55 else "resolved_approx"
        return item["url"], status
    return None, "unresolved"


def _resolve_master_circular(record: "DocumentRecord") -> tuple[str | None, str]:
    query = _search_keywords(record)
    if not query:
        return None, "unresolved"
    date_str = _parse_date_ddmmyyyy(record.date)
    results = _sebi_search(
        query,
        ssid=_SSID["master_circular"],
        from_date=date_str,
        to_date=date_str,
        max_pages=1,
    )
    if not results and date_str:
        # Relax — try without date
        results = _sebi_search(query, ssid=_SSID["master_circular"], max_pages=2)
    mc_results = [r for r in results if "/legal/master-circulars/" in r["url"]]
    item, score = _best_match(mc_results, record.title or query, threshold=0.3)
    if item:
        status = "resolved" if score >= 0.50 else "resolved_approx"
        return item["url"], status
    return None, "unresolved"


def _resolve_circular(record: "DocumentRecord") -> tuple[str | None, str]:
    date_str = _parse_date_ddmmyyyy(record.date)
    circ_results: list[dict] = []

    # 1. Try exact date filter — if only one result, it's almost certainly correct
    if date_str:
        date_results = _sebi_search(
            "",
            ssid=_SSID["circular"],
            from_date=date_str,
            to_date=date_str,
            max_pages=1,
        )
        circ_results = [r for r in date_results if "/legal/circulars/" in r["url"]]
        if len(circ_results) == 1:
            return circ_results[0]["url"], "resolved_approx"

    # 2. Keyword search (works well if we have a title or short_title)
    query = _search_keywords(record)
    if query:
        kw_results = _sebi_search(
            query,
            ssid=_SSID["circular"],
            from_date=date_str,
            to_date=date_str,
            max_pages=2,
        )
        kw_circ = [r for r in kw_results if "/legal/circulars/" in r["url"]]
        if kw_circ:
            target = record.title or record.short_title or query
            item, score = _best_match(kw_circ, target, threshold=0.3)
            if item:
                status = "resolved" if score >= 0.50 else "resolved_approx"
                return item["url"], status

    # 3. Fallback: multiple results on same date → return first, mark approx
    if len(circ_results) > 1:
        target = record.title or query
        if target:
            item, score = _best_match(circ_results, target, threshold=0.2)
            if item:
                return item["url"], "resolved_approx"

    return None, "unresolved"


# ─── PUBLIC INTERFACE ───────────────────────────────────────────────────────

def resolve_one(record: "DocumentRecord") -> tuple[str | None, str]:
    """
    Attempt to resolve a URL for a single record.

    Returns (resolved_url, resolution_status).
    Never raises.
    """
    if record.document_type == "act":
        return _resolve_act(record)
    if record.document_type == "regulations":
        return _resolve_regulations(record)
    if record.document_type == "master_circular":
        return _resolve_master_circular(record)
    if record.document_type == "circular":
        return _resolve_circular(record)
    # notifications and others: not resolvable
    return None, "unresolved"


def resolve_document_urls(records: list["DocumentRecord"]) -> dict:
    """
    Attempt URL resolution for every record in the list.
    Modifies records in-place: sets resolved_url and resolution_status.

    Returns a summary:
        {resolved: N, resolved_approx: N, unresolved: N}
    """
    counts: dict[str, int] = {"resolved": 0, "resolved_approx": 0, "unresolved": 0}
    for record in records:
        if record.resolution_status not in {"unresolved"}:
            continue  # already resolved from a previous run
        url, status = resolve_one(record)
        record.resolved_url = url
        record.resolution_status = status
        counts[status] = counts.get(status, 0) + 1
        time.sleep(_RATE_SLEEP)
    return counts
