"""Starter manuscript templates. They contain structure and instructions only, never content
that could be mistaken for research results or real citations."""

BLANK_MAIN = r"""\documentclass[11pt]{article}

\begin{document}

\end{document}
"""

ARTICLE_MAIN = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage[hidelinks]{hyperref}

\title{%(title)s}
\author{%(authors)s}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
% Summarise the problem, approach, and findings.
\end{abstract}

\section{Introduction}
\label{sec:introduction}

\section{Related Work}
\label{sec:related-work}

\section{Methodology}
\label{sec:methodology}

\section{Results}
\label{sec:results}

\section{Discussion}
\label{sec:discussion}

\section{Conclusion}
\label{sec:conclusion}

% Uncomment once references.bib contains entries and the text cites them with \cite{key}.
% \bibliographystyle{plain}
% \bibliography{references}

\end{document}
"""

IEEE_MAIN = r"""\documentclass[conference]{IEEEtran}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{cite}

\begin{document}

\title{%(title)s}

\author{\IEEEauthorblockN{%(authors)s}
\IEEEauthorblockA{\textit{Affiliation}}}

\maketitle

\begin{abstract}
% Summarise the problem, approach, and findings.
\end{abstract}

\begin{IEEEkeywords}
% keyword one, keyword two
\end{IEEEkeywords}

\section{Introduction}
\label{sec:introduction}

\section{Methodology}
\label{sec:methodology}

\section{Experiments}
\label{sec:experiments}

\section{Conclusion}
\label{sec:conclusion}

% \bibliographystyle{IEEEtran}
% \bibliography{references}

\end{document}
"""

STRUCTURED_MAIN = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage[hidelinks]{hyperref}
\graphicspath{{figures/}}

\title{%(title)s}
\author{%(authors)s}
\date{\today}

\begin{document}
\maketitle

\input{sections/abstract}
\input{sections/introduction}
\input{sections/methodology}
\input{sections/results}
\input{sections/conclusion}

% \bibliographystyle{plain}
% \bibliography{references}

\end{document}
"""

STRUCTURED_SECTIONS = {
    "sections/abstract.tex": "\\begin{abstract}\n% Summarise the problem, approach, and findings.\n\\end{abstract}\n",
    "sections/introduction.tex": "\\section{Introduction}\n\\label{sec:introduction}\n\n",
    "sections/methodology.tex": "\\section{Methodology}\n\\label{sec:methodology}\n\n",
    "sections/results.tex": "\\section{Results}\n\\label{sec:results}\n\n",
    "sections/conclusion.tex": "\\section{Conclusion}\n\\label{sec:conclusion}\n\n",
}

BIB_PLACEHOLDER = "% BibTeX entries for this manuscript.\n% Add entries here, or use \"Sync from library\" in the References panel.\n"

TEMPLATES = ("blank", "article", "ieee", "structured")


def _escape(value: str) -> str:
    out = []
    for ch in value:
        if ch in "&%$#_{}":
            out.append("\\" + ch)
        elif ch == "~":
            out.append("\\textasciitilde{}")
        elif ch == "^":
            out.append("\\textasciicircum{}")
        elif ch == "\\":
            out.append("\\textbackslash{}")
        else:
            out.append(ch)
    return "".join(out)


def _fill(template: str, values: dict[str, str]) -> str:
    # Plain replacement: templates contain LaTeX '%' comments, so printf-style formatting is unsafe.
    for key, value in values.items():
        template = template.replace(f"%({key})s", value)
    return template


def render_template(name: str, title: str, authors: list[str]) -> dict[str, str]:
    values = {"title": _escape(title), "authors": " \\and ".join(_escape(a) for a in authors) or "Author"}
    if name == "blank":
        return {"main.tex": BLANK_MAIN}
    if name == "ieee":
        values["authors"] = ", ".join(_escape(a) for a in authors) or "Author"
        return {"main.tex": _fill(IEEE_MAIN, values), "references.bib": BIB_PLACEHOLDER}
    if name == "structured":
        files = {"main.tex": _fill(STRUCTURED_MAIN, values), "references.bib": BIB_PLACEHOLDER}
        files.update(STRUCTURED_SECTIONS)
        return files
    return {"main.tex": _fill(ARTICLE_MAIN, values), "references.bib": BIB_PLACEHOLDER}
