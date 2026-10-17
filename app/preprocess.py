"""Cleaning the pasted email before the AI sees it."""
import re

_ON_WROTE = re.compile(r"^\s*On\s.{3,200}$", re.I)
_ORIGINAL = re.compile(r"^\s*[-_=]{2,}\s*Original Message\s*[-_=]*\s*$", re.I)


def strip_quoted(body: str) -> tuple[str, int]:
    """Drop the earlier messages of a reply thread so only the newest message is analysed.

    Cut at "On <date> <name> wrote:" or "----- Original Message -----", and drop lines quoted
    with ">". Forwarded messages are KEPT: the real request is often inside them.
    Returns (clean_body, number_of_lines_removed). Never returns an empty email.
    """
    lines = body.splitlines()
    cut = None
    for i, line in enumerate(lines):
        if _ORIGINAL.match(line):
            cut = i
            break
        if _ON_WROTE.match(line):
            next_line = lines[i + 1].strip().lower() if i + 1 < len(lines) else ""
            if "wrote:" in line.lower() or next_line.endswith("wrote:"):
                cut = i
                break
    kept = lines if cut is None else lines[:cut]
    removed = len(lines) - len(kept)
    final = [line for line in kept if not line.lstrip().startswith(">")]
    removed += len(kept) - len(final)
    clean = "\n".join(final).strip()
    if not clean:
        return body, 0
    return clean, removed
