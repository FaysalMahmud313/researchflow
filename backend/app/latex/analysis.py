"""Static analysis of LaTeX source: outline, section extraction, labels, citations, dependencies.

Nothing here rewrites source. Section extraction slices the original text verbatim so the
exported LaTeX is byte-for-byte what the researcher wrote.
"""
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable, Mapping

SECTION_LEVELS: dict[str, int] = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
}

_HEADING_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{")
_ENV_BEGIN_RE = re.compile(r"\\begin\{(abstract|figure\*?|table\*?|equation\*?|align\*?|algorithm\*?|gather\*?|multline\*?)\}")
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_CITE_RE = re.compile(
    r"\\(?:no)?(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|parencite|textcite|autocite|footcite|fullcite|smartcite)\*?"
    r"\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]*)\}"
)
_REF_RE = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref|nameref|vref)\*?\{([^}]+)\}")
_INPUT_RE = re.compile(r"\\(input|include|subfile|import)\s*\{([^}]+)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics\*?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_GRAPHICSPATH_RE = re.compile(r"\\graphicspath\s*\{((?:\{[^}]*\}\s*)+)\}")
_BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\s*\{([^}]+)\}")
_ADDBIB_RE = re.compile(r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_USEPACKAGE_RE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_DOCCLASS_RE = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_BIBSTYLE_RE = re.compile(r"\\bibliographystyle\s*\{([^}]+)\}")

GRAPHICS_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")


def mask_comments(text: str) -> str:
    """Replace `%` comments with spaces, keeping offsets identical. `\\%` is not a comment."""
    out = []
    for line in text.split("\n"):
        idx = 0
        cut = -1
        while idx < len(line):
            ch = line[idx]
            if ch == "\\":
                idx += 2
                continue
            if ch == "%":
                cut = idx
                break
            idx += 1
        out.append(line if cut < 0 else line[:cut] + " " * (len(line) - cut))
    return "\n".join(out)


def _read_braced(text: str, open_brace_idx: int) -> tuple[str, int]:
    """Return (content, index after closing brace) for a balanced group starting at `{`."""
    depth = 0
    i = open_brace_idx
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1 : i], i + 1
        i += 1
    return text[open_brace_idx + 1 :], len(text)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


@dataclass
class OutlineItem:
    kind: str  # heading command name, or environment name
    level: int
    title: str
    label: str
    start: int
    end: int
    line: int
    end_line: int

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "level": self.level,
            "title": self.title,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "line": self.line,
            "end_line": self.end_line,
        }


def build_outline(text: str) -> list[OutlineItem]:
    """List headings (with their full extent) plus abstract/figure/table/equation environments."""
    masked = mask_comments(text)
    doc_end = masked.find("\\end{document}")
    hard_end = doc_end if doc_end >= 0 else len(text)

    headings: list[tuple[int, str, int, str, int]] = []  # start, kind, level, title, after_title
    for m in _HEADING_RE.finditer(masked):
        title, after = _read_braced(masked, m.end() - 1)
        headings.append((m.start(), m.group(1), SECTION_LEVELS[m.group(1)], " ".join(title.split()), after))

    # Bibliography/appendix markers terminate the last section's body.
    terminators = [
        m.start()
        for m in re.finditer(r"\\(?:bibliography\{|printbibliography|begin\{thebibliography\}|appendix\b)", masked)
    ]

    items: list[OutlineItem] = []
    for idx, (start, kind, level, title, after) in enumerate(headings):
        end = hard_end
        for later_start, _k, later_level, _t, _a in headings[idx + 1 :]:
            if later_level <= level:
                end = later_start
                break
        for term in terminators:
            if start < term < end:
                end = term
                break
        end = _trim_trailing_whitespace(text, start, end)
        label_m = _LABEL_RE.search(masked, after, min(end, after + 300))
        items.append(
            OutlineItem(kind, level, title, label_m.group(1) if label_m else "", start, end, _line_of(text, start), _line_of(text, end))
        )

    for m in _ENV_BEGIN_RE.finditer(masked):
        env = m.group(1)
        end_tag = f"\\end{{{env}}}"
        end_idx = masked.find(end_tag, m.end())
        if end_idx < 0:
            continue
        end = end_idx + len(end_tag)
        body = masked[m.end() : end_idx]
        label_m = _LABEL_RE.search(body)
        caption_title = ""
        cap = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", body)
        if cap:
            caption_title, _ = _read_braced(body, cap.end() - 1)
        base = env.rstrip("*")
        title = "Abstract" if base == "abstract" else (" ".join(caption_title.split())[:120] or (label_m.group(1) if label_m else base.title()))
        items.append(
            OutlineItem(base, 9, title, label_m.group(1) if label_m else "", m.start(), end, _line_of(text, m.start()), _line_of(text, end))
        )
    items.sort(key=lambda it: (it.start, it.level))
    return items


def _trim_trailing_whitespace(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1] in " \t\r\n":
        end -= 1
    return end


def extract_range(text: str, start: int, end: int) -> str:
    if start < 0 or end > len(text) or start >= end:
        raise ValueError("Invalid source range.")
    return text[start:end] + "\n"


def find_labels(text: str) -> list[dict[str, object]]:
    masked = mask_comments(text)
    return [{"label": m.group(1).strip(), "line": _line_of(text, m.start())} for m in _LABEL_RE.finditer(masked)]


def find_citations(text: str) -> list[str]:
    keys: list[str] = []
    for m in _CITE_RE.finditer(mask_comments(text)):
        keys.extend(k.strip() for k in m.group(1).split(",") if k.strip() and k.strip() != "*")
    return keys


