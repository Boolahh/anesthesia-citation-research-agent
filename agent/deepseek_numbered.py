"""Evidence-preserving DeepSeek numbered-PDF citation extraction.

DeepSeek exports may produce three nested hyperlinks for each visible citation.
A browser PDF page break can also shift link rectangles away from printed numbers.
Do not treat the "Found N web pages" indicator as N citations.
"""
from collections import defaultdict
import re

import fitz

NUMBER = re.compile(r'\d{1,3}')
FOUND = re.compile(r'Found\s+(\d+)\s+web\s+pages', re.I)


def _number_spans(page):
    out = []
    for block in page.get_text('dict', sort=True).get('blocks', []):
        if block.get('type') != 0:
            continue
        for line in block.get('lines', []):
            for span in line.get('spans', []):
                label = (span.get('text') or '').strip()
                if NUMBER.fullmatch(label) and span.get('size', 100) <= 8.5:
                    out.append((label, fitz.Rect(span['bbox'])))
    return out


def _link_groups(page):
    """Merge nested hitboxes, not separate occurrences of the same URL."""
    grouped = []
    items = [(str(item.get('uri') or ''), fitz.Rect(item['from']))
             for item in page.get_links()
             if str(item.get('uri') or '').startswith(('https://', 'http://'))]
    for url, rect in sorted(items, key=lambda item: -item[1].get_area()):
        match = None
        for group in grouped:
            if group['url'] != url:
                continue
            outer = group['outer']
            # Neighboring citation boxes can overlap; require containment.
            if ((outer & rect).get_area() >= rect.get_area() * .97
                    and rect.get_area() <= outer.get_area()):
                match = group
                break
        if match is None:
            grouped.append({'url': url, 'outer': rect, 'boxes': [rect]})
        else:
            match['boxes'].append(rect)
    return grouped


def extract_deepseek_numbered(pages):
    """Return observed citation occurrences and extraction-review warnings.

    An empty output means that the generic PDF extraction path should be tried.
    Source numbers, hyperlink URLs and occurrence counts are not fabricated.
    """
    output = []
    warnings = []
    numbers_to_urls = defaultdict(set)
    for page in pages:
        spans = _number_spans(page)
        groups = _link_groups(page)
        found = FOUND.search(page.get_text('text'))
        reported_limit = int(found.group(1)) if found else None
        for group in groups:
            box = min(group['boxes'], key=lambda rect: rect.get_area())
            x = (box.x0 + box.x1) / 2
            y = (box.y0 + box.y1) / 2
            candidates = []
            for label, word in spans:
                cx = (word.x0 + word.x1) / 2
                cy = (word.y0 + word.y1) / 2
                dx, dy = abs(cx - x), abs(cy - y)
                if dx > 3.0 or dy > 110:
                    continue
                if reported_limit is not None and int(label) > reported_limit:
                    continue
                candidates.append((dy > 9, dy, dx, label, word))
            candidates.sort(key=lambda item: (item[0], item[1], item[2]))
            if not candidates:
                warnings.append(
                    f'DeepSeek page {page.number+1}: printed source number not found '
                    'for a linked URI; manual review required')
                continue
            _, delta_y, _, label, word = candidates[0]
            if (len(candidates) > 1 and candidates[1][0] == candidates[0][0]
                    and abs(candidates[1][1] - candidates[0][1]) < 3):
                warnings.append(
                    f'DeepSeek page {page.number+1}: ambiguous linked source number; '
                    'manual review required')
                continue
            alignment = 'direct' if delta_y <= 7 else 'displaced_annotation'
            if alignment != 'direct':
                warnings.append(
                    f'DeepSeek page {page.number+1}: source {label} hyperlink displaced '
                    f'by {delta_y:.1f} PDF points; verify original linked source')
            source_number = int(label)
            numbers_to_urls[source_number].add(group['url'])
            output.append({
                'page': page.number+1, 'y': word.y0, 'x': word.x0,
                'url': group['url'], 'citation': label,
                'kind': 'deepseek_numbered_link',
                'confidence': 'high' if alignment == 'direct' else 'review',
                'evidence': {
                    'page': page.number+1, 'uri_annotation': group['url'],
                    'section': 'inline_link', 'source_number': source_number,
                    'link_rectangles_collapsed': len(group['boxes']),
                    'label_alignment': alignment,
                },
            })
    for number, urls in numbers_to_urls.items():
        if len(urls) > 1:
            warnings.append(
                f'DeepSeek source number {number} has {len(urls)} different URLs; '
                'review source identities')
    return sorted(output, key=lambda item: (item['page'], item['y'], item['x'])), warnings
