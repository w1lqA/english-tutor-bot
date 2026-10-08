import re
from html import escape

from vocabulary import Correction, VocabularyAnalysis, VocabularyItem

MAX_MESSAGE_LEN = 4000  # Telegram's hard limit is 4096

SEPARATOR = "──────────"


def _e(s: str) -> str:
    return escape(s, quote=False)


# ---------------------------------------------------------------------------
# Target-term highlighting (deterministic; no extra LLM calls)
# ---------------------------------------------------------------------------

# Lightweight English inflection generation: given a base term, produce
# plausible surface forms we should look for in examples/collocations.
# Deliberately small; we are not building a morphological analyzer.
def _inflected_forms(term: str) -> set[str]:
    t = term.strip().lower()
    forms = {t}
    if not t:
        return forms

    # Strip a leading infinitive marker for verbs like "to entangle".
    core = t[3:].strip() if t.startswith("to ") else t
    if not core:
        return forms

    forms.add(core)

    # Regular verb / adjective inflections
    if core.endswith("e"):
        forms.add(core + "d")
        forms.add(core + "s")
        forms.add(core[:-1] + "ing")
    elif core.endswith("y") and len(core) > 1 and core[-2] not in "aeiou":
        stem = core[:-1]
        forms.add(stem + "ies")
        forms.add(stem + "ied")
        forms.add(core + "ing")
    else:
        forms.add(core + "s")
        forms.add(core + "ed")
        forms.add(core + "ing")

    # Consonant doubling for CVC endings (rig → rigged, stop → stopping)
    if (
        len(core) >= 3
        and core[-1] not in "aeiouwy"
        and core[-2] in "aeiou"
        and core[-3] not in "aeiou"
    ):
        forms.add(core + core[-1] + "ed")
        forms.add(core + core[-1] + "ing")

    # Irregulars we care about (short list, extended as needed)
    irregular = {
        "halve": ["halved", "halves", "halving"],
        "imply": ["implied", "implies", "implying"],
        "rigorous": [],
    }
    for extra in irregular.get(core, []):
        forms.add(extra)

    return forms


def _build_pattern(term: str) -> re.Pattern | None:
    """Build a case-insensitive word-boundary regex matching the term and its
    plausible inflections. Returns None if the term is empty."""
    if not term or not term.strip():
        return None

    forms = _inflected_forms(term)
    # Longest first so "entangled" matches before "entangle".
    forms_sorted = sorted(forms, key=len, reverse=True)
    escaped = [re.escape(f) for f in forms_sorted]

    # For multi-word phrases we allow the phrase itself; word boundaries still
    # apply at the outer edges so "art" won't match inside "article".
    alternation = "|".join(escaped)
    pattern = re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)
    return pattern


def _highlight_html(text: str, term: str, tag: str) -> str:
    """Escape `text` for Telegram HTML, then wrap matches of `term` (and its
    plausible inflections) in `<tag>...</tag>`.

    Escaping happens first, then matching on the escaped string. All form
    characters we search for (letters, spaces, hyphens) survive HTML escaping
    unchanged, so the offsets are safe.
    """
    escaped = _e(text)
    pattern = _build_pattern(term)
    if pattern is None:
        return escaped

    def repl(m: re.Match) -> str:
        return f"<{tag}>{m.group(0)}</{tag}>"

    return pattern.sub(repl, escaped)


# ---------------------------------------------------------------------------
# Item rendering
# ---------------------------------------------------------------------------

def _format_header(it: VocabularyItem) -> str:
    parts = [f"<b>{_e(it.term)}</b>"]
    if it.part_of_speech:
        parts.append(f"<i>{_e(it.part_of_speech)}</i>")
    if it.pronunciation:
        parts.append(_e(it.pronunciation))
    return "  ".join(parts)


def _format_correction(c: Correction | str | None) -> str | None:
    if c is None:
        return None

    if isinstance(c, Correction):
        line = (
            f"⚠️ <b>Correction</b>\n"
            f"<s>{_e(c.original)}</s> → <b>{_e(c.corrected)}</b>"
        )
        if c.note:
            line += f"\n{_e(c.note)}"
        return line

    # Plain-string correction from older responses
    return f"⚠️ <b>Correction</b>\n{_e(c)}"


def _format_meaning(it: VocabularyItem) -> str | None:
    meanings = [m for m in (it.meanings or []) if m.english or m.russian]
    if not meanings:
        return None

    lines = ["💡 <b>Meaning</b>"]
    if len(meanings) == 1:
        m = meanings[0]
        eng = _e(m.english) if m.english else ""
        rus = f"<b>{_e(m.russian)}</b>" if m.russian else ""
        line = " — ".join(p for p in (eng, rus) if p)
        lines.append(line)
    else:
        for m in meanings:
            eng = _e(m.english) if m.english else ""
            rus = f"<b>{_e(m.russian)}</b>" if m.russian else ""
            line = " — ".join(p for p in (eng, rus) if p)
            lines.append(f"• {line}")
    return "\n".join(lines)


def _format_collocations(it: VocabularyItem) -> str | None:
    if not it.collocations:
        return None
    lines = ["🔗 <b>Collocations</b>"]
    for coll in it.collocations:
        # Whole collocation is bolded, per the brief: the phrase is the
        # learning unit. Target term inside is not separately highlighted.
        lines.append(f"• <b>{_e(coll)}</b>")
    return "\n".join(lines)


def _format_grammar(it: VocabularyItem) -> str | None:
    if not it.grammar:
        return None
    return f"🧩 <b>Pattern</b>\n{_e(it.grammar)}"


def _format_examples(it: VocabularyItem) -> str | None:
    if not it.examples:
        return None
    lines = ["✍️ <b>Examples</b>"]
    for ex in it.examples:
        lines.append(f"• {_highlight_html(ex, it.term, 'u')}")
    return "\n".join(lines)


def _format_synonyms(it: VocabularyItem) -> str | None:
    if not it.synonyms:
        return None
    joined = " · ".join(_e(s) for s in it.synonyms)
    return f"🔄 <b>Synonyms:</b> {joined}"


def _format_register(it: VocabularyItem) -> str | None:
    if not it.register:
        return None
    return f"🎯 <b>Register:</b> {_e(it.register)}"


def _format_item(it: VocabularyItem) -> str:
    sections: list[str] = [_format_header(it)]

    for render in (
        lambda: _format_correction(it.correction),
        lambda: _format_meaning(it),
        lambda: _format_collocations(it),
        lambda: _format_grammar(it),
        lambda: _format_examples(it),
        lambda: _format_synonyms(it),
        lambda: _format_register(it),
    ):
        block = render()
        if block:
            sections.append(block)

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Top-level formatter
# ---------------------------------------------------------------------------

def format_vocabulary_analysis(data: VocabularyAnalysis) -> list[str]:
    """Return one or more Telegram-HTML messages for the analysis.

    Splits on item boundaries so no single message exceeds Telegram's limit.
    """
    if not data.items:
        return ["No vocabulary items found in this post."]

    messages: list[str] = []
    current = ""
    for block in (_format_item(it) for it in data.items):
        candidate = f"{current}\n\n{SEPARATOR}\n\n{block}" if current else block
        if current and len(candidate) > MAX_MESSAGE_LEN:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages