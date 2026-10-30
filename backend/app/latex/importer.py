"""Safe import of manuscripts: LaTeX project ZIPs, single .tex/.bib files, Markdown and DOCX.

Archives are treated as hostile: entry count, total uncompressed size and per-entry
compression ratio are bounded, paths are re-validated (no absolute paths, traversal,
symlinks or hidden files), and nothing is ever executed. Converted formats (Markdown,
DOCX) report every construct that could not be represented faithfully.
"""
import io
import re
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET  # noqa: S405 - parsing DOCX XML with no external entities

from app.latex.paths import (
    ManuscriptPathError,
    is_binary_asset_path,
    is_text_path,
    normalize_manuscript_path,
)

MAX_COMPRESSION_RATIO = 200
MAX_SINGLE_TEXT_BYTES = 8 * 1024 * 1024
SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
BUILD_ARTIFACT_SUFFIXES = {".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk", ".synctex.gz", ".blg", ".lof", ".lot", ".nav", ".snm"}


class ImportErrorWithReason(ValueError):
    pass


@dataclass
class ImportedFile:
    path: str
    kind: str  # "text" | "binary"
    text: str = ""
    data: bytes = b""


@dataclass
class ImportResult:
    files: list[ImportedFile] = field(default_factory=list)
    main_file: str = ""
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def decode_text(data: bytes, name: str, warnings: list[str]) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        warnings.append(f"{name} is not valid UTF-8; decoded as Latin-1. Check accented characters.")
        return data.decode("latin-1")


def detect_main_file(texts: dict[str, str]) -> str:
    candidates = [p for p, t in texts.items() if p.endswith(".tex") and "\\documentclass" in t and "\\begin{document}" in t]
    for preferred in ("main.tex", "paper.tex", "manuscript.tex", "thesis.tex"):
        if preferred in candidates:
            return preferred
    candidates.sort(key=lambda p: (p.count("/"), p))
    return candidates[0] if candidates else ""


def import_zip(data: bytes, max_entries: int, max_total_bytes: int) -> ImportResult:
    result = ImportResult()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportErrorWithReason("The file is not a valid ZIP archive.") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > max_entries:
        raise ImportErrorWithReason(f"The archive has {len(infos)} files; the limit is {max_entries}.")
    total = sum(i.file_size for i in infos)
    if total > max_total_bytes:
        raise ImportErrorWithReason("The archive expands beyond the allowed size.")

    # Strip a single shared top-level folder (common when zipping a directory).
    names = [i.filename.replace("\\", "/") for i in infos]
    tops = {n.split("/", 1)[0] for n in names}
    strip = next(iter(tops)) + "/" if len(tops) == 1 and all("/" in n for n in names) else ""

    texts: dict[str, str] = {}
    for info in infos:
        raw_name = info.filename.replace("\\", "/")
        mode = (info.external_attr >> 16) & 0o170000
        if mode and stat.S_ISLNK(mode):
            result.skipped.append(raw_name + " (symbolic link)")
            continue
        if raw_name.startswith("__MACOSX/") or PurePosixPath(raw_name).name in SKIP_NAMES:
            continue
        if raw_name.startswith("/") or ".." in raw_name.split("/") or re.match(r"^[A-Za-z]:", raw_name):
            raise ImportErrorWithReason(f"Archive entry '{raw_name}' tries to escape the project directory.")
        rel = raw_name[len(strip):] if strip and raw_name.startswith(strip) else raw_name
        if any(rel.endswith(s) for s in BUILD_ARTIFACT_SUFFIXES):
            result.skipped.append(rel + " (build artifact)")
            continue
        if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
            raise ImportErrorWithReason(f"Archive entry '{rel}' has a suspicious compression ratio.")
        try:
            path = normalize_manuscript_path(rel)
        except ManuscriptPathError as exc:
            result.skipped.append(f"{rel} ({exc})")
            continue
        content = zf.read(info)
        if len(content) != info.file_size:
            raise ImportErrorWithReason(f"Archive entry '{rel}' size mismatch.")
        if is_text_path(path) and not is_binary_asset_path(path):
            if len(content) > MAX_SINGLE_TEXT_BYTES:
                result.skipped.append(f"{path} (text file too large for the editor)")
                continue
            text = decode_text(content, path, result.warnings)
            texts[path] = text
            result.files.append(ImportedFile(path, "text", text=text))
        else:
            result.files.append(ImportedFile(path, "binary", data=content))
    result.main_file = detect_main_file(texts)
    if not result.main_file:
        result.warnings.append("No file with \\documentclass and \\begin{document} was found; choose the main file manually.")
    return result


