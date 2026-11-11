"""Job digests (NUS TalentConnect) -> a list of jobs a student can scan and open.

A digest arrives as one long run of text in which every posting looks like::

    [logo] Singapore General Hospital Research Intern<https://nus-talentconnect
    .app.kinobi.asia/jobs/1793848831156-6aebf5...-research-intern-singapore-general
    -hospital-sg> Easy Apply Internship Programme Singapore Remote - Internship
    Academic Year 2026/2027 Semester 2 (Dec '26 - May/Jun '27) ... SGD 1000 - 1200 (Monthly)

The text before the link mixes company and title. The link's last part spells
the same words in a fixed order (title, then company), so it tells where one
ends and the other begins. The text after the link holds the details.

Only TalentConnect is understood; other mail returns ``None``.
"""

from __future__ import annotations

import re

JOB_LINK = re.compile(r"<(https://nus-talentconnect\.app\.kinobi\.asia/jobs/[^>\s]+)>")
LINK_ADDRESS = re.compile(r"<https?://[^>\s]+>")
MORE_LINK = re.compile(r"view\s+more\s+jobs\s*<(https?://[^>\s]+)>", re.IGNORECASE)
MAX_JOBS = 30

_SLUG = re.compile(r"/jobs/\d+-[0-9a-f]+-(?P<words>[a-z0-9-]+)", re.IGNORECASE)
_TYPES = (
    (r"\bfull[\s-]*time\b", "Full time"),
    (r"\bpart[\s-]*time\b", "Part time"),
    (r"\binternship\b", "Internship"),
    (r"\bcontract\b", "Contract"),
)
_MODES = (
    (r"\bremote\b", "Remote"),
    (r"\bhybrid\b", "Hybrid"),
    (r"\bwork\s+from\s+office\b|\bon[\s-]*site\b", "Office"),
)
_PERIOD = re.compile(r"\(([A-Z][a-z]{2}\s*'\d{2}\s*[-–]\s*[A-Za-z/]+\s*'\d{2})\)")
_PAY = re.compile(
    r"\b(SGD|S\$|USD)\s*([\d,]+)\s*(?:[-–]\s*([\d,]+))?\s*\((monthly|hourly|yearly|annually|weekly)\)",
    re.IGNORECASE,
)
_PROGRAMME = re.compile(r"\((UPIP|SIP|[A-Z]{2,5}\d{4}[A-Z]?)\)|\b([A-Z]{2,4}\d{4}[A-Z]?)\b")


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


# Words a company name carries that the link may leave out or cut short.
_CORP_WORDS = {"pte", "ltd", "llp", "llc", "inc", "co", "corp", "limited", "the", "of", "and", "sg"}


def _in_link(word: str, slug_words: list[str]) -> bool:
    """The link spells this word, or cuts it short at its end ("pte" -> "pt")."""
    return word in slug_words or word in _CORP_WORDS or (
        bool(slug_words) and word.startswith(slug_words[-1])
    )


def _name_tokens(span: str, slug_words: list[str]) -> list[str]:
    """The run of words at the end of ``span`` that the link spells (company + title)."""
    tokens = span.replace("[logo]", " ").split()
    start = len(tokens)
    while start > 0:
        words = _words(tokens[start - 1])
        if words and not all(_in_link(word, slug_words) for word in words):
            break
        start -= 1
    return tokens[start:]


