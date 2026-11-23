"""Portable exports: complete project ZIP, flattened single-file paper, figures archive.

Archives contain only the manuscript's own source files and assets at their original
relative paths, plus an optional generated README. No database records, user metadata,
credentials or unrelated project files are ever included.
"""
import io
import re
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Callable, Iterable, Mapping

from app.latex.analysis import DependencyReport, mask_comments

_INPUT_RE = re.compile(r"\\(input|include)\s*\{([^}]+)\}")


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=datetime.now(UTC).timetuple()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def build_readme(title: str, main_file: str, engine: str, report: DependencyReport) -> str:
    stem = PurePosixPath(main_file).stem
    engine_flag = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}.get(engine, "-pdf")
    lines = [
        f"# {title}",
        "",
        "LaTeX source exported from ResearchFlow. ResearchFlow does not compile PDFs, so this archive",
        "has not been compiled. Build it with your own TeX installation or upload it to an online editor.",
        "",
        "## Compiling it yourself",
        "",
        "```bash",
        f"latexmk {engine_flag} {main_file}",
        "```",
        "",
        "Or manually:",
        "",
        "```bash",
        f"{engine} {main_file}",
        f"bibtex {stem}      # only if the paper has a bibliography",
        f"{engine} {main_file}",
        f"{engine} {main_file}",
        "```",
        "",
        f"Main file: `{main_file}` · Engine: `{engine}`",
    ]
    problems = []
    for item in report.missing_inputs:
        problems.append(f"- Missing input file `{item['path']}` (referenced from `{item['from']}`, line {item['line']})")
    for item in report.missing_figures:
        problems.append(f"- Missing figure `{item['path']}` (referenced from `{item['from']}`, line {item['line']})")
    for item in report.missing_bibliographies:
        problems.append(f"- Missing bibliography `{item['path']}` (referenced from `{item['from']}`)")
    for key in report.undefined_citations:
        problems.append(f"- Citation key `{key}` is not defined in any bibliography file")
    if problems:
        lines += ["", "## Known issues at export time", "", *problems]
    return "\n".join(lines) + "\n"


def build_project_zip(
    texts: Mapping[str, str],
    binaries: Mapping[str, str],
    folders: Iterable[str],
    read_blob: Callable[[str], bytes],
    readme: str | None,
    root_folder: str,
) -> bytes:
    buf = io.BytesIO()
    prefix = f"{root_folder}/" if root_folder else ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(texts):
            zf.writestr(_zip_info(prefix + path), texts[path].encode("utf-8"))
        for path in sorted(binaries):
            zf.writestr(_zip_info(prefix + path), read_blob(binaries[path]))
        present_dirs = {str(PurePosixPath(p).parent) for p in list(texts) + list(binaries)}
        for folder in sorted(set(folders)):
            if folder not in present_dirs:
                zf.writestr(_zip_info(prefix + folder.rstrip("/") + "/"), b"")
        if readme is not None and "README.md" not in texts:
            zf.writestr(_zip_info(prefix + "README.md"), readme.encode("utf-8"))
    return buf.getvalue()


def build_assets_zip(binaries: Mapping[str, str], read_blob: Callable[[str], bytes], root_folder: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(binaries):
            zf.writestr(_zip_info(f"{root_folder}/{path}"), read_blob(binaries[path]))
    return buf.getvalue()


def flatten_latex(texts: Mapping[str, str], main_file: str, max_depth: int = 12) -> tuple[str, list[str]]:
    """Inline \\input/\\include recursively into one source file. Unresolvable inputs are kept and reported."""
    warnings: list[str] = []

    def resolve(target: str, base: str) -> str | None:
        target = target.strip()
        for cand in (str(PurePosixPath(base) / target) if base else target, target):
            while cand.startswith("./"):
                cand = cand[2:]
            for option in (cand, cand + ".tex"):
                if option in texts:
                    return option
        return None

    def expand(path: str, depth: int, stack: tuple[str, ...]) -> str:
        text = texts[path]
        masked = mask_comments(text)
        base = str(PurePosixPath(path).parent) if "/" in path else ""
        out: list[str] = []
        cursor = 0
        for m in _INPUT_RE.finditer(masked):
            out.append(text[cursor : m.start()])
            cursor = m.end()
            resolved = resolve(m.group(2), base)
            if resolved is None:
                warnings.append(f"Could not resolve \\{m.group(1)}{{{m.group(2)}}} in {path}; left unchanged.")
                out.append(text[m.start() : m.end()])
                continue
            if resolved in stack or depth >= max_depth:
                warnings.append(f"Recursive or too deeply nested input '{resolved}' left unchanged.")
                out.append(text[m.start() : m.end()])
                continue
            body = expand(resolved, depth + 1, stack + (resolved,))
            if m.group(1) == "include":
                out.append(f"\\clearpage\n% ---- begin {resolved} ----\n{body}\n% ---- end {resolved} ----\n\\clearpage")
            else:
                out.append(f"% ---- begin {resolved} ----\n{body}\n% ---- end {resolved} ----")
        out.append(text[cursor:])
        return "".join(out)

    if main_file not in texts:
        raise KeyError(main_file)
    return expand(main_file, 0, (main_file,)), warnings


def safe_download_name(name: str, default: str = "paper") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:80]
    return cleaned or default


def content_disposition(filename: str) -> str:
    return f'attachment; filename="{safe_download_name(filename)}"'
