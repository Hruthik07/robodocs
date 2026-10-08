"""Docs-website HTML (Sphinx, pydata/NVIDIA theme) -> Markdown.

Keeps: headings, paragraphs, lists, tables, code blocks (with language), image alt text.
Drops: navigation, header/footer, scripts, '#' heading anchors, copy buttons.
"""

import re

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

DROP_SELECTORS = ["script", "style", "nav", "header", "footer", "a.headerlink", "button",
                  ".copybtn", ".prev-next-area", ".bd-footer-article", ".toc-entry"]


class _Converter(MarkdownConverter):
    def convert_pre(self, el, text, *args, **kwargs):
        # Sphinx puts the language on a wrapper: <div class="highlight-python"><div class="highlight"><pre>
        lang = ""
        for parent in el.parents:
            for cls in parent.get("class") or []:
                if cls.startswith("highlight-"):
                    lang = cls.removeprefix("highlight-")
            if lang:
                break
        code = el.get_text().rstrip("\n")
        return f"\n\n```{lang if lang not in ('default', 'none', 'text') else ''}\n{code}\n```\n\n"

    def convert_img(self, el, text, *args, **kwargs):
        alt = (el.get("alt") or "").strip()
        return f"[image: {alt or 'figure'}]"


def html_to_markdown(html: str) -> tuple[str, str]:
    """Return (title, markdown) for the main article of a docs page."""
    soup = BeautifulSoup(html, "lxml")
    article = soup.select_one("article") or soup.select_one("main") or soup.body or soup
    for sel in DROP_SELECTORS:
        for el in article.select(sel):
            el.decompose()
    h1 = article.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "")
    # No escaping: "ROS\_GenericPub" would break exact matching on identifiers developers search for.
    md = _Converter(heading_style="ATX", bullets="-", escape_underscores=False,
                    escape_asterisks=False, escape_misc=False).convert_soup(article)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return title, md
