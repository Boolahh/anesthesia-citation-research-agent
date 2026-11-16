"""Evidence-only parsing for PDFs printed from Microsoft's Copilot web UI.

The browser print driver saves clickable *sidebar navigation* to
copilot.com/chat, /search, /projects, etc., while the actual small grey
medical source badges typically have no preserved hyperlinks. Never pretend
navigation is a bibliography or expand a '+1' badge into unseen references.
"""
from __future__ import annotations

from urllib.parse import urlsplit
import re

import fitz


BADGE = re.compile(r'^[a-z][a-z0-9._\-…]{1,32}(?:\s+\+\d{1,2})?$', re.I)


def is_sidebar_link(uri):
    """Only known Copilot UI navigation routes; not linked medical sources."""
    try:
        url = urlsplit(str(uri or ''))
        host = (url.hostname or '').lower().removeprefix('www.')
        path = url.path.rstrip('/') or '/'
        if host not in ('copilot.com', 'copilot.microsoft.com'):
            return False
        return (path in ('/chat', '/search', '/chat/all', '/library',
                         '/library/all', '/projects')
                or path.startswith('/chat/conversation/'))
    except ValueError:
        return False


def is_viewport_print(pages):
    """Distinguish a screenshot-style web-print PDF from a complete export."""
    return any(
        'Copilot is an AI and may make mistakes' in page.get_text()
        and any(is_sidebar_link(link.get('uri') or '')
                for link in page.get_links())
        for page in pages
    )


def visible_unlinked_badges(pages):
    """Transcribe exact visible inline Copilot badge labels, with URL unknown.

    No inferred DOI, title, named source, citation count beyond visible
    occurrences, or fabricated link. An unexpanded '+1' stays literal.
    """
    found = []
    for page in pages:
        actual_source_links = [
            fitz.Rect(link['from'])
            for link in page.get_links()
            if (link.get('uri') or '').lower().startswith(('https://', 'http://'))
            and not is_sidebar_link(link.get('uri') or '')
        ]
        for block in page.get_text('dict').get('blocks', []):
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    label = ' '.join(str(span.get('text') or '').split())
                    rect = fitz.Rect(span['bbox'])
                    # Copilot's actual on-screen source badges in this format
                    # are 7.5pt grey labels inside the main answer region.
                    # Sidebar controls, response text, the input bar and
                    # hidden sources are deliberately excluded.
                    if not (6.8 <= span.get('size', 0) <= 8.6
                            and rect.x0 >= page.rect.width * .15
                            and page.rect.height*.12 <= rect.y0 <= page.rect.height*.95
                            and BADGE.fullmatch(label)):
                        continue
                    # If this badge has a real embedded hyperlink, the normal
                    # PDF URI extractor already owns it; do not duplicate.
                    if any((rect & dest).get_area() >=
                           .15*max(rect.get_area(), 1)
                           for dest in actual_source_links):
                        continue
                    found.append({
                        'page': page.number+1,
                        'x': rect.x0, 'y': rect.y0,
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