def _split_company_title(tokens: list[str], slug_words: list[str]) -> tuple[str, str]:
    """Find k where tokens[k:] (the title) is how the link starts and the rest
    of the link names the company (tokens[:k])."""
    slug = "-".join(slug_words)
    for k in range(1, len(tokens)):
        title = "-".join(_words(" ".join(tokens[k:])))
        if not title or not slug.startswith(title):
            continue
        rest_words = slug[len(title):].strip("-").split("-")
        company_words = _words(" ".join(tokens[:k]))
        if company_words and all(_in_link(word, rest_words) for word in company_words):
            return " ".join(tokens[:k]), " ".join(tokens[k:])
    # Some layouts put the title first: "Channel Manager OPPO" (longest title first).
    for k in range(len(tokens) - 1, 0, -1):
        title = "-".join(_words(" ".join(tokens[:k])))
        if not title or not slug.startswith(title):
            continue
        rest_words = slug[len(title):].strip("-").split("-")
        company_words = _words(" ".join(tokens[k:]))
        if company_words and all(_in_link(word, rest_words) for word in company_words):
            return " ".join(tokens[k:]), " ".join(tokens[:k])
    return "", " ".join(tokens)


def _tidy_company(name: str) -> str:
    name = name.strip(" -–:")
    if name.isupper() and len(name.split()) > 1:  # "ASTER CHEMICALS ..." but not "OPPO"
        name = name.title()
        name = re.sub(r"\b(And|Of|The|For|In)\b", lambda m: m.group(1).lower(), name)
        name = name[:1].upper() + name[1:]
    return name


def _details(text: str) -> dict:
    found = {
        "easy_apply": bool(re.search(r"\beasy\s+apply\b", text, re.IGNORECASE)),
        "type": next((label for pattern, label in _TYPES if re.search(pattern, text, re.IGNORECASE)), ""),
        "mode": next((label for pattern, label in _MODES if re.search(pattern, text, re.IGNORECASE)), ""),
        "location": "Singapore" if re.search(r"\bsingapore\b", text, re.IGNORECASE) else "",
        "period": "",
        "pay": "",
        "programme": "",
    }
    if period := _PERIOD.search(text):
        found["period"] = re.sub(r"\s+", " ", period.group(1))
    if pay := _PAY.search(text):
        low = int(pay.group(2).replace(",", ""))
        high = int((pay.group(3) or pay.group(2)).replace(",", ""))
        unit = {"monthly": "mo", "hourly": "hr", "weekly": "wk"}.get(pay.group(4).lower(), "yr")
        amount = f"{low:,}" if low == high else f"{low:,}–{high:,}"
        found["pay"] = f"SGD {amount}/{unit}" if pay.group(1).upper() in ("SGD", "S$") else f"{pay.group(1).upper()} {amount}/{unit}"
        found["paid"] = high > 0
    if programme := _PROGRAMME.search(text):
        found["programme"] = programme.group(1) or programme.group(2) or ""
    return found


_GENERIC_LABELS = {"apply", "apply now", "easy apply", "view", "view job", "view details", "details", "learn more"}
_DETAIL_WORDS = re.compile(
    r"\b(?:easy\s+apply|remote|hybrid|work\s+from\s+office|full[\s-]*time|part[\s-]*time|"
    r"academic\s+year|semester|sgd|monthly)\b",
    re.IGNORECASE,
)


def _clean_label(span: str) -> str:
    return " ".join(LINK_ADDRESS.sub(" ", span).replace("[logo]", " ").split()).strip(" -–|·")


def _prefix_score(label: str, slug_words: list[str]) -> int:
    """How many words of the link address this label spells from its start."""
    count = 0
    for word, slug_word in zip(_words(label), slug_words):
        if word != slug_word:
            break
        count += 1
    return count


def _from_labels(text: str, group: list[re.Match], slug_words: list[str]) -> tuple[str, str]:
    """(company, title) from the clean labels between a job's own links."""
    labels: list[str] = []
    for previous, match in zip(group, group[1:]):
        label = _clean_label(text[previous.end():match.start()])
        if (
            label
            and label.lower() not in _GENERIC_LABELS
            and len(label) <= 160
            and not _DETAIL_WORDS.search(label)
            and label not in labels
        ):
            labels.append(label)
    if not labels:
        return "", ""
    title = max(labels, key=lambda label: _prefix_score(label, slug_words))
    if _prefix_score(title, slug_words) == 0:
        return "", ""
    others = [label for label in labels if label != title]
    return (others[0] if others else ""), title


