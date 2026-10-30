import io
import unittest
import zipfile

from app.latex.analysis import DependencyReport, build_outline, find_citations, mask_comments
from app.latex.bibtex import parse_bibtex, serialize_entry
from app.latex.export import build_readme, flatten_latex
from app.latex.importer import ImportErrorWithReason, import_zip
from app.latex.paths import ManuscriptPathError, normalize_manuscript_path


class LatexUnitTests(unittest.TestCase):
    def test_paths_reject_traversal_and_hidden_files(self) -> None:
        self.assertEqual(normalize_manuscript_path("sections\\intro.tex"), "sections/intro.tex")
        for bad in ("../x.tex", "/etc/passwd", "a/../../b", ".env", "a/.git/config", "con\x00.tex", ""):
            with self.assertRaises(ManuscriptPathError, msg=bad):
                normalize_manuscript_path(bad)

    def test_comments_are_masked_but_escaped_percent_is_not(self) -> None:
        src = "100\\% done % hidden \\cite{x}\n\\cite{y}"
        self.assertEqual(len(mask_comments(src)), len(src))
        self.assertEqual(find_citations(src), ["y"])

    def test_outline_section_extents(self) -> None:
        src = "\\section{A}\na\n\\subsection{A1}\nx\n\\section{B}\nb\n\\bibliography{refs}\n\\end{document}"
        items = build_outline(src)
        a = next(i for i in items if i.title == "A")
        b = next(i for i in items if i.title == "B")
        self.assertEqual(src[a.start:a.end], "\\section{A}\na\n\\subsection{A1}\nx")
        self.assertEqual(src[b.start:b.end], "\\section{B}\nb")

    def test_bibtex_roundtrip_preserves_custom_fields(self) -> None:
        entries, errors = parse_bibtex('@Article{k1, title={A {B} c}, author="X and Y", year=2021, zz_custom={keep}}')
        self.assertFalse(errors)
        self.assertEqual(entries[0].entry_type, "article")
        out = serialize_entry(entries[0].entry_type, entries[0].key, entries[0].fields)
        again, _ = parse_bibtex(out)
        self.assertEqual(again[0].fields, entries[0].fields)

    def test_flatten_inlines_inputs_and_reports_missing(self) -> None:
        texts = {"main.tex": "A\n\\input{sec/one}\n\\input{nope}\nZ", "sec/one.tex": "ONE"}
        flat, warnings = flatten_latex(texts, "main.tex")
        self.assertIn("ONE", flat)
        self.assertIn("\\input{nope}", flat)
        self.assertEqual(len(warnings), 1)

    def test_export_readme_does_not_claim_compilation(self) -> None:
        readme = build_readme("Paper", "main.tex", "xelatex", DependencyReport())
        self.assertIn("has not been compiled", readme)
        self.assertIn("latexmk -xelatex main.tex", readme)

    def test_zip_bomb_and_entry_limits(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("main.tex", b"\0" * (5 * 1024 * 1024))
        with self.assertRaises(ImportErrorWithReason):
            import_zip(buf.getvalue(), max_entries=100, max_total_bytes=10 * 1024 * 1024)
        many = io.BytesIO()
        with zipfile.ZipFile(many, "w") as zf:
            for i in range(20):
                zf.writestr(f"f{i}.tex", "x")
        with self.assertRaises(ImportErrorWithReason):
            import_zip(many.getvalue(), max_entries=10, max_total_bytes=10**9)


if __name__ == "__main__":
    unittest.main()
