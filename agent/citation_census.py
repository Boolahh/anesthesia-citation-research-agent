"""Independent citation-appearance and distinct-source census for each AI answer.

Do not change the extraction workbook counts: the newer preregistered study
rule counts each visible source *appearance*, including repeats. A distinct
link or bibliographic-list entry is a separate descriptive quantity, not a
second method for silently rewriting the primary outcome.
"""
from collections import defaultdict

from .pdf_extract import citation_identity


CITATION_CENSUS_FIELDS = [
    'tool', 'question', 'pdf_files', 'citation_occurrences',
    'distinct_citation_identities', 'distinct_linked_source_identities',
    'repeat_occurrences', 'bibliography_entries',
    'bibliography_distinct_sources', 'inline_link_occurrences',
    'unlinked_occurrences', 'review_note',
]


def citation_census_by_question(citations, documents=()):
    """Produce one reviewer-friendly row per tool/question, including zero exports."""
    groups = defaultdict(list)
    sources = defaultdict(set)
    for row in citations:
        key = row['tool'], row['question']
        groups[key].append(row)
        if row.get('source_file'):
            sources[key].add(str(row['source_file']))
    for doc in documents:
        key = doc.get('tool'), doc.get('question')
        if not all(key):
            continue
        groups.setdefault(key, [])
        if doc.get('file'):
            sources[key].add(str(doc['file']))
    output = []
    for key in sorted(groups):
        entries = groups[key]
        identities = {citation_identity(row) for row in entries}
        linked = [
            row for row in entries if row.get('url') not in ('', 'NR', None)
        ]
        bibliographies = [
            row for row in entries if row.get('source_context') == 'bibliography'
        ]
        bib_sources = {citation_identity(row) for row in bibliographies}
        links = {citation_identity(row) for row in linked}
        repeats = len(entries) - len(identities)
        inline = sum(row.get('source_context') == 'inline_link' for row in entries)
        no_url = len(entries) - len(linked)
        if not entries:
            note = ('No recoverable citations in export; confirm original chat '
                    'and PDF quality before treating this as zero references')
        elif not linked:
            note = ('PDF lacks linked source URLs: original chat may have '
                    'citation badges hidden or lost during export')
        elif repeats:
            note = ('A source linked repeatedly counts each time as an appearance; '
                    'do not interpret every appearance as a different publication')
        elif bibliographies:
            note = ('Bibliography entries are shown separately; a URL is not '
                    'proof that the source is a verified publication')
        else:
            note = ('Only cited source candidates can be counted; verify the '
                    'original conversation and linked source identities')
        output.append({
            'tool': key[0],
            'question': key[1],
            'pdf_files': ' | '.join(sorted(sources.get(key, ()))),
            'citation_occurrences': len(entries),
            'distinct_citation_identities': len(identities),
            'distinct_linked_source_identities': len(links),
            'repeat_occurrences': repeats,
            'bibliography_entries': len(bibliographies),
            'bibliography_distinct_sources': len(bib_sources),
            'inline_link_occurrences': inline,
            'unlinked_occurrences': no_url,
            'review_note': note,
        })
    return output