def find_refs(text: str) -> list[str]:
    out: list[str] = []
    for m in _REF_RE.finditer(mask_comments(text)):
        out.extend(k.strip() for k in m.group(1).split(",") if k.strip())
    return out


@dataclass
class DependencyReport:
    reachable_files: list[str] = field(default_factory=list)
    missing_inputs: list[dict[str, object]] = field(default_factory=list)
    missing_figures: list[dict[str, object]] = field(default_factory=list)
    missing_bibliographies: list[dict[str, object]] = field(default_factory=list)
    undefined_citations: list[str] = field(default_factory=list)
    undefined_references: list[str] = field(default_factory=list)
    referenced_assets: list[str] = field(default_factory=list)
    local_packages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "reachable_files": self.reachable_files,
            "missing_inputs": self.missing_inputs,
            "missing_figures": self.missing_figures,
            "missing_bibliographies": self.missing_bibliographies,
            "undefined_citations": self.undefined_citations,
            "undefined_references": self.undefined_references,
            "referenced_assets": self.referenced_assets,
            "local_packages": self.local_packages,
            "warnings": self.warnings,
            "ok": not (self.missing_inputs or self.missing_figures or self.missing_bibliographies),
        }


def _resolve(candidate: str, base_dir: str, existing: set[str], extensions: Iterable[str]) -> str | None:
    cand = candidate.strip().strip('"')
    options = []
    for root in (base_dir, ""):
        joined = str(PurePosixPath(root) / cand) if root else cand
        while joined.startswith("./"):
            joined = joined[2:]
        options.append(joined)
    for opt in options:
        if opt in existing:
            return opt
        for ext in extensions:
            if opt + ext in existing:
                return opt + ext
    return None


def analyze_dependencies(
    files: Mapping[str, str],
    binary_paths: Iterable[str],
    main_file: str,
    bib_keys_extra: Iterable[str] = (),
) -> DependencyReport:
    """Walk \\input/\\include from the main file and report missing files, figures, citations and labels.

    `files` maps text file paths to their content; `binary_paths` lists uploaded assets.
    """
    from app.latex.bibtex import parse_bibtex

    report = DependencyReport()
    existing = set(files) | set(binary_paths)
    if main_file not in files:
        report.missing_inputs.append({"path": main_file, "from": "(main file)", "line": 0})
        return report

    visited: list[str] = []
    stack = [main_file]
    graphics_dirs: list[str] = [""]
    bib_files: list[str] = []
    all_cites: set[str] = set()
    all_refs: set[str] = set()
    all_labels: set[str] = set()

    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.append(current)
        text = files.get(current, "")
        masked = mask_comments(text)
        base_dir = str(PurePosixPath(current).parent) if "/" in current else ""

        for gp in _GRAPHICSPATH_RE.finditer(masked):
            for d in re.findall(r"\{([^}]*)\}", gp.group(1)):
                graphics_dirs.append(d.strip().strip("/"))

        for m in _INPUT_RE.finditer(masked):
            target = m.group(2).strip()
            resolved = _resolve(target, base_dir, set(files), (".tex",))
            if resolved:
                stack.append(resolved)
            else:
                report.missing_inputs.append({"path": target, "from": current, "line": _line_of(text, m.start())})

        for m in _GRAPHICS_RE.finditer(masked):
            target = m.group(1).strip()
            found = None
            for gdir in graphics_dirs:
                cand = str(PurePosixPath(gdir) / target) if gdir else target
                found = _resolve(cand, base_dir, existing, GRAPHICS_EXTENSIONS)
                if found:
                    break
            if found:
                if found not in report.referenced_assets:
                    report.referenced_assets.append(found)
            else:
                report.missing_figures.append({"path": target, "from": current, "line": _line_of(text, m.start())})

        for regex, default_ext in ((_BIBLIOGRAPHY_RE, ".bib"), (_ADDBIB_RE, "")):
            for m in regex.finditer(masked):
                for name in m.group(1).split(","):
                    name = name.strip()
                    if not name:
                        continue
                    resolved = _resolve(name, base_dir, set(files), (default_ext,) if default_ext else ())
                    if resolved:
                        bib_files.append(resolved)
                        if resolved not in report.referenced_assets:
                            report.referenced_assets.append(resolved)
                    else:
                        report.missing_bibliographies.append({"path": name, "from": current, "line": _line_of(text, m.start())})

        for regex, ext in ((_USEPACKAGE_RE, ".sty"), (_DOCCLASS_RE, ".cls"), (_BIBSTYLE_RE, ".bst")):
            for m in regex.finditer(masked):
                for name in m.group(1).split(","):
                    local = _resolve(name.strip(), base_dir, set(files), (ext,))
                    if local and local not in report.local_packages:
                        report.local_packages.append(local)

        all_cites.update(find_citations(text))
        all_refs.update(find_refs(text))
        all_labels.update(str(lbl["label"]) for lbl in find_labels(text))

    known_keys = set(bib_keys_extra)
    for bib in bib_files:
        entries, _ = parse_bibtex(files.get(bib, ""))
        known_keys.update(e.key for e in entries)
    # A thebibliography environment defines keys inline.
    for path in visited:
        known_keys.update(re.findall(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", files.get(path, "")))

    report.reachable_files = visited
    report.undefined_citations = sorted(k for k in all_cites if k not in known_keys)
    report.undefined_references = sorted(r for r in all_refs if r not in all_labels)
    if not bib_files and all_cites and not any("\\bibitem" in files.get(p, "") for p in visited):
        report.warnings.append("Citations are used but no \\bibliography or \\addbibresource was found.")
    return report
