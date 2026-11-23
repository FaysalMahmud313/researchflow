"""BibTeX parsing and serialization that preserves entry types and custom fields.

The parser is tolerant: malformed entries are reported as errors instead of aborting the
whole import, and unknown fields are kept verbatim so nothing a researcher wrote is lost.
"""
import re
from dataclasses import dataclass, field

_KEY_RE = re.compile(r"^[^\s,{}()\"#%'=\\~]+$")
_MONTHS = {m: m for m in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")}

COMMON_ENTRY_TYPES = (
    "article", "book", "booklet", "conference", "inbook", "incollection", "inproceedings", "manual",
    "mastersthesis", "misc", "phdthesis", "proceedings", "techreport", "unpublished", "online", "software", "dataset",
)


@dataclass
class BibEntry:
    entry_type: str
    key: str
    fields: dict[str, str] = field(default_factory=dict)
    line: int = 0

    def get(self, name: str) -> str:
        return self.fields.get(name, "")


@dataclass
class BibParseError:
    line: int
    message: str


def is_valid_cite_key(key: str) -> bool:
    return bool(key) and len(key) <= 120 and bool(_KEY_RE.match(key))


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def _read_value(s: str, i: int, strings: dict[str, str]) -> tuple[str, int]:
    """Read a field value: {braced}, "quoted", number, or @string macro, joined by #."""
    parts: list[str] = []
    while True:
        i = _skip_ws(s, i)
        if i >= len(s):
            raise ValueError("Unexpected end of input in field value.")
        ch = s[i]
        if ch == "{":
            depth, j = 0, i
            while j < len(s):
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= len(s):
                raise ValueError("Unbalanced braces in field value.")
            parts.append(s[i + 1 : j])
            i = j + 1
        elif ch == '"':
            depth, j = 0, i + 1
            while j < len(s):
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                elif s[j] == '"' and depth == 0:
                    break
                j += 1
            if j >= len(s):
                raise ValueError("Unterminated quoted field value.")
            parts.append(s[i + 1 : j])
            i = j + 1
        else:
            m = re.match(r"[A-Za-z0-9_.:+\-/]+", s[i:])
            if not m:
                raise ValueError(f"Unexpected character '{ch}' in field value.")
            token = m.group(0)
            low = token.lower()
            parts.append(strings.get(low, _MONTHS.get(low, token)))
            i += len(token)
        i = _skip_ws(s, i)
        if i < len(s) and s[i] == "#":
            i += 1
            continue
        return "".join(parts), i


def parse_bibtex(source: str) -> tuple[list[BibEntry], list[BibParseError]]:
    entries: list[BibEntry] = []
    errors: list[BibParseError] = []
    strings: dict[str, str] = {}
    i = 0
    n = len(source)
    while True:
        at = source.find("@", i)
        if at < 0:
            break
        line = source.count("\n", 0, at) + 1
        m = re.match(r"@\s*([A-Za-z]+)\s*([{(])", source[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        closer = "}" if m.group(2) == "{" else ")"
        j = at + m.end()
        try:
            if etype == "comment":
                depth = 1
                while j < n and depth:
                    if source[j] == m.group(2):
                        depth += 1
                    elif source[j] == closer:
                        depth -= 1
                    j += 1
                i = j
                continue
            if etype == "preamble":
                _value, j = _read_value(source, j, strings)
                j = _skip_ws(source, j)
                i = j + 1
                continue
            if etype == "string":
                name_m = re.match(r"\s*([A-Za-z][A-Za-z0-9_\-]*)\s*=", source[j:])
                if not name_m:
                    raise ValueError("Malformed @string definition.")
                value, j = _read_value(source, j + name_m.end(), strings)
                strings[name_m.group(1).lower()] = value
                j = _skip_ws(source, j)
                i = j + 1
                continue

            key_m = re.match(r"\s*([^\s,]+?)\s*,", source[j:])
            if not key_m:
                raise ValueError("Missing citation key.")
            key = key_m.group(1)
            if not is_valid_cite_key(key):
                raise ValueError(f"Invalid citation key '{key}'.")
            j += key_m.end()
            fields: dict[str, str] = {}
            while True:
                j = _skip_ws(source, j)
                if j < n and source[j] == closer:
                    j += 1
                    break
                if j < n and source[j] == ",":
                    j += 1
                    continue
                f_m = re.match(r"([A-Za-z][A-Za-z0-9_\-:+.]*)\s*=", source[j:])
                if not f_m:
                    raise ValueError("Malformed field (expected name = value).")
                fname = f_m.group(1).lower()
                value, j = _read_value(source, j + f_m.end(), strings)
                fields[fname] = " ".join(value.split()) if fname not in ("abstract", "note", "annote") else value.strip()
            entries.append(BibEntry(etype, key, fields, line))
            i = j
        except ValueError as exc:
            errors.append(BibParseError(line, str(exc)))
            # Resynchronise at the next entry start.
            i = at + 1
    return entries, errors


def _escape_value(value: str) -> str:
    depth = 0
    for ch in value:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                break
    if depth != 0:
        # Unbalanced braces cannot be represented in a braced value; escape them.
        value = value.replace("{", "\\{").replace("}", "\\}")
    return value


FIELD_ORDER = ("author", "editor", "title", "booktitle", "journal", "year", "month", "volume", "number", "pages",
               "publisher", "address", "school", "institution", "organization", "edition", "series", "doi", "url",
               "isbn", "issn", "eprint", "archiveprefix", "primaryclass", "note", "abstract", "keywords")


def serialize_entry(entry_type: str, key: str, fields: dict[str, str]) -> str:
    ordered = [f for f in FIELD_ORDER if fields.get(f)]
    ordered += sorted(f for f in fields if f not in FIELD_ORDER and fields.get(f))
    width = max((len(f) for f in ordered), default=0)
    body = ",\n".join(f"  {f.ljust(width)} = {{{_escape_value(fields[f])}}}" for f in ordered)
    return f"@{entry_type}{{{key},\n{body}\n}}" if body else f"@{entry_type}{{{key}\n}}"


def make_cite_key(authors: str, year: int | str, title: str, taken: set[str]) -> str:
    first = authors.split(" and ")[0].split(",")[0].strip() if authors else ""
    if "," not in (authors.split(" and ")[0] if authors else "") and first:
        first = first.split()[-1]
    surname = re.sub(r"[^A-Za-z0-9]", "", first).lower() or "ref"
    word = next((w for w in re.findall(r"[A-Za-z]{4,}", title or "") if w.lower() not in {"with", "from", "that", "this", "towards"}), "")
    base = f"{surname}{year}{word.lower()}"[:60]
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}{n}"
    return key


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\\[a-zA-Z]+|[{}]", "", title.lower()))


def normalize_doi(doi: str) -> str:
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d
