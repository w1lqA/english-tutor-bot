import re

from pydantic import BaseModel

_TAG_RE = re.compile(r"^\s*#vocabulary\b", re.IGNORECASE)


def is_vocabulary_post(text: str | None) -> bool:
    return bool(text) and _TAG_RE.match(text) is not None


def extract_content(text: str) -> str:
    """Post text with the leading #vocabulary tag removed."""
    return _TAG_RE.sub("", text, count=1).strip()


# --- Structured LLM output (all fields optional: concise beats exhaustive) ---

class Meaning(BaseModel):
    english: str | None = None
    russian: str | None = None


class Correction(BaseModel):
    original: str
    corrected: str
    note: str | None = None


class VocabularyItem(BaseModel):
    term: str
    part_of_speech: str | None = None
    pronunciation: str | None = None
    meanings: list[Meaning] | None = None
    collocations: list[str] | None = None
    grammar: str | None = None
    examples: list[str] | None = None
    synonyms: list[str] | None = None
    register: str | None = None
    correction: Correction | str | None = None


class VocabularyAnalysis(BaseModel):
    items: list[VocabularyItem] = []