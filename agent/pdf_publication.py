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

MAX_PDF_BYTES = 10_000_000
MAX_PDF_SECONDS = 30


def plausible_document_title(value):
    text = re.sub(r'\s+', ' ', str(value or '')).strip(' -|\t\r\n')
    if not 24 <= len(text) <= 220 or len(re.findall(r'[A-Za-z]{3,}', text)) < 4:
        return ''
    if re.search(r'\b(?:microsoft word|untitled|document\d*|scanner|scan copy|'
                 r'adobe acrobat|page [0-9]+|access denied|draft cover)\b', text, re.I):
        return ''
    return text


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
                return {'status': 'read', 'title': title,
                        'pages': doc.page_count,
                        'title_basis': 'embedded PDF title also visible on first page'
                        if title else 'no independently supported document title'}
        except (fitz.FileDataError, ValueError, RuntimeError):
            return {'status': 'invalid_pdf'}
    return {'status': 'too_many_redirects'}