# ----------------------------------------------------------------------------
# Markdown -> LaTeX
# ----------------------------------------------------------------------------
_LATEX_SPECIALS = {"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def _escape_text(s: str) -> str:
    s = s.replace("\\", r"\textbackslash{}")
    return "".join(_LATEX_SPECIALS.get(ch, ch) for ch in s)


def _inline_md(s: str) -> str:
    # Protect math and inline code first, then escape and convert emphasis/links.
    tokens: list[str] = []

    def keep(value: str) -> str:
        tokens.append(value)
        return f"\x00{len(tokens) - 1}\x00"

    s = re.sub(r"\$\$(.+?)\$\$", lambda m: keep(f"\\[{m.group(1)}\\]"), s)
    s = re.sub(r"(?<!\\)\$(.+?)(?<!\\)\$", lambda m: keep(f"${m.group(1)}$"), s)
    s = re.sub(r"`([^`]+)`", lambda m: keep(f"\\texttt{{{_escape_text(m.group(1))}}}"), s)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", lambda m: keep(f"\\includegraphics[width=\\linewidth]{{{m.group(2)}}}"), s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: keep(f"\\href{{{m.group(2)}}}{{{_escape_text(m.group(1))}}}"), s)
    s = _escape_text(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", s)
    s = re.sub(r"(?<![\w\\])\\_(?!\s)(.+?)(?<!\s)\\_(?!\w)", r"\\emph{\1}", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m.group(1))], s)


