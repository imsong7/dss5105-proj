from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from generate_replies import placeholders_in

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "eval_cases.json"
DEFAULT_DRAFTS = HERE / "drafts" / "drafts.json"
AI_PHRASES = ("as an ai", "as a language model", "ai assistant", "i am an ai", "i'm an ai")
ADDRESS_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cases") or data.get("messages") or []
    return [item for item in data if item.get("eval")]


def load_drafts(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("drafts", []) if isinstance(data, dict) else data
    index = {}
    for record in records:
        for key in ("id", "internet_message_id", "subject"):
            value = record.get(key)
            if value:
                index[str(value)] = record
    return index


def find_draft(case: dict, drafts: dict[str, dict]) -> dict | None:
    for key in ("id", "internetMessageId", "subject"):
        value = case.get(key)
        if value and str(value) in drafts:
            return drafts[str(value)]
    return None


def incoming_addresses(case: dict) -> set[str]:
    addresses = set()
    sender = ((case.get("from") or {}).get("emailAddress") or {}).get("address")
    if sender:
        addresses.add(str(sender).lower())
    body = (case.get("body") or {}).get("content") or ""
    addresses.update(address.lower() for address in ADDRESS_RE.findall(body))
    return addresses


def reply_body(reply: str) -> str:
    match = re.search(r"(?i)\bPlaceholders:\s*", reply)
    body = reply[: match.start()] if match else reply
    signoff = re.split(
        r"\n\s*(?:(?:best|kind|warm)\s+)?regards,?\s*\n|\n\s*(?:best|sincerely|yours sincerely),?\s*\n",
        body,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    return signoff[0]


def sentence_count(reply: str) -> int:
    parts = re.split(r"(?<=[.!?])\s+", reply_body(reply).strip())
    return len([part for part in parts if re.search(r"[A-Za-z0-9]", part)])


def evaluate_reply(case: dict, reply: str) -> list[str]:
    if not reply.strip():
        return ["reply is empty"]

    issues = []
    lower = reply.lower()
    meta = case["eval"]

    for phrase in meta.get("must_include", []):
        if phrase.lower() not in lower:
            issues.append(f"missing key fact: {phrase}")

    for group in meta.get("must_include_any", []):
        if not any(phrase.lower() in lower for phrase in group):
            issues.append("missing one of: " + ", ".join(group))

    for phrase in meta.get("must_not_include", []):
        if phrase.lower() in lower:
            issues.append(f"contains banned phrase: {phrase}")

    for address in sorted(incoming_addresses(case)):
        if address in lower:
            issues.append(f"copies raw email address: {address}")

    for phrase in AI_PHRASES:
        if phrase in lower:
            issues.append(f"mentions AI/assistant phrase: {phrase}")

    placeholder_match = re.search(r"(?i)\bPlaceholders:\s*", reply)
    if placeholder_match:
        body = reply[: placeholder_match.start()]
        listing = reply[placeholder_match.end() :]
        body_placeholders = {item.lower() for item in placeholders_in(body)}
        listed = {item.lower() for item in placeholders_in(listing)}
        for placeholder in sorted(body_placeholders):
            if body.lower().count(placeholder) > 1:
                issues.append(f"placeholder appears more than once: {placeholder}")
        for placeholder in sorted(body_placeholders - listed):
            issues.append(f"placeholder is not listed: {placeholder}")
        for placeholder in sorted(listed - body_placeholders):
            issues.append(f"listed placeholder is not in the reply: {placeholder}")
    else:
        body_placeholders = {item.lower() for item in placeholders_in(reply)}
        for placeholder in sorted(body_placeholders):
            if reply.lower().count(placeholder) > 1:
                issues.append(f"placeholder appears more than once: {placeholder}")
            issues.append(f"placeholder is not listed: {placeholder}")

    if meta.get("requires_placeholder") and not body_placeholders:
        issues.append("expected a placeholder for missing details")

    max_sentences = meta.get("max_sentences")
    if max_sentences and sentence_count(reply) > max_sentences:
        issues.append(f"too many sentences: {sentence_count(reply)} > {max_sentences}")

    return issues


def evaluate_cases(cases: list[dict], replies: dict[str, str]) -> list[dict]:
    results = []
    for case in cases:
        reply = replies.get(str(case.get("id")), "")
        issues = evaluate_reply(case, reply)
        results.append(
            {
                "id": case.get("id"),
                "type": case["eval"].get("type", ""),
                "issues": issues,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate reply drafts against offline rubric cases (no API).")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to eval_cases.json")
    parser.add_argument("--drafts", default=str(DEFAULT_DRAFTS), help="Path to drafts.json")
    parser.add_argument("--use-ideal", action="store_true", help="Validate the eval rubric using ideal replies")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    if not cases:
        print(f"No eval cases found in {args.cases}", file=sys.stderr)
        return 2

    if args.use_ideal:
        replies = {str(case["id"]): case["eval"].get("ideal_reply", "") for case in cases}
    else:
        drafts_path = Path(args.drafts)
        if not drafts_path.exists():
            print(f"No drafts found at {drafts_path}; generate drafts first or use --use-ideal", file=sys.stderr)
            return 2
        drafts = load_drafts(drafts_path)
        replies = {}
        for case in cases:
            record = find_draft(case, drafts)
            if record:
                replies[str(case["id"])] = record.get("reply", "")

    results = evaluate_cases(cases, replies)
    failed = [result for result in results if result["issues"]]

    if args.json:
        print(json.dumps({"results": results, "passed": len(results) - len(failed), "failed": len(failed)}, indent=2))
    else:
        for result in results:
            status = "FAIL" if result["issues"] else "PASS"
            print(f"[{status}] {result['id']} ({result['type']})")
            for issue in result["issues"]:
                print(f"  - {issue}")
        print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed, {len(results)} total")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
