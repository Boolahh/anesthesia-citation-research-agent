"""Strict original-citation-to-publication identity gate.

Never turn a search hit, similar title, general webpage, institutional
document, or author-country inference into a confirmed bibliographic record.
An authoritative identifier matched to its original PDF source is required
for unattended publication enrichment. These are still PROPOSALS until a
reviewer independently verifies the citation.
"""
from __future__ import annotations

from urllib.parse import unquote, urlparse
import re

from .pdf_extract import DOI_RE


MISSING = 'NOT FOUND'


def _doi(value):
    match = DOI_RE.search(unquote(str(value or '')))
    return match.group(0).rstrip('.,;)').casefold() if match else ''


def _article_pmid(url):
    parsed = urlparse(str(url or ''))
    host = (parsed.hostname or '').casefold()
    path = unquote(parsed.path).rstrip('/')
    if host == 'pubmed.ncbi.nlm.nih.gov':
        match = re.fullmatch(r'/(\d{6,9})', path)
        return match.group(1) if match else ''
    if host == 'www.ncbi.nlm.nih.gov':
        match = re.fullmatch(r'/pubmed/(\d{6,9})', path)
        return match.group(1) if match else ''
    if host in ('europepmc.org', 'www.europepmc.org'):
        match = re.fullmatch(r'/article/MED/(\d{6,9})', path, re.I)
        return match.group(1) if match else ''
    if host == 'pesquisa.bvsalud.org':
        match = re.fullmatch(r'/(?:portal/)?resource/[^/]+/mdl-(\d{6,9})',
                             path, re.I)
        return match.group(1) if match else ''
    return ''


def _pmcid(url):
    parsed = urlparse(str(url or ''))
    if (parsed.hostname or '').casefold() not in (
            'pmc.ncbi.nlm.nih.gov', 'www.ncbi.nlm.nih.gov'):
        return ''
    match = re.search(r'/articles/(PMC\d{5,10})(?:/|$)', unquote(parsed.path), re.I)
    return match.group(1).upper() if match else ''


