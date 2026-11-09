"""Research coverage and source access reports, never investigator verdicts.

A citation occurrence and a candidate publication are not interchangeable.
These reviewer-oriented tables preserve every original source URL and count.
"""
from collections import defaultdict
from urllib.parse import urlparse
import re

from .pdf_extract import citation_identity


GEO_SOURCE_FIELDS = [
    'tool', 'question', 'candidate_identity', 'candidate_identity_basis',
    'citation_occurrences', 'citation_orders', 'linked_source_identities',
    'first_author', 'first_author_countries', 'country_evidence_class',
    'country_evidence_urls', 'title_proposals', 'review_priority', 'review_action',
]

ACCESS_REVIEW_FIELDS = [
    'tool', 'question', 'source_identity', 'citation_occurrences',
    'citation_orders', 'original_urls', 'source_access_category',
    'source_domain', 'research_status', 'source_document_status',
    'source_document_title_hint', 'priority', 'review_action',
]

EMPTY = ('', 'NR', 'NOT FOUND', None)


def _citation_key(item):
    return item['tool'], item['question'], int(item['order'])


def _unique(values):
    return ' | '.join(dict.fromkeys(str(x).strip() for x in values
                                   if x not in EMPTY and str(x).strip()))


def geography_candidate_sources(rows, proposals):
    """Count identifier-grouped first-author country *candidates*.

    Same DOI or PMID can connect different original hyperlinks; blue citation
    occurrences never get collapsed. Title-only records are NOT merged on a
    guessed title. Conflicting country evidence is highlighted, not resolved.
    """
    mapped = {_citation_key(p): p for p in proposals}
    grouped = defaultdict(list)
    for item in rows:
        proposal = mapped.get(_citation_key(item)) or {}
        f = proposal.get('fields') or {}
        country = f.get('AN')
        if country in EMPTY or not proposal.get('written_to_workbook'):
            continue
        ids = proposal.get('identifiers') or {}
        doi = str(ids.get('doi') or f.get('AB') or '').strip().lower()
        pmid = str(ids.get('pmid') or f.get('AC') or '').strip()
        if doi.upper() in ('NR', 'NOT FOUND'): doi = ''
        if pmid.upper() in ('NR', 'NOT FOUND'): pmid = ''
        if doi:
            resolved = 'doi:' + doi
            basis = 'provisional DOI'
        elif pmid.isdigit():
            resolved = 'pmid:' + pmid
            basis = 'provisional PMID'
        else:
            resolved = 'original_link:' + citation_identity(item)
            basis = 'original linked source (no verified bibliographic ID)'
        grouped[(item['tool'], item['question'], resolved, basis)].append((item, proposal))

    results = []
    for (tool, question, identity, basis), members in sorted(grouped.items()):
        countries = sorted({str((p.get('fields') or {}).get('AN'))
                            for _, p in members})
        provenances = [(p.get('field_provenance') or {}).get('AN') or {}
                       for _, p in members]
        authors = [(p.get('fields') or {}).get('AL') for _, p in members]
        source_types = {v.get('source', '') for v in provenances}
        inferred = any('OpenAlex' in type_name for type_name in source_types)
        conflicts = len(countries) != 1
        results.append({
            'tool': tool, 'question': question,
            'candidate_identity': identity, 'candidate_identity_basis': basis,
            'citation_occurrences': len(members),
            'citation_orders': _unique(item['order'] for item, _ in members),
            'linked_source_identities': _unique(citation_identity(item) for item, _ in members),
            'first_author': _unique(authors),
            'first_author_countries': ' | '.join(countries),
            'country_evidence_class': ('conflicting' if conflicts else
                                       'OpenAlex inferred (human review)' if inferred else
                                       'PubMed author-specific affiliation'),
            'country_evidence_urls': _unique(v.get('url') for v in provenances),
            'title_proposals': _unique((p.get('fields') or {}).get('Z') for _, p in members),
            'review_priority': 'High' if conflicts else 'Review',
            'review_action': (
                'Conflicting countries for one candidate paper: do not select automatically'
                if conflicts else
                'Verify matched publication, author position, affiliation and country; '
                'do not equate repeated occurrences with independent publications'),
        })
    return results


def source_access_review(rows, proposals):
    """One action per unresolved original linked source, not per occurrence."""
    mapped = {_citation_key(p): p for p in proposals}
    grouped = defaultdict(list)
    for item in rows:
        p = mapped.get(_citation_key(item))
        if not p or p.get('written_to_workbook'):
            continue
        grouped[(item['tool'], item['question'], citation_identity(item))].append((item, p))

    result = []
    for (tool, question, source_identity), members in grouped.items():
        urls = [str(item.get('url') or '') for item, _ in members]
        parsed = urlparse(urls[0])
        path = parsed.path.lower()
        doc_info = [(p.get('source_document') or {}) for _, p in members]
        reason = str((members[0][1].get('match') or {}).get('status') or '')
        if reason == 'non_source_search_results':
            category = 'search_results_not_single_publication'
            action = 'Review whether the AI cited a search listing rather than a specific publication'
            priority = 'High'
        elif (path.endswith('.pdf') or '/surrogate' in path or
              '/getcontentasset/' in path or '/dl-' in path):
            category = 'downloadable_document_or_pdf'
            action = ('Run targeted Inspect linked source PDFs with this original URL; '
                      'confirm document title, version, publisher and authors manually. '
                      'Do not assume that a large collection is one journal article')
            priority = 'High'
        else:
            category = 'webpage_or_index_record'
            action = ('Review original source URL and provider metadata; '
                      'check whether it is an identifiable individual publication')
            priority = 'Review'
        result.append({
            'tool': tool, 'question': question,
            'source_identity': source_identity,
            'citation_occurrences': len(members),
            'citation_orders': _unique(item['order'] for item, _ in members),
            'original_urls': _unique(urls),
            'source_access_category': category,
            'source_domain': parsed.hostname or '',
            'research_status': reason or 'unresolved',
            'source_document_status': _unique(doc.get('status') for doc in doc_info),
            'source_document_title_hint': _unique(doc.get('title_hint') for doc in doc_info),
            'priority': priority,
            'review_action': action,
        })
    return sorted(result, key=lambda x: (
        x['priority'] != 'High', -x['citation_occurrences'], x['tool'], x['question']))