def markdown_to_latex(md: str, title: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    body: list[str] = []
    lines = md.splitlines()
    i = 0
    list_stack: list[str] = []

    def close_lists() -> None:
        while list_stack:
            body.append(f"\\end{{{list_stack.pop()}}}")

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            close_lists()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            body.append("\\begin{verbatim}\n" + "\n".join(block) + "\n\\end{verbatim}")
            i += 1
            continue
        if line.strip() == "$$":
            close_lists()
            block = []
            i += 1
            while i < len(lines) and lines[i].strip() != "$$":
                block.append(lines[i])
                i += 1
            body.append("\\begin{equation*}\n" + "\n".join(block) + "\n\\end{equation*}")
            i += 1
            continue
        h = re.match(r"^(#{1,4})\s+(.*)$", line)
        if h:
            close_lists()
            cmd = {1: "section", 2: "subsection", 3: "subsubsection", 4: "paragraph"}[len(h.group(1))]
            body.append(f"\\{cmd}{{{_inline_md(h.group(2).strip())}}}")
            i += 1
            continue
        item = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if item:
            env = "enumerate" if item.group(2)[0].isdigit() else "itemize"
            if not list_stack or list_stack[-1] != env:
                close_lists()
                body.append(f"\\begin{{{env}}}")
                list_stack.append(env)
            body.append(f"  \\item {_inline_md(item.group(3))}")
            i += 1
            continue
        if line.strip().startswith("|"):
            close_lists()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                cols = max(len(r) for r in rows)
                tex = ["\\begin{tabular}{" + "l" * cols + "}", "\\toprule"]
                for n, r in enumerate(rows):
                    tex.append(" & ".join(_inline_md(c) for c in r + [""] * (cols - len(r))) + " \\\\")
                    if n == 0:
                        tex.append("\\midrule")
                tex += ["\\bottomrule", "\\end{tabular}"]
                body.append("\n".join(tex))
            continue
        if line.startswith(">"):
            close_lists()
            body.append("\\begin{quote}\n" + _inline_md(line.lstrip("> ")) + "\n\\end{quote}")
            i += 1
            continue
        if re.match(r"^<[^>]+>", line.strip()):
            warnings.append(f"Line {i + 1}: raw HTML is not supported and was kept as escaped text.")
        if not line.strip():
            close_lists()
            body.append("")
        else:
            body.append(_inline_md(line))
        i += 1
    close_lists()
    doc = (
        "\\documentclass[11pt]{article}\n\\usepackage{amsmath,amssymb}\n\\usepackage{graphicx}\n\\usepackage{booktabs}\n"
        "\\usepackage[hidelinks]{hyperref}\n\n"
        f"\\title{{{_escape_text(title)}}}\n\n\\begin{{document}}\n\\maketitle\n\n" + "\n".join(body).strip() + "\n\n\\end{document}\n"
    )
    return doc, warnings


# ----------------------------------------------------------------------------
# DOCX -> LaTeX (text structure only; formatting beyond headings/bold/italic is reported)
# ----------------------------------------------------------------------------
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _safe_xml(data: bytes) -> ET.Element:
    if b"<!DOCTYPE" in data[:2048] or b"<!ENTITY" in data[:4096]:
        raise ImportErrorWithReason("DOCX contains a DTD, which is not allowed.")
    return ET.fromstring(data)  # noqa: S314 - DTDs rejected above


def docx_to_latex(data: bytes, title: str) -> tuple[str, list[ImportedFile], list[str]]:
    warnings: list[str] = []
    assets: list[ImportedFile] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        document = _safe_xml(zf.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ImportErrorWithReason("The file is not a valid .docx document.") from exc
    rels: dict[str, str] = {}
    try:
        for rel in _safe_xml(zf.read("word/_rels/document.xml.rels")):
            rels[rel.get("Id", "")] = rel.get("Target", "")
    except KeyError:
        pass

    body = document.find(f"{W}body")
    if body is None:
        raise ImportErrorWithReason("The .docx document has no body.")
    out: list[str] = []
    doc_title = title
    unsupported: set[str] = set()

    def runs_text(p: ET.Element) -> str:
        parts = []
        for node in p.iter():
            if node.tag == f"{W}r":
                text = "".join(t.text or "" for t in node.iter(f"{W}t"))
                if not text:
                    blip = next(node.iter(f"{A_NS}blip"), None)
                    if blip is not None:
                        target = rels.get(blip.get(f"{R_NS}embed", ""), "")
                        if target.startswith("media/"):
                            name = PurePosixPath(target).name
                            try:
                                path = normalize_manuscript_path(f"figures/{name}")
                                assets.append(ImportedFile(path, "binary", data=zf.read(f"word/{target}")))
                                parts.append(f"\n\\begin{{figure}}[htbp]\n\\centering\n\\includegraphics[width=0.8\\linewidth]{{{path}}}\n\\end{{figure}}\n")
                            except (KeyError, ManuscriptPathError):
                                unsupported.add("an embedded image could not be extracted")
                    continue
                rpr = node.find(f"{W}rPr")
                esc = _escape_text(text)
                if rpr is not None and rpr.find(f"{W}b") is not None:
                    esc = f"\\textbf{{{esc}}}"
                if rpr is not None and rpr.find(f"{W}i") is not None:
                    esc = f"\\emph{{{esc}}}"
                parts.append(esc)
            elif node.tag.endswith("}oMath"):
                unsupported.add("Word equations (OMML) are not converted; they are marked with TODO comments")
                parts.append(" % TODO: equation from Word not converted\n")
        return "".join(parts)

    for el in body:
        if el.tag == f"{W}p":
            style_el = el.find(f"{W}pPr/{W}pStyle")
            style = style_el.get(f"{W}val", "") if style_el is not None else ""
            text = runs_text(el).strip()
            if not text:
                out.append("")
                continue
            low = style.lower()
            if low == "title":
                doc_title = re.sub(r"\\[a-z]+\{|\}", "", text)
                continue
            heading = re.match(r"heading(\d)", low)
            if heading:
                level = int(heading.group(1))
                cmd = {1: "section", 2: "subsection", 3: "subsubsection"}.get(level, "paragraph")
                out.append(f"\\{cmd}{{{text}}}")
            elif "list" in low:
                out.append(f"\\begin{{itemize}}\n  \\item {text}\n\\end{{itemize}}")
            else:
                out.append(text)
        elif el.tag == f"{W}tbl":
            rows = []
            for tr in el.iter(f"{W}tr"):
                rows.append([runs_text(tc).strip() for tc in tr.iter(f"{W}tc")])
            if rows:
                cols = max(len(r) for r in rows)
                table = ["\\begin{table}[htbp]", "\\centering", "\\begin{tabular}{" + "l" * cols + "}", "\\toprule"]
                for n, r in enumerate(rows):
                    table.append(" & ".join(r + [""] * (cols - len(r))) + " \\\\")
                    if n == 0:
                        table.append("\\midrule")
                table += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
                out.append("\n".join(table))
                unsupported.add("table cell merges and shading are not preserved")
    if zf.namelist() and any(n.startswith("word/comments") for n in zf.namelist()):
        unsupported.add("Word comments and tracked changes are not imported")
    warnings.extend(sorted(unsupported))
    text_body = re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)).strip()
    tex = (
        "\\documentclass[11pt]{article}\n\\usepackage{amsmath,amssymb}\n\\usepackage{graphicx}\n\\usepackage{booktabs}\n\n"
        f"\\title{{{_escape_text(doc_title)}}}\n\n\\begin{{document}}\n\\maketitle\n\n{text_body}\n\n\\end{{document}}\n"
    )
    return tex, assets, warnings
