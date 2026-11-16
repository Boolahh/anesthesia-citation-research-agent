"""Only visible Gemini source chips are citation candidates in browser-print PDFs.

Browser print views may preserve Google account/app links while silently
omitting article citations. Never reconstruct missing source URLs from a
publisher label or clinical prose. A +N chip is a group containing unseen
sources, NOT N identified publications.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

import pymupdf as fitz


_VISIBLE_SOURCE = re.compile(
    r"^(?:PMC(?:\s*[-–]\s*NIH)?|PubMed(?:\s*[-–]\s*NIH)?|"
    r"PubMed Central|ResearchGate|Google Scholar|ScienceDirect|"
    r"Cochrane|Elsevier|Springer(?:Link)?|Wiley|BMJ|JAMA|"
    r"The Lancet|NEJM|NIH|Medscape|UpToDate|"
    r"World Health Organization|WHO|"
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
    r"(?:\s*\+\s*\d{1,2})?$",
    re.I,
)


def is_gemini_interface_url(uri):
    """Known Gemini/Google UI navigation links, never medical citations."""
    try:
        parsed = urlsplit(str(uri or ''))
        host = (parsed.hostname or '').lower().removeprefix('www.')
        path = parsed.path.lower()
        if host in ('gemini.google.com', 'accounts.google.com'):
            return True
        if (host in ('google.com', 'google.ca', 'google.co.uk')
                and path.startswith('/intl/')
                and path.endswith('/about/products')):
            return True
        return False
    except ValueError:
        return False


def is_gemini_browser_print(pages):
    """Gemini on-screen print has its Google Apps and account URI controls."""
    return any(
        any((urlsplit(str(link.get('uri') or '')).hostname or '')
            == 'accounts.google.com' and
            'gemini.google.com' in str(link.get('uri') or '')
            for link in page.get_links())
        for page in pages
    )


def gemini_visible_source_badges(pages):
    """Return only source chips with direct visible evidence in the PDF.

    The PDF may show a label such as 'PMC - NIH' but not the cited article.
    Preserve the label exactly and return URL unknown, except if a genuine
    scholarly URI annotation overlaps this specific badge.
    """
    result = []
    seen = set()
    for page in pages:
        source_links = [
            (fitz.Rect(link['from']), str(link.get('uri') or ''))
            for link in page.get_links()
            if str(link.get('uri') or '').lower().startswith(('http://', 'https://'))
            and not is_gemini_interface_url(link.get('uri'))
        ]
        for block in page.get_text('dict').get('blocks', []):
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                spans = [span for span in line.get('spans', [])
                         if str(span.get('text') or '').strip()]
                if not spans:
                    continue
                visible = ' '.join(''.join(span['text'] for span in
                                           line.get('spans', [])).split())
                rectangle = fitz.Rect(line['bbox'])
                if not (
                    page.rect.width*.35 <= rectangle.x0 <= page.rect.width*.75
                    and page.rect.height*.04 <= rectangle.y0 <= page.rect.height*.92
                    and all(8.0 <= span.get('size', 0) <= 11.2 for span in spans)
                    and _VISIBLE_SOURCE.fullmatch(visible)
                ):
                    continue
                # Chrome PDF exports sometimes store the same selectable
                # text twice at identical coordinates. Not two sources.
                geometry_key = (page.number, visible.casefold(),
                                round(rectangle.x0), round(rectangle.y0))
                if geometry_key in seen:
                    continue
                seen.add(geometry_key)
                matched = [link for rect, link in source_links
                           if (rectangle & rect).get_area() >=
                           .1*max(1.0, rectangle.get_area())]
                url = matched[0] if len(set(matched)) == 1 else ''
                result.append({
                    'page': page.number+1, 'x': rectangle.x0, 'y': rectangle.y0,
                    'citation': visible, 'url': url,
                    'kind': 'gemini_visible_source_badge',
                    'confidence': 'high' if url else 'review',
                    'evidence': {
                        'page': page.number+1,
                        'section': 'gemini_inline_source_badge',
                        'visible_badge': visible,
                        'source_url_in_pdf': bool(url),
                        'collapsed_group_unexpanded': bool(
                            re.search(r'\+\s*\d+$', visible)),
                    },
                })
    return result
