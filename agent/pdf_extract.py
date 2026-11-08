"""Evidence-first extraction of citations from heterogeneous AI-response PDFs.

The source of truth is the content actually visible in the exported PDF. URLs
may come from PDF URI annotations or literal URL text, never from guessed IDs.
For unknown/incomplete layouts, preserve candidates plus explicit review warnings.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qsl, urlencode
import hashlib
import re

import fitz

DOI_RE = re.compile(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', re.I)
PMID_RE = re.compile(r'\bPMID\s*[:#]?\s*(\d{6,9})\b', re.I)
PMCID_RE = re.compile(r'\bPMC\d{5,10}\b', re.I)
URL_RE = re.compile(r'(?<![\w@])(?:https?://|www\.)[^\s<>\[\]"“”]+', re.I)
YEAR_RE = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')
REF_HEADER = re.compile(r'^\s*(?:\d+[).]?\s*)?(?:(?:key|selected|main|primary|suggested|important|additional|supporting|cited)\s+)?(?:references|citations|bibliography|guidelines(?:\s+and\s+references)?|sources\s+cited|cited\s+sources|sources)\s*:?[\s\-]*$', re.I)
UNUSED_HEADER = re.compile(r'\b(?:search results|search(?:ed|ing)? (?:sources|strategy)|sources (?:found|considered|reviewed|retrieved|searched)|further reading|recommended reading|related articles|other articles|suggested search|references not cited)\b', re.I)
STOP_HEADER = re.compile(r'^(?:bottom line|conclusion|summary|takeaways|key clinical takeaways|final answer|clinical recommendations|implementation|references not cited|sources searched|search results)\b', re.I)
LIST_START = re.compile(r'^\s*(?:\[(\d{1,3})\]|\((\d{1,3})\)|(\d{1,3})[.)]|[•●▪\-–])\s+(\S.+)$')
GENERIC_LINKS = {'full', 'article', 'full article', 'pubmed', 'pubmed central', 'pmc', 'doi', 'clinical review', 'ncbi bookshelf', 'read more', 'source', 'link', 'view article', 'asra pain medicine'}


def flatten_text(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def normalize(s):
    return re.sub(r'[^a-z0-9]+', '', str(s or '').lower())


def trim_tracking(url):
    return str(url or '').split('?', 1)[0].split('#', 1)[0]


def ids_as_shown(text, url):
    merged = f'{text} {unquote(str(url or ""))}'
    doi = DOI_RE.search(merged)
    pmid = PMID_RE.search(merged)
    if not pmid:
        pmid = re.search(r'(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d{6,9})(?:[/#?]|$)', str(url), re.I)
    return doi.group().rstrip('.,;)') if doi else 'NR', pmid.group(1) if pmid else 'NR'


def citation_identity(citation):
    """Normalize a single bibliographic identity without changing as-cited URLs.

    PMID/PMCID links from alternative NCBI hosts identify one source. Query
    parameters with real resource identifiers (e.g. WordPress ?p=1234) must
    be retained; only common tracking parameters may be dropped.
    """
    url = str(citation.get('url') or '')
    citation_text = str(citation.get('citation') or '')
    doi = DOI_RE.search(unquote(url)) or DOI_RE.search(citation_text)
    if doi:
        return 'doi:'+doi.group().rstrip('.,;)').casefold()
    pmid = re.search(
        r'(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d{6,9})(?:[/#?]|$)',
        url, re.I)
    pmid = pmid or PMID_RE.search(citation_text)
    if pmid:
        return 'pmid:'+pmid.group(1)
    pmcid = PMCID_RE.search(unquote(url)) or PMCID_RE.search(citation_text)
    if pmcid:
        return 'pmcid:'+pmcid.group().upper()
    if url and url != 'NR':
        parts = urlsplit(url)
        host = (parts.hostname or '').lower().removeprefix('www.')
        path = unquote(parts.path or '/').rstrip('/') or '/'
        tracking = ('utm_', 'fbclid', 'gclid', 'mc_cid', 'mc_eid', 'ref_', 'source')
        query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not any(k.lower().startswith(prefix) for prefix in tracking))
        return 'url:'+host+path+('?' + urlencode(query) if query else '')
    return 'text:'+normalize(citation_text)


def weak_visible_citation_label(label, url=''):
    """Identify linked labels that are insufficient as bibliographic titles.

    A domain badge like 'nysora', 'nih', or two-word phrase cannot be assumed
    to be the actual publication title. Preserve it, but lower extraction
    confidence for explicit reviewer attention.
    """
    label = flatten_text(label).strip(' .:;,')
    if not url or url == 'NR' or not label:
        return False
    if DOI_RE.search(label) or PMID_RE.search(label) or YEAR_RE.search(label):
        return False
    words = re.findall(r'[A-Za-z]{2,}', label)
    return len(label) < 28 and len(words) <= 3


def rough_fields(text, url):
    """Blue-column data is an *as-cited* transcription, not researched corrections."""
    doi, pmid = ids_as_shown(text, url)
    year = YEAR_RE.search(text)
    author = 'NR'
    m = re.match(r'^\s*(?:\[\d+\]|\d+[.)])?\s*([A-Z][\w\-\u00C0-\u024F ]{1,45}(?:\s+et al\.?)?)\s*[,.]', text)
    if m and (re.search(r'\bet al\b', m.group(1), re.I) or re.match(r'^[A-Z][a-z-]+\s+[A-Z]{1,3}\b', m.group(1))):
        author = m.group(1).strip()
    journal = 'NR'
    j = re.search(r'(?:\s+—\s+|\s+[-–]\s+)(NEJM|BJA Education|Anesthesia & Analgesia|Anesthesiology|CMAJ|JACC)(?:\b|,)', text, re.I)
    if j:
        journal = j.group(1)
    title = flatten_text(text[m.end():]).lstrip('.:, ') if author != 'NR' else text
    return {'citation': text or 'NR', 'title': title or 'NR', 'authors': author,
            'year': year.group() if year else 'NR', 'journal': journal,
            'doi': doi, 'pmid': pmid}


def page_lines(page):
    lines = []
    for block in page.get_text('dict', sort=True).get('blocks', []):
        if block.get('type') != 0:
            continue
        for line in block.get('lines', []):
            text = flatten_text(''.join(span.get('text', '') for span in line.get('spans', [])))
            if text:
                lines.append({'text': text, 'box': fitz.Rect(line['bbox'])})
    lines.sort(key=lambda x: (round(x['box'].y0, 1), x['box'].x0))
    return lines


def text_for_link(page, lines, boxes):
    """Recover link context from PDF text geometry, including generic link buttons."""
    if not lines:
        return ''
    first = min(boxes, key=lambda r: (r.y0, r.x0))
    idx = min(range(len(lines)), key=lambda i: (
        0 if not (lines[i]['box'] & first).is_empty else 1,
        abs(lines[i]['box'].y0-first.y0) + abs(lines[i]['box'].x0-first.x0)*.03))
    original = lines[idx]['text']
    all_words = page.get_text('words')
    anchor = flatten_text(' '.join(w[4] for b in boxes for w in all_words
        if not (fitz.Rect(w[:4]) & b).is_empty and
        (fitz.Rect(w[:4]) & b).get_area() >= .2 * max(fitz.Rect(w[:4]).get_area(), 1)))
    # A one-word lowercase linked domain badge (e.g. 'nysora', 'nih')
    # represents one as-displayed citation label, not its entire clinical
    # advice line. Two badges on the same line must remain two separate
    # appearances even when they share a URL. Generic 'Full article'
    # buttons remain eligible for reference-line context recovery below.
    if (anchor and anchor.lower() not in GENERIC_LINKS
            and len(anchor.split()) <= 2
            and (anchor.islower() or original.lower().count(anchor.lower()) > 1)
            and not LIST_START.match(original)):
        return anchor
    # Inline footnote markers are evidence of a citation, but not a complete
    # bibliographic reference. Preserve the marker instead of claiming the
    # surrounding medical advice is the publication title.
    if re.fullmatch(r'(?:\[?\d{1,3}\]?|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)', anchor.strip()):
        return anchor.strip()
    # A generic linked phrase on its *own* numbered reference line still
    # belongs to that line. Only borrow preceding text for a genuinely short
    # wrapped continuation (e.g. "Full" at the end of a line, "article" below).
    if idx and len(original) < 35 and (len(anchor) < 12 or anchor.lower() in GENERIC_LINKS):
        prior = lines[idx-1]
        if (not LIST_START.match(original)
                and 0 <= lines[idx]['box'].y0-prior['box'].y1 < 17
                and lines[idx]['box'].x0 > prior['box'].x0 + 6):
            original = prior['text']+' '+original
    if idx+1 < len(lines):
        nxt = lines[idx+1]
        if 0 <= nxt['box'].y0-lines[idx]['box'].y1 < 6 and not LIST_START.match(nxt['text']) and (
            nxt['text'].lower() in GENERIC_LINKS or original.endswith((',', ' and', ' of', 'Blood', 'Prediction,'))):
            original += ' '+nxt['text']
    return flatten_text(re.sub(r'^(?:(?:Key|Selected|Main|Primary) references)\s*:\s*', '', original, flags=re.I)).rstrip(' .')


def _section_for_position(lines, y, initial='body'):
    """Never code search-result dumps or explicitly uncited reading lists as citations."""
    state = initial
    for line in lines:
        if line['box'].y0 > y:
            break
        txt = line['text'].strip()
        if len(txt) < 100 and UNUSED_HEADER.search(txt):
            state = 'unused'
        elif len(txt) < 100 and REF_HEADER.match(txt):
            state = 'cited'
        elif len(txt) < 85 and STOP_HEADER.match(txt):
            state = 'body'
    return state


def extract_links(pages):
    groups = []
    carry_section = 'body'
    for pno, page in enumerate(pages):
        lines = page_lines(page)
        annotations = []
        for a in page.get_links():
            uri = (a.get('uri') or '').strip()
            if uri.lower().startswith(('https://', 'http://')):
                annotations.append((uri, fitz.Rect(a['from'])))
        by_url = defaultdict(list)
        for uri, rect in annotations:
            by_url[uri].append(rect)
        def line_near(rect):
            if not lines:
                return ''
            found = min(lines, key=lambda ln: (
                0 if not (ln['box'] & rect).is_empty else 1,
                abs(ln['box'].y0 - rect.y0)))
            return found['text']
        # URL equality does not mean one citation: Claude can print two
        # identical linked domain badges alongside each other on one line.
        # Conversely, a reference-list entry can wrap onto the next line
        # and produce two URI annotation rectangles for *one* citation.
        def linked_words(rect):
            words = page.get_text('words')
            return flatten_text(' '.join(
                word[4] for word in words if
                (fitz.Rect(word[:4]) & rect).get_area() >=
                .20 * max(fitz.Rect(word[:4]).get_area(), 1)))
        for uri, rects in by_url.items():
            clusters = []
            for rect in sorted(rects, key=lambda x: (x.y0, x.x0)):
                if clusters:
                    prior = clusters[-1][-1]
                    if (abs(rect.y0-prior.y0) < 1
                            and (rect & prior).get_area() >=
                            .85*min(rect.get_area(), prior.get_area())):
                        # Exact overlapping duplicate PDF annotations are
                        # rendering artifacts, not independent source badges.
                        continue
                    if (rect.y0 > prior.y0 + 6
                            and 0 <= rect.y0-prior.y1 <= 4
                            and abs(rect.x0-prior.x0) < 12
                            and _section_for_position(lines, prior.y0, carry_section) == 'cited'):
                        prev_text = linked_words(prior)
                        current_text = linked_words(rect)
                        # A second linked line is a continuation only when it
                        # isn't a new numbered reference or generic badge.
                        if (len(prev_text) >= 30 and len(current_text) >= 8
                                and not LIST_START.match(line_near(rect))
                                and prev_text.lower() not in GENERIC_LINKS
                                and current_text.lower() not in GENERIC_LINKS):
                            clusters[-1].append(rect)
                            continue
                clusters.append([rect])
            for cluster in clusters:
                rect = cluster[0]
                section = _section_for_position(lines, rect.y0, carry_section)
                if section == 'unused':
                    continue
                label = text_for_link(page, lines, cluster)
                groups.append({'page': page.number + 1, 'y': rect.y0,
                               'x': rect.x0, 'url': uri,
                               'citation': label,
                               'kind': 'pdf_link',
                               'confidence': ('review' if weak_visible_citation_label(label, uri)
                                              else 'high'),
                               'evidence': {'page': page.number+1, 'uri_annotation': uri,
                                            'section': ('bibliography' if section == 'cited'
                                                        else 'inline_link')}})
        if lines:
            carry_section = _section_for_position(lines, lines[-1]['box'].y1, carry_section)
    return sorted(groups, key=lambda x: (x['page'], x['y'], x['x']))


def _visible_url(text):
    m = URL_RE.search(text)
    if not m:
        return ''
    u = m.group(0).rstrip('.,;:!>\u201d\u2019')
    if u.count('(') < u.count(')'):
        u = u.rstrip(')')
    return ('https://' + u) if u.lower().startswith('www.') else u


def _plausible_reference(text):
    x = flatten_text(text)
    if len(x) < 16 or len(x) > 650 or REF_HEADER.match(x) or UNUSED_HEADER.search(x):
        return False
    if 'doi.org/' in x.lower() or PMID_RE.search(x) or PMCID_RE.search(x) or DOI_RE.search(x):
        return True
    if _visible_url(x) and len(x) >= 30:
        return True
    if YEAR_RE.search(x) and len(x) >= 26:
        return True
    if re.search(r'\b(?:guidelines?|consensus statement|systematic review|randomized|meta.analysis|trial|journal|et al\.)\b', x, re.I) and len(x) > 40:
        return True
    return False


def _plain_references(pages):
    """Split numbered and unnumbered bibliography entries with PDF line geometry.

    Claude often lists separate unnumbered sources 18-20pt apart and wraps
    individual titles 14-16pt apart. A continuous 33pt proximity rule merged
    entire source lists, silently losing unlinked references like MYRIAD.
    """
    out = []
    in_reference = False
    in_unused = False
    current = None

    def flush():
        nonlocal current
        if current is not None and (
                _plausible_reference(current['citation']) or
                (current.get('_explicit_section') and
                 len(current['citation']) >= 20 and
                 not current['citation'].startswith(('\ue056', '\ue06c')))):
            out.append(current)
        current = None

    for page in pages:
        lines = page_lines(page)
        linked_rectangles = [
            (fitz.Rect(link['from']), link.get('uri') or '')
            for link in page.get_links() if (link.get('uri') or '').startswith(('http://','https://'))
        ]
        def link_for_line(box):
            links = [url for rect, url in linked_rectangles
                     if (rect & box).get_area() > .2 * min(rect.get_area(), box.get_area())]
            return links[0] if links and len(set(links)) == 1 else ''
        # A section can span pages; the next section heading terminates it.
        for line in lines:
            text, rect = line['text'], line['box']
            if len(text) < 100 and UNUSED_HEADER.search(text):
                flush(); in_reference = False; in_unused = True
                continue
            if len(text) < 100 and REF_HEADER.match(text):
                flush(); in_reference = True; in_unused = False
                continue
            if in_unused:
                continue
            if in_reference and len(text) < 85 and STOP_HEADER.match(text):
                flush(); in_reference = False
                continue
            if not in_reference:
                continue
            # Do not accidentally turn Claude's export toolbar into a source.
            if text.startswith(('\ue056','\ue06c','\ue0e4')) or 'Create a doc' in text:
                flush(); in_reference = False
                continue
            start = LIST_START.match(text)
            raw = start.group(4) if start else text
            # A bibliography's separate unnumbered entries have a larger
            # baseline gap than a wrapped title. Require consistent indentation
            # for continuations, and always split explicit numbered entries.
            gap = rect.y0-current['_last_y0'] if current else 100
            same_indent = current and abs(rect.x0-current['_last_x0']) <= 14
            line_url = link_for_line(rect)
            # A 17pt gap can indicate a separate list entry when both lines
            # are independently linked to *different* URLs, as in Claude's
            # DAS page and NYSORA summary. Distinct link evidence wins over
            # font-dependent line-spacing heuristics.
            different_link = bool(current and current.get('_last_link_url')
                                  and line_url and current['_last_link_url'] != line_url)
            continuation = bool(
                current and not start and same_indent and not different_link and
                0 <= gap <= 17.4 and len(current['citation']) < 600)
            if continuation:
                current['citation'] += ' ' + text
                if not current['url']:
                    current['url'] = _visible_url(text)
            else:
                flush()
                if len(raw) < 12 and not _plausible_reference(raw):
                    continue
                current = {'page': page.number+1, 'x': rect.x0, 'y': rect.y0,
                           'citation': raw, 'url': _visible_url(raw),
                           'kind': 'plain_reference', 'confidence': 'medium',
                           '_explicit_section': True,
                           'evidence': {'page': page.number+1,
                                        'reference_label': text[:55],
                                        'section': 'bibliography'}
            if current is not None:
                current['_last_y0'] = rect.y0
                current['_last_x0'] = rect.x0
                if line_url:
                    current['_last_link_url'] = line_url
    flush()
    for item in out:
        for key in ('_last_y0','_last_x0','_last_link_url','_explicit_section'):
            item.pop(key, None)
    return out


def fallback_named_sources(pages):
    """Legacy conservative recovery for linkless prose citing explicit named sources."""
    full = flatten_text(' '.join(p.get_text() for p in pages))
    out = []
    for m in re.finditer(r'((?:First|Second|Third|Fourth|Fifth|Sixth) Consensus Guidelines\s+for\s+.{10,130}?\([^()]{8,120}?(?:19|20)\d{2}\))', full, re.I):
        out.append({'page': 0, 'x': 0, 'y': float(m.start()), 'citation': m.group(1),
                    'url': '', 'kind': 'explicit_named', 'confidence': 'low'})
    if 'The principal recommendations from recent guidelines are' in full:
        for i, m in enumerate(re.finditer(r'(?:20\d{2})\s+(?:ACC/AHA|POQI consensus|ESAIC|Association of Anaesthetists)', full, re.I)):
            if m.group(0) not in {x['citation'] for x in out}:
                out.append({'page': 0, 'x': 0, 'y': 100000+i,
                            'citation': m.group(0), 'url': '', 'kind': 'explicit_named', 'confidence': 'low'})
    return out


def _matches_reference(a, b):
    if a['page'] != b['page'] or abs(a['y']-b['y']) > 33:
        return False
    au = trim_tracking(a.get('url'))
    bu = trim_tracking(b.get('url'))
    if au and bu and au == bu:
        return True
    sa, sb = normalize(a['citation']), normalize(b['citation'])
    return bool(sa and sb and (sa in sb or sb in sa) and min(len(sa), len(sb)) > 17)


def _parse_pages(pages, tool, question, path, api=None):
    warnings = []
    annotations = extract_links(pages)
    references = _plain_references(pages)
    # Include uncaptured references, but never add the same entry once more
    # simply because its URL appears as visible text and as PDF annotation.
    found = list(annotations)
    for ref in references:
        matches = [a for a in annotations if _matches_reference(a, ref)]
        if matches:
            # Never replace a high-confidence single link label with a plain-
            # text block that spans *multiple* different linked references.
            # This happens when HTML-to-PDF places consecutive references on
            # neighboring baselines without numbering or blank lines.
            best = matches[0]
            ref_label = normalize(ref['citation'])
            other_sources = [a for a in annotations if a is not best
                             and a['page'] == ref['page']
                             and len(normalize(a['citation'])) >= 22
                             and normalize(a['citation']) in ref_label]
            if (not other_sources and len(ref['citation']) > len(best['citation'])
                    and len(ref['citation']) < 600):
                best['citation'] = ref['citation']
            if not best.get('url') and ref.get('url'):
                best['url'] = ref['url']
            if best.get('evidence') is not None:
                best['evidence']['section'] = 'bibliography'
            continue
        found.append(ref)
    found.sort(key=lambda x: (x['page'], x['y'], x['x']))
    if not found:
        found = fallback_named_sources(pages)
    text = '\n'.join(p.get_text(sort=True) for p in pages)
    text_n = normalize(text)
    collapsed = re.findall(r'(?<!\w)\+\s*\d{1,3}(?!\w)', text)
    if collapsed:
        warnings.append(f'Collapsed +N source labels ({len(collapsed)}) found; expand hidden citations before finalizing')
    if not text_n and not found:
        warnings.append('PDF has no selectable text or URI links; OCR/manual export is required')
    if api:
        try:
            proposed = api.extract_citations(text, found, tool, question)
            allowed_urls = {r.get('url') for r in found if r.get('url')}
            for item in proposed:
                citation = flatten_text(item.get('citation', ''))
                if not citation or len(normalize(citation)) < 20 or normalize(citation) not in text_n:
                    continue
                url = item.get('url', '')
                if url not in allowed_urls:
                    url = ''
                candidate = {'page': 0, 'x': 0, 'y': len(found)*1000,
                             'citation': citation, 'url': url,
                             'kind': 'ai_transcribed', 'confidence': 'review',
                             'evidence': {'source': 'exact PDF text'}}
                if not any(_matches_reference(candidate, a) or normalize(a['citation']) == normalize(citation) for a in found):
                    found.append(candidate)
        except Exception as exc:
            warnings.append('Optional AI extraction failed; deterministic sources kept: '+str(exc)[:150])
    if not found:
        warnings.append('No explicit citations recoverable; confirm original conversation and export format')
    if not any(g.get('url') for g in found):
        warnings.append('No clickable URLs found; no recoverable visible source URLs; review original export')
    results = []
    seen = set()
    for n, entry in enumerate(found, 1):
        raw = flatten_text(entry.get('citation', ''))
        url = entry.get('url') or 'NR'
        info = rough_fields(raw, url)
        identity = citation_identity({**info, 'url': url})
        repeated = 'Y' if identity in seen else 'N'
        seen.add(identity)
        results.append({'tool': tool, 'question': question, 'order': n,
                        'url': url, 'repeat': repeated, **info,
                        'source_file': path.name, 'source_page': entry.get('page', 0),
                        'extraction_method': entry.get('kind', 'unknown'),
                        'extraction_confidence': entry.get('confidence', 'review'),
                        'source_context': (entry.get('evidence') or {}).get(
                            'section', 'named_source_mention' if entry.get('kind') == 'explicit_named'
                            else 'unclassified'),
                        'evidence': entry.get('evidence') or {'page': entry.get('page', 0)}})
    return results, warnings


def _question_matches(text, questions):
    normalized = normalize(text)
    return [key for key, q in questions.items() if normalize(q) in normalized or (
        len(normalize(q)) > 60 and normalize(q)[:65] in normalized)]


QUESTION_HINTS = {
    'Q01': ('ponv', 'postoperative nausea', 'nausea vomiting'),
    'Q02': ('intraoperative hypotension', 'prevent hypotension', 'blood pressure management'),
    'Q03': ('intraoperative hemorrhage', 'intraoperative haemorrhage', 'massive hemorrhage', 'massive haemorrhage'),
    'Q04': ('last toxicity', 'local anesthetic systemic toxicity', 'local anaesthetic systemic toxicity'),
    'Q05': ('difficult airway', 'awake tracheal intubation'),
    'Q06': ('one lung ventilation', 'one-lung ventilation', 'olv hypoxemia', 'olv hypoxaemia'),
    'Q07': ('cesarean anesthesia', 'caesarean anaesthesia', 'cesarean delivery'),
    'Q08': ('acute kidney injury', 'aki risk', 'kidney injury prevention', 'kidney injury risk'),
    'Q09': ('postoperative delirium', 'delirium risk'),
    'Q10': ('tonsillectomy', 'recent upper respiratory infection', 'urti'),
    'Q11': ('cabg', 'coronary artery bypass', 'volatile vs tiva', 'volatile anesthesia comparison'),
    'Q12': ('intracranial pressure', 'craniotomy', 'elevated icp', 'raised icp'),
}


def heuristic_question(filename, pages):
    # Filename is a stronger signal than narrative content, which can mention
    # other anesthetic subspecialties incidentally. Require one unambiguous hit.
    for sample in (filename, ' '.join(p.get_text(sort=True)[:650] for p in pages[:1])):
        tokenized = re.sub(r'[^a-z0-9]+', ' ', sample.lower()).strip()
        matches = [code for code, hints in QUESTION_HINTS.items()
                   if any(re.sub(r'[^a-z0-9]+', ' ', hint.lower()).strip() in tokenized for hint in hints)]
        if len(matches) == 1:
            return matches[0]
    return None


def get_question_for_file(pages, questions, filename):
    matches = _question_matches(' '.join(p.get_text() for p in pages[:2]), questions)
    m = re.search(r'(?i)(?:^|[_\s\-.])Q\s*0?([1-9]|1[0-2])(?:[^0-9]|$)', filename)
    if m:
        key = f'Q{int(m.group(1)):02d}'
        return key, (['Filename question differs from visible question; review mapping'] if matches and key not in matches else [])
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, [f'Multiple questions detected {matches}; name file Q01_*.pdf or split exports']
    fallback = heuristic_question(filename, pages)
    if fallback:
        return fallback, [f'Question {fallback} inferred from filename/heading keywords; confirm against actual study prompt']
    return None, ['Cannot identify one of the 12 study questions; name file Q01_*.pdf, etc.']


def inspect_unresolved_pdf(path):
    """Context-only diagnostics for PDFs yielding no citation candidates.

    Never copy clinical text to logs. Filename topic mapping is only a hint:
    identifying a question is NOT evidence that the AI supplied a citation.
    """
    filename = Path(path).stem
    with fitz.open(str(path)) as document:
        pages = len(document)
        text_chars = 0
        uri_links = 0
        image_pages = 0
        for page in document:
            text_chars += len(page.get_text('text'))
            uri_links += sum(bool((link.get('uri') or '').lower().startswith(
                ('https://', 'http://'))) for link in page.get_links())
            image_pages += bool(page.get_images(full=False))
        return {
            'page_count': pages,
            'selectable_text_characters': text_chars,
            'uri_link_annotations': uri_links,
            'pages_containing_images': image_pages,
            'possible_image_only_export': bool(
                pages and text_chars < 25 and image_pages > 0),
            'question_inferred_from_filename': heuristic_question(filename, []),
        }


def parse_pdf(path, tool, questions, api=None):
    path = Path(path)
    with fitz.open(str(path)) as doc:
        if len(doc) == 0:
            return [], ['Empty PDF']
        if len(doc) > 500:
            return [], ['PDF exceeds 500-page safety limit; split exports']
        pages = list(doc)
        changes = []
        for i, page in enumerate(pages):
            hits = _question_matches(page.get_text(sort=True)[:1600], questions)
            if len(hits) == 1 and (not changes or hits[0] != changes[-1][1]):
                changes.append((i, hits[0]))
        if len(changes) > 1:
            results, warnings = [], []
            for i, (start, question) in enumerate(changes):
                end = changes[i+1][0] if i+1 < len(changes) else len(pages)
                group, w = _parse_pages(pages[start:end], tool, question, path, api)
                results.extend(group)
                warnings.extend(f'{question}: {msg}' for msg in w)
            if changes[0][0] > 0:
                warnings.append('Pages before the first question were not attributed')
            return results, warnings
        question, warnings = get_question_for_file(pages, questions, path.stem)
        if not question:
            return [], warnings
        return_rows, extra = _parse_pages(pages, tool, question, path, api)
        return return_rows, warnings+extra
