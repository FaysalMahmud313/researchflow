import html
import re
from html.parser import HTMLParser

ALLOWED_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "ul", "ol", "li",
    "strong", "b", "em", "i", "u", "code", "pre",
    "blockquote", "table", "thead", "tbody", "tr", "th", "td",
    "a", "hr", "br", "span",
})

ALLOWED_ATTRS = {
    "a": frozenset({"href", "title"}),
    "th": frozenset({"colspan", "rowspan"}),
    "td": frozenset({"colspan", "rowspan"}),
}

SAFE_URL_SCHEMES = ("http://", "https://", "mailto:", "#")

_DANGEROUS_BLOCK_RE = re.compile(
    r"<(script|style|iframe|object|embed|svg|math|form)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


class _SafeHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t not in ALLOWED_TAGS:
            return
        allowed_for_tag = ALLOWED_ATTRS.get(t, frozenset())
        rendered_attrs: list[str] = []
        for k, v in attrs:
            key = k.lower()
            if key.startswith("on") or key not in allowed_for_tag or v is None:
                continue
            val = v.strip()
            if key == "href":
                lower_val = val.lower()
                if not any(lower_val.startswith(scheme) for scheme in SAFE_URL_SCHEMES):
                    continue
            rendered_attrs.append(f' {key}="{html.escape(val, quote=True)}"')
        if t == "a" and any(a.startswith(" href=") for a in rendered_attrs):
            rendered_attrs.append(' rel="noopener noreferrer"')
        self.out.append(f"<{t}{''.join(rendered_attrs)}>")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ALLOWED_TAGS and t not in ("br", "hr"):
            self.out.append(f"</{t}>")

    def handle_data(self, data: str) -> None:
        self.out.append(html.escape(data, quote=False))


def sanitize_rich_text(raw_html: str) -> str:
    """Sanitize rich-text HTML against a strict allowlist to prevent stored XSS."""
    if not raw_html:
        return ""
    stripped = _DANGEROUS_BLOCK_RE.sub("", raw_html)
    parser = _SafeHTMLSanitizer()
    parser.feed(stripped)
    parser.close()
    return "".join(parser.out)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_plain_text(raw: str, max_length: int = 300) -> str:
    """Normalize user-supplied plain text (titles, comments). Rendered as text by the client, never as HTML."""
    if not raw:
        return ""
    return _CONTROL_CHARS_RE.sub("", raw).strip()[:max_length]
