"""Zero-dependency language hint for the extractor.

The LLM already preserves the message language when told to, but a short or
ambiguous sentence can still slip to English (the model's default bias). A cheap,
deterministic detector run BEFORE the LLM lets us name the language explicitly in
the prompt — turning "preserve the language" into "write in Portuguese".

Two stages, stdlib only:
  1. Script detection (Unicode ranges) — near-certain for non-Latin scripts
     (CJK, Cyrillic, Arabic, Devanagari, Hangul, Hebrew, Greek, Thai).
  2. Stop-word voting for Latin-script languages (pt/en/es/fr/de/it…).

Returns a human-readable language NAME the prompt can drop in, or None when it
can't tell confidently — in which case we fall back to the plain "preserve the
language" instruction and let the LLM decide.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Optional

# ── stage 1: script ranges → language name (only when unambiguous) ───────────
_SCRIPT_NAME = {
    "CJK": "Chinese",            # refined to ja/ko below if kana/hangul present
    "HIRAGANA": "Japanese", "KATAKANA": "Japanese",
    "HANGUL": "Korean",
    "CYRILLIC": "Russian",
    "ARABIC": "Arabic",
    "DEVANAGARI": "Hindi",
    "HEBREW": "Hebrew",
    "GREEK": "Greek",
    "THAI": "Thai",
}


def _script_of(ch: str) -> Optional[str]:
    o = ord(ch)
    if 0x3040 <= o <= 0x309F: return "HIRAGANA"
    if 0x30A0 <= o <= 0x30FF: return "KATAKANA"
    if 0xAC00 <= o <= 0xD7AF: return "HANGUL"
    if 0x4E00 <= o <= 0x9FFF: return "CJK"
    if 0x0400 <= o <= 0x04FF: return "CYRILLIC"
    if 0x0600 <= o <= 0x06FF: return "ARABIC"
    if 0x0900 <= o <= 0x097F: return "DEVANAGARI"
    if 0x0590 <= o <= 0x05FF: return "HEBREW"
    if 0x0370 <= o <= 0x03FF: return "GREEK"
    if 0x0E00 <= o <= 0x0E7F: return "THAI"
    return None


# ── stage 2: Latin-script stop words (high-frequency, low-overlap) ───────────
_STOP = {
    "Portuguese": "de que e o a do da em um para com nao uma os no se na por mais as dos como mas ao ele das tem seu sua ou quando muito eu tambem so pelo ela entre era voce".split(),
    "English": "the of and to in a is that it for was on are as with his they at be this from or had by but not what all were we when your can said there use".split(),
    "Spanish": "de la que el en y a los del se las por un para con no una su al lo como mas pero sus le ya este si porque esta entre cuando muy entonces entre".split(),
    "French": "je le la de un et a les des en du une dans est que qui pour pas sur au avec ce il ne se ces son mais ou comme tout nous leur bien sans vous c'est cette ".split(),
    "German": "der die und in den von zu das mit sich des auf fur ist im dem nicht ein eine als auch es an werden aus er hat dass sie nach wird bei".split(),
    "Italian": "di che e la il un a per in una sono mi si ma con le ci se ti lo come piu io questo ha sua qui hai cosa quando perche".split(),
}
_WORD = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def detect_language(text: str) -> Optional[str]:
    """Best-effort language NAME for the prompt, or None if not confident."""
    if not text or len(text.strip()) < 3:
        return None

    # stage 1 — non-Latin script wins outright
    scripts = Counter(s for ch in text if (s := _script_of(ch)))
    if scripts:
        top, n = scripts.most_common(1)[0]
        if n >= 2:
            if top == "CJK" and (scripts["HIRAGANA"] or scripts["KATAKANA"]):
                return "Japanese"
            return _SCRIPT_NAME.get(top)

    # stage 2 — Latin stop-word voting (accent-insensitive so "não"~"nao")
    words = [_strip_accents(w.lower()) for w in _WORD.findall(text)]
    if len(words) < 2:
        return None
    bag = set(words)
    scores = {lang: sum(1 for w in stop if w in bag) for lang, stop in _STOP.items()}
    best = max(scores, key=scores.get)
    top = scores[best]
    if top == 0:
        return None
    # require a clear winner: the runner-up must trail, else it's ambiguous
    runner = sorted(scores.values(), reverse=True)[1]
    if top - runner < 1:
        return None
    return best
