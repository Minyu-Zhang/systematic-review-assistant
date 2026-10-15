"""Cheap extraction alarms, not measures of semantic accuracy."""

from collections import Counter
import re
import unicodedata


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def coverage(reference, candidate):
    """Order-insensitive character and 5-gram recall against extractable text.

    Whitespace/formatting differences are ignored. These scores cannot detect
    incorrect column order or text missing from the PDF's text layer itself.
    """
    ref, cand = normalized(reference), normalized(candidate)
    if not ref:
        return {"character_recall": None, "ngram_recall": None, "length_ratio": None}

    def recall(a, b):
        return round(sum((a & b).values()) / max(1, sum(a.values())), 4)

    n = min(5, len(ref))
    return {
        "character_recall": recall(Counter(ref), Counter(cand)),
        "ngram_recall": recall(Counter(ref[i:i+n] for i in range(len(ref)-n+1)),
                               Counter(cand[i:i+n] for i in range(max(0, len(cand)-n+1)))),
        "length_ratio": round(len(cand) / len(ref), 4),
    }


def text_health(text):
    visible = [c for c in text if not c.isspace()]
    bad = sum(c == "\ufffd" or unicodedata.category(c) in {"Co", "Cc"} for c in visible)
    lines = [normalized(line) for line in text.splitlines() if normalized(line)]
    counts = Counter(lines)
    return {
        "chars": len(text),
        "alnum_chars": len(normalized(text)),
        "suspicious_unicode_count": bad,
        "suspicious_unicode_ratio": round(bad / max(1, len(visible)), 4),
        "repeated_line_instances": sum(n - 1 for n in counts.values() if n > 1),
        "standalone_numbers": len(re.findall(r"^\s*\d+\s*$", text, re.M)),
    }


def candidate_issues(reference, candidate):
    scores = coverage(reference, candidate)
    issues = []
    if scores["character_recall"] is not None and scores["character_recall"] < .97:
        issues.append("candidate_character_loss")
    if scores["ngram_recall"] is not None and scores["ngram_recall"] < .90:
        issues.append("candidate_sequence_loss")
    if scores["length_ratio"] is not None and scores["length_ratio"] > 1.35:
        issues.append("candidate_expansion")
    return scores, issues
