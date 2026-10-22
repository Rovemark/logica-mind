"""Linear mention matching without allocating four n-grams for every word."""
import re


class MentionIndex:
    def __init__(self, names, pattern=r"[\w][\w'\-]*"):
        self.pattern = re.compile(pattern)
        self.first = {}
        for name in names:
            tokens = tuple(self.pattern.findall(str(name).lower()))
            if not tokens or len(tokens) > 4:
                continue
            self.first.setdefault(tokens[0], {})[tokens] = name

    def matches(self, text, limit=None):
        tokens = self.pattern.findall(str(text or '').lower())
        found, seen = [], set()
        for i, word in enumerate(tokens):
            candidates = self.first.get(word)
            if not candidates:
                continue
            for size in (4, 3, 2, 1):
                if i + size > len(tokens):
                    continue
                name = candidates.get(tuple(tokens[i:i + size]))
                if name is not None and name not in seen:
                    seen.add(name)
                    found.append(name)
                    if limit and len(found) >= limit:
                        return found
        return found