def _title_from_slug(slug_words: list[str]) -> str:
    """Last resort: the link's words, e.g. "Data Analyst Acme Sg" -> "Data analyst acme"."""
    words = slug_words[:-1] if len(slug_words) > 1 else slug_words
    text = " ".join(words)
    return text[:1].upper() + text[1:] if text else "Job"


def _job_id(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("-", 1)[0]


# Only "new jobs posted" and "jobs alert" digests become job cards ("4 new job(s) has been
# posted!", subject "New Jobs Posted"); other TalentConnect mail stays mail.
NEW_JOBS = re.compile(
    r"\bnew\s+job(?:\(s\)|s)?\b[^\n]{0,40}?\bposted\b|\bjobs?\s+alerts?\b", re.IGNORECASE
)


def is_new_jobs_digest(subject: str, text: str) -> bool:
    return bool(NEW_JOBS.search(subject or "") or NEW_JOBS.search((text or "")[:1500]))


def parse_jobs(text: str, subject: str = "") -> dict | None:
    """``{"jobs": [...], "more_url": str}`` for a TalentConnect digest, else None.

    In the HTML email one job usually has several links to the same page (the
    logo, the company name, the title, an Apply button). Links are grouped by
    job id: their labels together give company and title, and the details are
    read from the text up to the next job.
    """
    if "nus-talentconnect.app.kinobi.asia/jobs" not in text or not is_new_jobs_digest(subject, text):
        return None
    links = [m for m in JOB_LINK.finditer(text) if _SLUG.search(m.group(1))]
    if not links:
        return None
    more = MORE_LINK.search(text)
    end_of_list = more.start() if more else len(text)

    # Group consecutive links that point at the same job.
    groups: list[list[re.Match]] = []
    for match in links:
        if groups and _job_id(groups[-1][0].group(1)) == _job_id(match.group(1)):
            groups[-1].append(match)
        else:
            groups.append([match])

    jobs: list[dict] = []
    bounds: list[tuple[int, int]] = []  # (where the job's name starts, where its first link ends)
    previous_end = 0
    for group in groups[:MAX_JOBS]:
        url = group[0].group(1)
        slug_words = _words(_SLUG.search(url).group("words"))
        tokens: list[str] = []
        name_start = group[0].start()
        company = title = ""
        span_start = previous_end
        for match in group:
            found = _name_tokens(text[span_start:match.start()], slug_words)
            if found and found != tokens[-len(found):]:
                if not tokens:
                    span = text[span_start:match.start()]
                    name_start = span_start + span.rfind(found[0])
                tokens += found
            span_start = match.end()
            covered = {word for token in tokens for word in _words(token)}
            # Stop once the name spells the whole link (its last word may be a
            # country code or cut short); later links (logo, Apply) add nothing.
            if all(word in covered for word in slug_words[:-1] if word != "copy"):
                break
        company, title = _split_company_title(tokens, slug_words)
        # Labels of the later links in the group are clean (just the company
        # or just the title) and may spell the company differently from the
        # link ("EY" vs "Ernst & Young LLP"); prefer them when they exist.
        label_company, label_title = _from_labels(text, group, slug_words)
        if label_title:
            title = label_title
            company = label_company or (company if company != label_title else "")
        if not title:
            title = _title_from_slug(slug_words)
        previous_end = group[-1].end()
        bounds.append((name_start, group[0].end()))
        jobs.append({
            "id": _job_id(url),
            "url": url,
            "title": title,
            "company": _tidy_company(company),
        })

    for index, job in enumerate(jobs):
        details_end = bounds[index + 1][0] if index + 1 < len(jobs) else end_of_list
        details = LINK_ADDRESS.sub(" ", text[bounds[index][1]:details_end])
        job.update(_details(details[:800]))

    return {"jobs": jobs, "more_url": more.group(1) if more else ""}
