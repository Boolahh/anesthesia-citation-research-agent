"""Bounded, optional direct-PDF metadata inspection for cited source URLs.

Never use PDF text as proof that an AI citation is real. Only a plausible
embedded title that is also visible on the original PDF's first page may be
proposed, with an explicit manual-review flag. Do not archive source PDF bytes.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse, unquote
import re
import time
import unicodedata

import fitz
import requests

MAX_PDF_BYTES = 24_000_000  # opt-in; accommodates the ~17 MB 2025 ANZCA Blue Book
MAX_PDF_SECONDS = 45


def plausible_document_title(value):
    text = re.sub(r'\s+', ' ', str(value or '')).strip(' -|\t\r\n')
    if not 24 <= len(text) <= 220 or len(re.findall(r'[^\W\d_]{3,}', text, re.UNICODE)) < 2:
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


def _document_words(value):
    """Normalize the printed source filename and title without translating."""
    normalized = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return re.findall(r'[^\W_]+', normalized, re.UNICODE)


def filename_corroborated_title(url, visible_heading):
    """Conservative title proposal from TWO pieces of the *same PDF*.

    Only accept a prominent first-page heading whose normalized words
    exactly match the PDF's original filename. Neither establishes reality
    or authorship; the downstream field retains provisional provenance.
    """
    name = unquote(urlparse(url).path.rsplit('/', 1)[-1])
    if not name.lower().endswith('.pdf'):
        return ''
    stem = name[:-4]
    if (len(visible_heading) < 24 or
            re.search(r'^(?:document|download|attachment|file|report)\b',
                      visible_heading, re.I)):
        return ''
    head_words = _document_words(visible_heading)
    file_words = _document_words(stem)
    if len(head_words) < 3 or len(file_words) < 3:
        return ''
    return visible_heading if head_words == file_words else ''


def anzca_blue_book_frontmatter(doc, source_url):
    """Recognize an official ANZCA collected volume, not its chapters.

    Only the real publisher's Blue Book PDF path qualifies, AND the
    document's opening pages must independently mention both title and
    edition year. No editor is treated as a first author.
    """
    parsed = urlparse(source_url)
    if (parsed.hostname or '').lower() not in ('anzca.edu.au', 'www.anzca.edu.au'):
        return None
    filename = unquote(parsed.path.rsplit('/', 1)[-1]).lower()
    edition = re.fullmatch(r'(20\d{2})[_-]blue[_-]book(?:[_-]pdf)?\.pdf', filename)
    if not edition:
        return None
    year = edition.group(1)
    first_pages = ' '.join(
        doc[i].get_text('text')[:30000] for i in range(min(doc.page_count, 7)))
    if not (re.search(r'australasian\s+anaesthesia', first_pages, re.I)
            and re.search(r'\b'+year+r'\b', first_pages)):
        return None
    return {
        'title': f'Australasian Anaesthesia {year}',
        'publication_year': year,
        'document_kind': 'edited_book_compilation',
        'title_basis': ('publisher-hosted Blue Book PDF name corroborated by '
                        'its opening-page publication title and edition year'),
    }

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
                title_basis = ('embedded PDF title also visible on first page'
                               if title else '')
                collection = None
                if not title and review_hint:
                    title = filename_corroborated_title(url, review_hint)
                    if title:
                        title_basis = ('prominent PDF first-page heading exactly '
                                       'matches source filename; unverified')
                if not title:
                    collection = anzca_blue_book_frontmatter(doc, url)
                    if collection:
                        title = collection['title']
                        title_basis = collection['title_basis']
                result = {
                    'status': 'read', 'title': title,
                    'title_hint': review_hint,
                    'pages': doc.page_count,
                    'title_basis': title_basis or (
                        'prominent first-page heading for reviewer only'
                        if review_hint else 'no independently supported document title'),
                }
                if collection:
                    result['document_kind'] = collection['document_kind']
                    result['publication_year'] = collection['publication_year']
                return result
        except (fitz.FileDataError, ValueError, RuntimeError):
            return {'status': 'invalid_pdf'}
    return {'status': 'too_many_redirects'}
