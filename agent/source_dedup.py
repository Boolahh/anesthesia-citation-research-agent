"""One workbook row per distinct as-cited source per model and question.

Keep *all* original citation appearances available in separate audit exports.
Never merge separate questions or platforms. Source identity is based on an
explicit identifier or original linked URL; ambiguous links are NOT guessed to
be identical on title similarity alone.
"""
from collections import OrderedDict
import re

from .pdf_extract import citation_identity, DOI_RE


def source_key(item):
    """Conservative source identity for deduplication and older XLSX rows."""
    # The same as-cited hyperlink can accompany a short in-text badge AND
    # a longer bibliography entry containing a DOI. Treat that as one linked
    # source. The URL is the common original evidence; publication identity
    # conflicts are left to the reviewer, never silently adjudicated.
    url = str(item.get('url') or '')
    label = str(item.get('citation') or '')
    # Two identical *truncated* Copilot sidebar titles/domains are not proof
    # of one publication. They may be two different records clipped to the
    # same prefix. Retain separately until actual original URLs are obtained.
    if (url in ('', 'NR', 'NOT FOUND') and
            ('…' in label or '...' in label) and
            ('source_context' in item and
             item['source_context'] == 'copilot_citations_panel'
             or ' — ' in label)):
        return ('copilot-clipped-candidate:' +
                str(item.get('order') or item.get('excel_row') or '') +
                ':' + citation_identity({'citation': label}))
    key = (citation_identity({'url': url, 'citation': ''})
           if url not in ('', 'NR', 'NOT FOUND') else citation_identity(item))
    if key.startswith('text:'):
        # Prefer an explicitly as-cited identifier if no linked URL was
        # retained by the PDF. Never substitute researched green metadata.
        doi = DOI_RE.search(str(item.get('doi') or ''))
        if doi:
            return 'doi:' + doi.group().rstrip('.,;)').casefold()
        pmid = re.fullmatch(r'\d{6,9}', str(item.get('pmid') or ''))
        if pmid:
            return 'pmid:' + pmid.group()
        if len(key.removeprefix('text:')) < 18:
            # A badge "source", "NR", or "nih" without a URL cannot establish
            # that two occurrences identify the same publication.
            return 'unresolved:' + '|'.join(map(str, (
                item.get('source_file') or '',
                item.get('source_page') or '',
                item.get('order') or item.get('excel_row') or '',
            )))
    return key


def _preference(item):
    """Select the clearest originally visible citation, not a researched title."""
    title = str(item.get('citation') or '')
    is_bibliography = item.get('source_context') == 'bibliography'
    has_full_reference = len(title) >= 35 and len(title.split()) >= 5
    return (
        bool(is_bibliography and has_full_reference),
        has_full_reference,
        is_bibliography,
        len(title),
    )


def unique_question_sources(appearances):
    """Return distinct workbook rows, retaining raw appearance counts.

    This function does not change appearance records, allowing a faithful
    original transcript to be stored in citation_occurrences_raw.json.
    """
    grouped = OrderedDict()
    for item in appearances:
        identity = (item['tool'], item['question'], source_key(item))
        if identity not in grouped:
            grouped[identity] = {
                'chosen': item,
                'count': 0,
                'appearance_orders': [],
                'source_files': set(),
            }
        group = grouped[identity]
        group['count'] += 1
        group['appearance_orders'].append(int(item['order']))
        if item.get('source_file'):
            group['source_files'].add(item['source_file'])
        if _preference(item) > _preference(group['chosen']):
            group['chosen'] = item
    numbers = {}
    output = []
    for (tool, question, _), group in grouped.items():
        key = tool, question
        numbers[key] = numbers.get(key, 0) + 1
        chosen = dict(group['chosen'])
        chosen['order'] = numbers[key]
        chosen['repeat'] = 'Y' if group['count'] > 1 else 'N'  # repeated within answer
        chosen['occurrence_count'] = group['count']
        chosen['original_appearance_orders'] = group['appearance_orders']
        chosen['original_source_files'] = sorted(group['source_files'])
        output.append(chosen)
    return output
