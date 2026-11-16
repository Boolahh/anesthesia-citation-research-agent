"""Evidence-only citation extraction from Microsoft Copilot browser-print PDFs.

Copilot's browser print driver keeps its *navigation* hyperlinks but may omit
all medical publication URLs. Modern Edge printouts also contain a right-hand
"Sources" drawer, with clearly divided "Citations" and "More" lists. Only
the former is a bibliography. Missing URLs must never be inferred from the
source domain or a truncated headline.
"""
from __future__ import annotations

from urllib.parse import urlsplit
import re

import pymupdf as fitz


BADGE = re.compile(r'^[a-z][a-z0-9._\-…]{1,32}(?:\s+\+\d{1,2})?$', re.I)
DOMAIN = re.compile(r'^(?:[a-z0-9-]+\.)+[a-z0-9-]{2,}$', re.I)


def is_sidebar_link(uri):
    """Reject known Copilot app-navigation routes, including Cowork."""
    try:
        url = urlsplit(str(uri or ''))
        host = (url.hostname or '').lower().removeprefix('www.')
        path = url.path.rstrip('/') or '/'
        if host not in ('copilot.com', 'copilot.microsoft.com'):
            return False
        return (path in ('/', '/chat', '/cowork', '/search', '/chat/all',
                         '/library', '/library/all', '/projects',
                         '/agents', '/notebooks')
                or path.startswith(('/chat/conversation/', '/projects/')))
    except ValueError:
        return False


def is_viewport_print(pages):
    """Recognize browser-generated Copilot screen printouts."""
    return any(
        'Copilot is an AI and may make mistakes' in page.get_text()
        and any(is_sidebar_link(link.get('uri') or '')
                for link in page.get_links())
        for page in pages
    )


def cited_sources_panel(pages):
    """Transcribe only visible entries below "Citations", above "More".

    Returns None if NO explicit right-hand Citations panel is visible.
    Returns a list (possibly empty) if a panel exists. The URL is NR unless a
    genuine publication URI annotation overlaps *that exact displayed entry*.
    Title/domain are transcribed as they appear. A truncated title retains
    its ellipsis and is never expanded into an imagined bibliographic title.

    Do not use the "More" area, unrelated sidebar chat history, page body,
    or generic summary statements as citation candidates.
    """
    entries = []
    has_panel = False
    for page in pages:
        right_blocks = sorted(
            (b for b in page.get_text('blocks')
             if b[0] > page.rect.width * .80),
            key=lambda b: (b[1], b[0]),
        )
        starts = [
            b[1] for b in right_blocks
            if str(b[4]).strip().casefold() == 'citations'
        ]
        if not starts:
            continue
        has_panel = True
        start = min(starts)
        stop = min(
            (b[1] for b in right_blocks
             if b[1] > start and str(b[4]).strip().casefold()
             in ('more', 'suggested', 'related')),
            default=page.rect.height,
        )
        for block in right_blocks:
            x0, y0, x1, y1, text = block[:5]
            if not (start < y0 < stop and
                    x0 > page.rect.width * .85):
                continue
            displayed_lines = [line.strip() for line in text.splitlines()
                               if line.strip()]
            if len(displayed_lines) < 2:
                continue
            domain = displayed_lines[-1]
            if not DOMAIN.fullmatch(domain):
                continue
            visible_title = ' '.join(displayed_lines[:-1])
            if not visible_title:
                continue
            # A truncated "..." is still only a visible fragment, not a
            # complete title. It can safely appear in as-cited column D.
            truncated = ('…' in visible_title or
                         visible_title.endswith('...'))
            rect = fitz.Rect(x0, y0, x1, y1)
            source_urls = [
                str(link.get('uri') or '')
                for link in page.get_links()
                if str(link.get('uri') or '').lower().startswith(
                    ('https://', 'http://'))
                and not is_sidebar_link(link.get('uri') or '')
                and not (rect & fitz.Rect(link['from'])).is_empty
            ]
            # Never guess which of several links was intended. Usually
            # these print PDFs preserve zero scholarly URLs.
            url = source_urls[0] if len(set(source_urls)) == 1 else ''
            entries.append({
                'page': page.number + 1, 'x': x0, 'y': y0,
                'url': url,
                'citation': visible_title + ' — ' + domain,
                'kind': 'copilot_cited_source_panel',
                'confidence': 'review' if not url or truncated else 'high',
                'evidence': {
                    'page': page.number + 1,
                    'section': 'copilot_citations_panel',
                    'visible_title': visible_title,
                    'visible_domain': domain,
                    'title_is_truncated': truncated,
                    'source_url_in_pdf': bool(url),
                },
            })
    return entries if has_panel else None


def visible_unlinked_badges(pages):
    """Fallback for old Copilot PDFs with NO visible Citations panel.

    Transcribe only actually printed source badges, never hidden +N citations.
    A short source-domain badge without a hyperlink is not a source identity.
    """
    found = []
    for page in pages:
        actual_source_links = [
            fitz.Rect(link['from'])
            for link in page.get_links()
            if (link.get('uri') or '').lower().startswith(
                ('https://', 'http://'))
            and not is_sidebar_link(link.get('uri') or '')
        ]
        for block in page.get_text('dict').get('blocks', []):
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    label = ' '.join(str(span.get('text') or '').split())
                    rect = fitz.Rect(span['bbox'])
                    if not (6.8 <= span.get('size', 0) <= 8.6
                            and rect.x0 >= page.rect.width * .15
                            and page.rect.height*.12 <= rect.y0 <=
                            page.rect.height*.95
                            and BADGE.fullmatch(label)):
                        continue
                    if any((rect & dest).get_area() >=
                           .15*max(rect.get_area(), 1)
                           for dest in actual_source_links):
                        continue
                    found.append({
                        'page': page.number+1, 'x': rect.x0, 'y': rect.y0,
                        'citation': label, 'url': '',
                        'kind': 'copilot_visible_unlinked_badge',
                        'confidence': 'review',
                        'evidence': {
                            'page': page.number+1,
                            'section': 'inline_badge_unlinked',
                            'visible_badge': label,
                            'source_url_in_pdf': False,
                        },
                    })
    return found