def reliable_original_identity(original, evidence):
    """Return (eligible, reason) for source-derived workbook proposals.

    No automatically verified citation-verdict is produced. DOI/title search
    results are not enough: the original source link, displayed identifier, or
    investigator's verified X link must identify the SAME actual record.
    """
    match = evidence.get('match') or {}
    status = str(match.get('status') or '')
    method = str(match.get('method') or '')
    warnings = ' '.join(str(x).casefold() for x in match.get('warnings') or [])
    if status in ('identifier_conflict', 'non_source_search_results'):
        return False, 'Original source is conflicting or is a search-results page'
    if ('conflict' in warnings or 'differs materially' in warnings or
            'mismatch' in warnings):
        return False, 'Original identifiers or citation title conflict with retrieved record'
    if method in ('high_similarity_title_candidate', 'exact_title_pubmed_candidate'):
        return False, 'Similar publication title from a search is not verified source identity'

    url = str(original.get('url') or '')
    doi = _doi(evidence.get('doi'))
    pmid = str(evidence.get('pmid') or '')
    pubmed = evidence.get('pubmed') or {}
    crossref = evidence.get('crossref') or {}
    europe = evidence.get('europepmc') or {}
    openalex = evidence.get('openalex') or {}
    official_pmid = str(pubmed.get('pmid') or '')
    official_doi = _doi(crossref.get('DOI')) or _doi(pubmed.get('doi'))
    title = (pubmed.get('title') or
             (crossref.get('title') or [''])[0] or
             europe.get('title') or openalex.get('display_name') or '')
    if not title:
        return False, 'No authoritative bibliographic publication record and title retrieved'

    url_pmid = _article_pmid(url)
    if url_pmid and pubmed and official_pmid == url_pmid == pmid:
        return True, 'Original direct PubMed/Europe PMC identifier matches an authoritative record'

    url_host = (urlparse(url).hostname or '').casefold()
    url_doi = _doi(url)
    if (url_doi and doi == url_doi and official_doi == doi
            and (url_host in ('doi.org', 'dx.doi.org') or
                 '/doi/' in urlparse(url).path.casefold())):
        return True, 'Original DOI-bearing article link matches authoritative publication DOI'

    # A printed DOI in a specific cited reference is usable without a PDF URI.
    # If a different, unrelated URL is present, a DOI written in the surrounding
    # prose is not independent proof that the hyperlink points to that work.
    cited_doi = _doi(original.get('doi'))
    if (not url or url == 'NR') and cited_doi and cited_doi == doi == official_doi:
        return True, 'Original explicit citation DOI matches authoritative publication DOI'
    cited_pmid = str(original.get('pmid') or '')
    if ((not url or url == 'NR') and cited_pmid.isdigit() and
            cited_pmid == pmid == official_pmid and pubmed):
        return True, 'Original explicit citation PMID matches authoritative PubMed record'

    pmc = _pmcid(url)
    if (pmc and (europe or pubmed) and
            (pmid == official_pmid or
             str(europe.get('pmcid') or europe.get('pmcId') or '').upper() == pmc) and
            (official_pmid or europe.get('title'))):
        return True, 'Original PMC full-article identifier resolved through authoritative database'

    # Original linked article metadata can be corroborated independently by
    # a DOI registry and the same full publication title (not a plain webpage
    # <title>, an organization label, or a general reference to the topic).
    page = evidence.get('public_page') or {}
    page_meta = page.get('meta') or {}
    citation_doi = _doi((page_meta.get('citation_doi') or [''])[0])
    citation_title = str((page_meta.get('citation_title') or [''])[0]).strip()
    if (url.startswith(('http://', 'https://')) and
            citation_doi and citation_doi == doi == official_doi and
            citation_title and title and
            re.sub(r'[^a-z0-9]', '', citation_title.casefold()) ==
            re.sub(r'[^a-z0-9]', '', title.casefold())):
        return True, 'Linked article metadata and independent DOI registry agree exactly'

    # A human-verified URL in column X is still not a license to invent an
    # author, year, or country. Only an authenticated authoritative source
    # record can supply publication facts.
    return False, 'Source identity not independently confirmed: preserve original citation and URL'


def strict_green_values(fields, provenance, eligible):
    """Use the template-supported NOT FOUND; never invent missing metadata.

    Even for an identified article, inferred OpenAlex countries, webpage
    title guesses, PDF document-label guesses and source-domain types are
    review clues, not automatic study outcome fields.
    """
    from .workbook import GREEN_COLS

    values = {}
    for col in GREEN_COLS:
        value = fields.get(col, MISSING)
        source = str((provenance.get(col) or {}).get('source') or '')
        if col == 'BE':
            # Only an actual investigator-provided licensed JCR record may
            # populate this restricted measure; never estimate it.
            values[col] = (
                value if eligible and
                source == 'Investigator-supplied licensed 2026 Journal Citation Reports'
                and value not in ('', 'NR', 'NOT FOUND', None) else ''
            )
            continue
        if not eligible:
            values[col] = MISSING
        elif value in ('', None, 'NR', 'NOT FOUND'):
            values[col] = MISSING
        elif (source == 'OpenAlex matched author-country' or
              'inferred' in source.casefold() or
              source.startswith(('Original linked webpage title', 'Original linked PDF title')) or
              source in ('source domain', 'recognized clinical education / society domain',
                         'linked resource provider', 'official public-agency domain',
                         'source category', 'type-based coding',
                         'independently retrieved publication title',
                         'official regional clinical protocol PDF (unverified)',
                         'publisher-hosted edited collection (unverified)',
                         'ANZCA source PDF frontmatter (unverified)',
                         'AI proposal from retrieved evidence')):
            values[col] = MISSING
        else:
            values[col] = value
    return values
