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
    return "", " ".join(tokens)


def _tidy_company(name: str) -> str:
    name = name.strip(" -–:")
    if name.isupper():
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


def parse_jobs(text: str) -> dict | None:
    """``{"jobs": [...], "more_url": str}`` for a TalentConnect digest, else None."""
    if "nus-talentconnect.app.kinobi.asia/jobs" not in text:
        return None
    links = [m for m in JOB_LINK.finditer(text) if _SLUG.search(m.group(1))]
    if not links:
        return None
    more = MORE_LINK.search(text)
    end_of_list = more.start() if more else len(text)

    jobs: list[dict] = []
    names: list[tuple[int, int]] = []  # where each job's name starts / its link ends
    for index, match in enumerate(links[:MAX_JOBS]):
        url = match.group(1)
        slug_words = _words(_SLUG.search(url).group("words"))
        start = links[index - 1].end() if index else 0
        span = text[start:match.start()]
        tokens = _name_tokens(span, slug_words)
        company, title = _split_company_title(tokens, slug_words)
        name_text = " ".join(tokens)
        name_start = span.rfind(tokens[0]) + start if tokens else match.start()
        names.append((name_start, match.end()))
        jobs.append({
            "id": url.rsplit("/", 1)[-1].split("-", 1)[0],
            "url": url,
            "title": title or name_text or "Job",
            "company": _tidy_company(company),
        })

    for index, job in enumerate(jobs):
        details_end = names[index + 1][0] if index + 1 < len(jobs) else end_of_list
        job.update(_details(text[names[index][1]:details_end][:600]))

    return {"jobs": jobs, "more_url": more.group(1) if more else ""}
