"""Bounded, optional direct-PDF metadata inspection for cited source URLs.

Never use PDF text as proof that an AI citation is real. Only a plausible
embedded title that is also visible on the original PDF's first page may be
proposed, with an explicit manual-review flag. Do not archive source PDF bytes.
"""
from __future__ import annotations

from urllib.parse import urljoin
import re
import time

import fitz
import requests

MAX_PDF_BYTES = 24_000_000  # opt-in; accommodates the ~17 MB 2025 ANZCA Blue Book
MAX_PDF_SECONDS = 45


def plausible_document_title(value):
    text = re.sub(r'\s+', ' ', str(value or '')).strip(' -|\t\r\n')
    if not 24 <= len(text) <= 220 or len(re.findall(r'[A-Za-z]{3,}', text)) < 4:
        return ''
    if re.search(r'\b(?:microsoft word|untitled|document\d*|scanner|scan copy|'
                 r'adobe acrobat|page [0-9]+|access denied|draft cover)\b', text, re.I):
        return ''
    return text



def visible_first_page_title_hint(page):
    """Extract only an *unverified review hint* from a prominent heading.

    Never promote this hint to an as-cited title or independent paper identity.
    PDF first-page typography is not proof of publication metadata.
    """
    spans = []
    doc = page.get_text('dict')
    for block in doc.get('blocks', []):
        if block.get('type') != 0:
            continue
        for line in block.get('lines', []):
            parts = [span for span in line.get('spans', [])
                     if str(span.get('text') or '').strip()]
            if not parts:
                continue
            text = ' '.join(part.get('text', '').strip() for part in parts).strip()
            size = max(float(part.get('size') or 0) for part in parts)
            top = min(float(part['bbox'][1]) for part in parts)
            if (24 <= len(text) <= 200 and
                    len(re.findall(r'[^\W\d_]{3,}', text, re.UNICODE)) >= 3 and
                    top < page.rect.height * .48 and size >= 13):
                spans.append((size, top, text))
    if not spans:
        return ''
    # Require clear typographic emphasis; skip ordinary paragraphs and
    # generic covers so only unusually prominent text is reported for review.
    spans.sort(key=lambda x: (-x[0], x[1]))
    highest = spans[0]
    if highest[0] < 15:
        return ''
    value = highest[2]
    if re.search(r'^(?:contents|table of contents|references|'
                 r'acknowledgements|introduction|version\s+\d+)\b',
                 value, re.I):
        return ''
    return value

def inspect_public_pdf(url, session, safe_destination, max_bytes=MAX_PDF_BYTES,
                       total_seconds=MAX_PDF_SECONDS):
    """Return minimal PDF bibliographic hints; no arbitrary URL or PDF text stored.

    A safe_destination(url) callback revalidates public DNS on *every* hop.
    One direct attempt, no retry storm, no full-text extraction.
    """
    start = time.monotonic()
    address = url
    for _ in range(4):
        if not safe_destination(address):
            return {'status': 'blocked_url'}
        try:
            with session.get(address, timeout=(5, 12), allow_redirects=False,
                             stream=True, headers={'Accept':'application/pdf'}) as resp:
                if resp.is_redirect:
                    address = urljoin(address, resp.headers.get('Location', ''))
                    continue
                if resp.status_code != 200:
                    return {'status': 'http_'+str(resp.status_code)}
                chunks = bytearray()
                for part in resp.iter_content(65536):
                    if time.monotonic()-start > total_seconds:
                        return {'status': 'time_budget_exceeded'}
                    chunks.extend(part)
                    if len(chunks) > max_bytes:
                        return {'status': 'too_large'}
                if not chunks.startswith(b'%PDF'):
                    return {'status': 'not_pdf'}
        except requests.RequestException:
            return {'status': 'network_error'}
        try:
            with fitz.open(stream=bytes(chunks), filetype='pdf') as doc:
                if not doc.page_count:
                    return {'status': 'empty_pdf'}
                title = plausible_document_title((doc.metadata or {}).get('title'))
                if title:
                    visible = re.sub(r'\s+', '', doc[0].get_text('text').casefold())
                    quoted = re.sub(r'\s+', '', title.casefold())
                    if quoted not in visible:
                        title = ''
                review_hint = (visible_first_page_title_hint(doc[0])
                               if not title else '')
                return {'status': 'read', 'title': title,
                        'title_hint': review_hint,
                        'pages': doc.page_count,
                        'title_basis': 'embedded PDF title also visible on first page'
                        if title else 'prominent first-page heading for reviewer only'
                        if review_hint else 'no independently supported document title'}
        except (fitz.FileDataError, ValueError, RuntimeError):
            return {'status': 'invalid_pdf'}
    return {'status': 'too_many_redirects'}
