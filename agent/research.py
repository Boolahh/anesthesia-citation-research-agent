"""Cautious, evidence-linked bibliographic research.

Never equate an API match with a human citation-verification decision. Preserve
original as-cited data in blue cells; all corrected fields are provisional and
accompanied by field-level provenance and unresolved ambiguity flags.
"""
from __future__ import annotations

from collections import OrderedDict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote, quote
from xml.etree import ElementTree as ET
import hashlib
from html import unescape
import os
import ipaddress
import json
import re
import socket
import time

import requests
from bs4 import BeautifulSoup

from .pdf_extract import DOI_RE, PMID_RE
from .workbook import GREEN_COLS

USER_AGENT = 'AnesthesiaCitationBiasResearchAgent/2.0 (evidence-traceable, human-verified)'
MAX_RESPONSE = 2_000_000
TRUSTED_BIBLIO_HOSTS = {'api.crossref.org', 'api.openalex.org', 'www.ebi.ac.uk',
                        'eutils.ncbi.nlm.nih.gov', 'pmc.ncbi.nlm.nih.gov'}


def public_dns_destination(url):
    """Refuse known private DNS answers for untrusted original model URLs.

    This is a defense in depth, not a full guarantee against DNS rebinding.
    Bibliographic API endpoints have fixed, recognized hostnames.
    """
    if not safe_url(url):
        return False
    host = urlparse(url).hostname
    if host in TRUSTED_BIBLIO_HOSTS:
        return True
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return bool(answers) and all(ipaddress.ip_address(item[4][0]).is_global for item in answers)
    except (OSError, ValueError, TypeError):
        return False


def safe_url(url):
    """Basic SSRF defense, including encoded/IPv4/IPv6/local host literals."""
    try:
        u = urlparse(str(url or ''))
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
            return False
        h = u.hostname.lower().rstrip('.')
        if h in ('localhost', 'localhost.localdomain') or h.endswith(('.localhost', '.local', '.internal', '.onion', '.test')):
            return False
        if any(ch.isspace() for ch in h):
            return False
        try:
            if not ipaddress.ip_address(h).is_global:
                return False
        except ValueError:
            # Invalid digit-only addresses and unqualified intranet hostnames are unsafe.
            if '.' not in h or re.fullmatch(r'[0-9.]+', h):
                return False
        return True
    except (TypeError, ValueError):
        return False


def norm_title(s):
    return re.sub(r'[^a-z0-9]', '', str(s or '').lower())


def quality(a, b):
    x, y = norm_title(a), norm_title(b)
    if not x or not y:
        return 0.0
    return SequenceMatcher(None, x, y).ratio()


def citation_title_similarity(as_cited_title, original_reference, retrieved_title):
    """Compare the true title, not page numbers, author initials or journal data.

    A complete displayed reference may include the exact publication title
    followed by its journal, issue and a generic 'Full article' label. Its
    full-string similarity is misleadingly low. Exact, substantial title
    containment in the *original* source text is strong evidence of a title
    match, but is NOT a verified DOI/source-identity verdict.
    """
    published = norm_title(retrieved_title)
    reference = norm_title(original_reference)
    title = str(retrieved_title or '')
    if (len(published) >= 28
            and len(re.findall(r'[A-Za-z]{3,}', title)) >= 4
            and published in reference):
        return 1.0, 'retrieved title appears verbatim in original reference'
    score = quality(as_cited_title, retrieved_title)
    # Some clinical checklist labels abbreviate *both* the issuing society
    # and the medical syndrome. A direct string comparison can produce a
    # false conflict even when the official published title is unambiguous.
    # This is a provisional title-alias check, not a source-authenticity verdict.
    expansions = {
        'ASRA': 'American Society of Regional Anesthesia and Pain Medicine',
        'LAST': 'Local Anesthetic Systemic Toxicity',
    }
    expanded = re.sub(
        r'\b(?:ASRA|LAST)\b',
        lambda m: expansions[m.group().upper()],
        str(as_cited_title or ''), flags=re.I)
    if expanded != str(as_cited_title or ''):
        expanded_score = quality(expanded, retrieved_title)
        if expanded_score >= .90:
            return expanded_score, 'abbreviated label with matching clinical acronym expansion; verify source identity'
    search_hint = title_search_hint(as_cited_title)
    if search_hint:
        score = max(score, quality(search_hint, retrieved_title))
    phrase_words, phrase_chars = _best_shared_title_phrase(original_reference, retrieved_title)
    if phrase_words >= 4 and phrase_chars >= 30 and score < .85:
        # An abbreviated citation can share a meaningful sequence without
        # matching the publication's full title. Retain human review.
        return .85, 'substantial shared title phrase; abbreviated label requires review'
    return score, 'as-cited title similarity'


def _best_shared_title_phrase(cited, retrieved):
    """Length of the longest contiguous word phrase shared by source labels.

    A long shared phrase indicates the as-cited title may be abbreviated.
    This is not independent proof of bibliographic source identity.
    """
    left = re.findall(r'[a-z0-9]+', str(cited or '').casefold())[:120]
    right = re.findall(r'[a-z0-9]+', str(retrieved or '').casefold())[:120]
    best = []
    for i in range(len(left)):
        for j in range(len(right)):
            k = 0
            while i+k < len(left) and j+k < len(right) and left[i+k] == right[j+k]:
                k += 1
            if k > len(best):
                best = left[i:i+k]
    return len(best), len(' '.join(best))


def descriptive_source_label(label):
    """A short descriptive summary is not the full bibliographic title."""
    plain = re.sub(r'^\s*(?:\[\d+\]|\d+[).])\s*', '', str(label or '')).strip()
    return (len(re.findall(r'[A-Za-z]{3,}', plain)) <= 9 and bool(re.match(
        r'^(?:a\s+)?(?:meta[- ]analysis|systematic review|randomized trial|'
        r'randomised trial|clinical overview|overview)\b', plain, re.I)))


def _safe_pubmed_xml(body):
    """Remove PubMed's standard external DTD without enabling entity expansion.

    Accept only NLM PubmedArticleSet publication DTD declarations; reject
    arbitrary/custom entities and other DOCTYPEs. PubMed XML parsing never
    needs an external DTD fetch.
    """
    if re.search(r'<!ENTITY\b', body, re.I):
        raise ValueError('PubMed XML included an entity declaration')
    body = re.sub(
        r'<!DOCTYPE\s+PubmedArticleSet\s+PUBLIC\s+["\x27][^"\x27]+["\x27]\s+'
        r'["\x27]https://dtd\.nlm\.nih\.gov/ncbi/pubmed/out/[^"\x27]+\.dtd["\x27]\s*>',
        '', body, count=1, flags=re.I)
    if re.search(r'<!DOCTYPE\b', body, re.I):
        raise ValueError('Unexpected PubMed XML document type')
    return body


def explicit_source_type_from_published_title(title):
    """Classify only overt publication self-descriptions, not papers ABOUT guidelines.

    PubMed may label an authored practice guideline as "Review". A retrieved
    bibliographic title is permissible provisional evidence for that source
    type; a human reviewer still owns final study coding.
    """
    value = ' '.join(str(title or '').split()).strip().lower()
    if re.match(r'^(?:a |an |the )?(?:systematic |narrative |scoping |critical )?'
                r'(?:review|overview|assessment|comparison|evaluation|analysis) of\b', value):
        return ''
    if re.search(r'\b(?:practice|clinical practice|evidence[- ]based|consensus[- ]based)\s+guidelines?\b'
                 r'|\bguidelines?\s*(?::|(?:for|on|of)\b)', value):
        return 'Guideline'
    if re.search(r'\b(?:joint )?consensus (?:statement|report|recommendations)\b', value):
        return 'Consensus statement'
    # The workbook has no separate Practice Advisory category. Official
    # clinical practice advisories are systematic recommendations, not
    # primary clinical studies. Map to Guideline as a *provisional* study
    # category and require reviewer confirmation of the classification.
    if re.search(r'\bpractice advisory for (?:perioperative|anesthesia|anaesthesia|'
                 r'management|clinical|preoperative|postoperative)\b', value):
        return 'Guideline'
    return ''


def normalize_doi(s):
    m = DOI_RE.search(unquote(str(s or '')))
    return m.group().rstrip('.,;)').lower() if m else ''


def title_search_hint(as_cited):
    """Extract a *query hint*, never alter the original blue citation text.

    Model answers sometimes append a bibliographic note after the real title,
    e.g. `Fourth Consensus Guidelines ... (Gan et al., A&A, 2020)`.
    Searching the entire text can miss the true DOI or match an unrelated work.
    A title search remains a review-required candidate, not an identity verdict.
    """
    value = ' '.join(str(as_cited or '').split())
    value = re.sub(r'^\s*(?:\[\d+\]|\d+[).])\s*', '', value)
    value = re.sub(r'^\s*(?:key|selected|main|primary)\s+references\s*:\s*', '', value, flags=re.I)
    # Only remove a trailing parenthesis that clearly looks bibliographic, not
    # legitimate title parentheses such as (PONV) or (LAST).
    value = re.sub(r'\s*\([^()]{4,160}\b(?:19|20)\d{2}\)\s*$', '', value)
    value = re.sub(r'\s*(?:doi|pmid)\s*:\s*\S+\s*$', '', value, flags=re.I)
    value = value.strip(' .:;\"\u201c\u201d')
    return value if 25 <= len(value) <= 240 and len(re.findall(r'[A-Za-z]{3,}', value)) >= 7 else ''


def iso2_country(code, countries):
    if not code:
        return 'NR', 'NR', 'NR'
    iso3 = ''
    try:
        import pycountry
        c = pycountry.countries.get(alpha_2=str(code).upper())
        iso3 = c.alpha_3 if c else ''
    except (ImportError, LookupError):
        pass
    if str(code).upper() == 'XK':
        iso3 = 'XKX'
    d = countries.get(iso3) or {}
    return d.get('name') or 'NR', d.get('region') or 'NR', d.get('income') or 'NR'


def _author_name_key(name):
    """Strict name normalization for matching authors *within one publication*."""
    return re.sub(r'[^a-z0-9]', '', str(name or '').casefold())


def _openalex_author_country(author, countries):
    """Return a country only when this one authorship has exactly one country.

    OpenAlex may list several institutions and nations without meaningful
    affiliation chronology. Neither their order nor an institution name is
    sufficient to select the newest institution. A unique country across
    that author's indexed work affiliation(s) is weaker, review-required
    evidence for geography alone.
    """
    codes = set()
    for code in author.get('countries') or []:
        if isinstance(code, str) and re.fullmatch(r'[A-Za-z]{2}', code):
            codes.add(code.upper())
    for ins in author.get('institutions') or []:
        if isinstance(ins, dict):
            code = ins.get('country_code')
            if isinstance(code, str) and re.fullmatch(r'[A-Za-z]{2}', code):
                codes.add(code.upper())
    if len(codes) != 1:
        return None
    result = iso2_country(next(iter(codes)), countries)
    return result if result[0] != 'NR' else None


def _node_text(node):
    return ' '.join(' '.join(node.itertext()).split()) if node is not None else ''


def _year(s):
    m = re.search(r'(?:19|20)\d{2}', str(s or ''))
    return m.group() if m else ''


def parse_pubmed_xml(xml_text):
    """Read each PubMed Author's own AffiliationInfo, never pooled affiliations."""
    root = ET.fromstring(xml_text)
    article = root.find('.//PubmedArticle')
    if article is None:
        return None
    med = article.find('MedlineCitation')
    paper = med.find('Article') if med is not None else None
    if paper is None:
        return None
    journal = paper.find('Journal')
    pubdate = journal.find('JournalIssue/PubDate') if journal is not None else None
    issue_year = _year(_node_text(pubdate.find('Year'))) if pubdate is not None else ''
    if not issue_year and pubdate is not None:
        issue_year = _year(_node_text(pubdate.find('MedlineDate')))
    online_year = _year(_node_text(paper.find('ArticleDate/Year')))
    if not online_year:
        online_year = _year(_node_text(article.find('.//PubMedPubDate[@PubStatus="epublish"]/Year')))
    people = []
    for person in paper.findall('AuthorList/Author'):
        collective = _node_text(person.find('CollectiveName'))
        name = collective or ' '.join(filter(None, [
            _node_text(person.find('ForeName')), _node_text(person.find('LastName'))]))
        if not name:
            continue
        affiliations = []
        for aff in person.findall('AffiliationInfo/Affiliation'):
            value = _node_text(aff)
            if value and value not in affiliations:
                affiliations.append(value)
        people.append({'name': name, 'group': bool(collective), 'affiliations': affiliations})
    # PubMed sometimes repeats one composite paragraph containing *all*
    # authors' labelled institutions inside every Author/AffiliationInfo.
    # Such a paragraph is NOT evidence that each person belongs to all of
    # those universities (e.g. Callum/Barkun/Karkouti affiliations in CMAJ).
    # Preserve a diagnostic; suppress institution assignment until a person
    # has a genuinely individual address or an investigator reviews the text.
    affiliation_diagnostics = []
    reuse = {}
    for author in people:
        for affiliation in author['affiliations']:
            reuse[affiliation] = reuse.get(affiliation, 0) + 1
    for author in people:
        remaining = []
        for affiliation in author['affiliations']:
            segments = [x.strip() for x in affiliation.split(';') if x.strip()]
            group_labels = re.findall(r'\([A-Za-z][A-Za-z -]{1,35}\)', affiliation)
            is_composite = (reuse.get(affiliation, 0) >= 2 and len(segments) > 1 and
                            (len(group_labels) >= 2 or
                             sum(bool(re.search(r'\b(?:department|division|university|hospital|centre|center)\b', x, re.I))
                                 for x in segments) >= 2))
            if is_composite:
                if affiliation not in affiliation_diagnostics:
                    affiliation_diagnostics.append(affiliation)
            else:
                remaining.append(affiliation)
        author['affiliations'] = remaining
    identifiers = {}
    for idnode in article.findall('PubmedData/ArticleIdList/ArticleId'):
        key, value = idnode.get('IdType'), _node_text(idnode)
        if key and value:
            identifiers[key] = value
    return {
        'pmid': _node_text(med.find('PMID')) if med is not None else '',
        'doi': normalize_doi(identifiers.get('doi', '')),
        'title': _node_text(paper.find('ArticleTitle')),
        'year': issue_year or online_year,
        'issue_year': issue_year,
        'online_year': online_year,
        'year_basis': 'PubMed journal issue date' if issue_year else 'PubMed electronic publication date' if online_year else 'not reported',
        'journal': _node_text(journal.find('Title')) if journal is not None else '',
        'authors': people,
        'shared_affiliation_blocks': affiliation_diagnostics,
        'publication_types': [_node_text(x) for x in paper.findall('PublicationTypeList/PublicationType')],
    }


class Bibliography:
    def __init__(self, countries, cache_dir, email='', timeout=18, offline=False):
        self.countries = countries
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.offline = offline
        self.email = email
        self.s = requests.Session()
        self.s.headers.update({'User-Agent': USER_AGENT + (f' mailto:{email}' if email else '')})
        self.events = []

    def _get(self, url, params=None, accept='application/json'):
        """Public GET with capped downloads, safe redirects, timeouts, retries, caching."""
        if not safe_url(url):
            self.events.append({'url': url, 'status': 'blocked_url'})
            return None
        key = hashlib.sha256(json.dumps([url, params, accept], sort_keys=True).encode()).hexdigest()
        ext = '.json' if accept == 'application/json' else '.txt'
        path = self.cache_dir / (key[:32] + ext)
        if path.exists():
            try:
                result = path.read_text(encoding='utf-8')
                data = json.loads(result) if accept == 'application/json' else result
                # The previous report showed '0 external lookup successes' even
                # when many sources were resolved successfully from local cache.
                # Audit cache reuse separately from a fresh network response.
                self.events.append({'url': url, 'status': 'cache_hit'})
                return data
            except (ValueError, OSError):
                pass
        if self.offline:
            return None
        for attempt in range(3):
            address = url
            try:
                for hop in range(6):
                    if not public_dns_destination(address):
                        raise ValueError('Unsafe / privately resolving URL or DNS failure')
                    with self.s.get(address, params=params if hop == 0 else None,
                                    timeout=self.timeout, allow_redirects=False,
                                    stream=True, headers={'Accept': accept}) as resp:
                        if resp.is_redirect:
                            address = urljoin(address, resp.headers.get('Location', ''))
                            continue
                        if resp.status_code in (429, 500, 502, 503, 504):
                            raise requests.HTTPError('Transient HTTP '+str(resp.status_code))
                        if resp.status_code != 200:
                            self.events.append({'url': address, 'status': 'http_'+str(resp.status_code)})
                            return None
                        if 'text/html' in resp.headers.get('Content-Type', '') and accept == 'application/json':
                            return None
                        data = bytearray()
                        for piece in resp.iter_content(65536):
                            data.extend(piece)
                            if len(data) > MAX_RESPONSE:
                                self.events.append({'url': address, 'status': 'too_large'})
                                return None
                        body = data.decode('utf-8-sig', errors='replace')
                        result = json.loads(body) if accept == 'application/json' else body
                        path.write_text(body, encoding='utf-8')
                        self.events.append({'url': address, 'status': 'ok'})
                        return result
                self.events.append({'url': url, 'status': 'too_many_redirects'})
                return None
            except (requests.RequestException, ValueError) as exc:
                if attempt == 2:
                    self.events.append({'url': url, 'status': 'error', 'detail': str(exc)[:130]})
                    return None
                time.sleep(1.5 * (attempt+1))
        return None

    def fetch_json(self, url, params=None):
        # OpenAlex offers a free API tier and optional API key. Never embed the
        # key in a stored response, console message or research provenance.
        if urlparse(url).hostname == 'api.openalex.org':
            key = os.getenv('OPENALEX_API_KEY', '')
            if key:
                params = {**(params or {}), 'api_key': key}
        return self._get(url, params, 'application/json')

    def public_page(self, url):
        body = self._get(url, accept='text/html,application/xhtml+xml')
        if not body or not body.lstrip().startswith(('<', '\ufeff<')):
            return None
        soup = BeautifulSoup(body, 'html.parser')
        meta = {}
        for tag in soup.find_all('meta'):
            key = (tag.get('name') or tag.get('property') or '').lower()
            value = tag.get('content', '')
            if key in ('citation_title', 'citation_doi', 'citation_author', 'citation_date',
                       'citation_publication_date', 'citation_journal_title', 'citation_pmid',
                       'og:title', 'dc.title', 'dc.date') and value:
                meta.setdefault(key, []).append(value)
        page_title = soup.title.get_text(' ', strip=True) if soup.title else ''
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'noscript']):
            tag.decompose()
        return {'url': url, 'title': page_title, 'meta': meta,
                'excerpt': ' '.join(soup.stripped_strings)[:4000]}

    def _europe(self, pmid='', pmcid=''):
        query = f'EXT_ID:{pmcid}' if pmcid else f'EXT_ID:{pmid} AND SRC:MED'
        data = self.fetch_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',
                               {'query': query, 'format': 'json', 'pageSize': 1})
        results = ((data or {}).get('resultList') or {}).get('result') or []
        return results[0] if results else None

    def _convert_pmc(self, pmcid):
        """Use the official PMC ID converter if Europe PMC cannot link a PMCID.

        This endpoint yields *identifiers only*; it does not prove that the AI
        title or the human source-verification verdict is correct.
        https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api/
        """
        if not re.fullmatch(r'PMC\d{5,10}', str(pmcid or ''), re.I):
            return None
        params = {'ids': pmcid.upper(), 'format': 'json', 'tool': 'anesthesia-citation-agent'}
        if self.email:
            params['email'] = self.email
        data = self.fetch_json('https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/', params)
        records = (data or {}).get('records') or []
        for record in records:
            if str(record.get('pmcid', '')).upper() == pmcid.upper() and 'errmsg' not in record:
                value = str(record.get('pmid') or '')
                return {'pmcid': pmcid.upper(), 'pmid': value if value.isdigit() else '',
                        'doi': normalize_doi(record.get('doi'))}
        return None

    def _pubmed(self, pmid):
        if not pmid:
            return None
        # NCBI's EFetch XML exposes author-specific affiliations and issue dates.
        body = self._get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',
                         {'db': 'pubmed', 'id': pmid, 'retmode': 'xml', 'tool': 'anesthesia-citation-agent',
                          **({'email': self.email} if self.email else {})}, 'application/xml')
        if body:
            try:
                parsed = parse_pubmed_xml(_safe_pubmed_xml(body))
                if parsed:
                    return parsed
            except (ET.ParseError, ValueError):
                pass
            self.events.append({'url': 'NCBI PubMed EFetch', 'status': 'invalid_xml'})
        return None

    def metadata(self, citation):
        """Independent lookup pipeline: explicit IDs > PubMed > publisher > constrained title."""
        self.events = []
        url = citation.get('url') or ''
        if url == 'NR':
            url = ''
        raw = citation.get('citation') or ''
        # A human-supplied, independently verified X URL overrides original
        # as-cited DOI/PMID text, which can itself contain the study's errors.
        verified_url = bool(citation.get('source_url_verified'))
        issue_flags = []
        original_doi = normalize_doi(citation.get('doi')) or normalize_doi(raw)
        url_doi = normalize_doi(url)
        url_pmid_match = re.search(
            r'(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d{6,9})(?:[/#?]|$)', url, re.I)
        url_pmid = url_pmid_match.group(1) if url_pmid_match else ''
        original_pmid = str(citation.get('pmid') or '')
        original_pmid = original_pmid if original_pmid.isdigit() else ''
        if url_doi and original_doi and url_doi != original_doi:
            issue_flags.append('Original cited DOI conflicts with hyperlink DOI')
        if url_pmid and original_pmid and url_pmid != original_pmid:
            issue_flags.append('Original cited PMID conflicts with hyperlink PMID')
        # The actual link's identifier takes priority for retrieval, but neither
        # conflicting blue field is altered in the original study workbook.
        doi = url_doi or ('' if verified_url else original_doi)
        pmid = url_pmid or ('' if verified_url else original_pmid)
        pmc_match = re.search(r'\bPMC\d{5,10}\b', url, re.I)
        pmc = pmc_match.group().upper() if pmc_match else ''
        europe = self._europe(pmid, pmc) if pmid or pmc else None
        converted = self._convert_pmc(pmc) if pmc else None
        if converted:
            converted_doi, converted_pmid = converted['doi'], converted['pmid']
            if doi and converted_doi and doi != converted_doi:
                issue_flags.append('Original cited DOI conflicts with PMC identifier conversion')
            if pmid and converted_pmid and pmid != converted_pmid:
                issue_flags.append('Original cited PMID conflicts with PMC identifier conversion')
            doi = converted_doi or doi
            pmid = converted_pmid or pmid
        if europe:
            europe_doi = normalize_doi(europe.get('doi'))
            if doi and europe_doi and doi != europe_doi:
                issue_flags.append('Original cited DOI conflicts with Europe PMC record')
            doi = (converted or {}).get('doi') or europe_doi or doi
            if not pmid and europe.get('source') == 'MED':
                pmid = str(europe.get('id') or '')
        pubmed = self._pubmed(pmid) if pmid else None
        if pubmed:
            pubmed_doi = pubmed.get('doi') or ''
            if doi and pubmed_doi and doi != pubmed_doi:
                issue_flags.append('Original cited DOI conflicts with PubMed record')
            doi = pubmed_doi or doi
        cross = None
        oa = None
        if doi and not pmid:
            # DOI-only citations may still have author-specific PubMed evidence.
            europe_doi = self.fetch_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',
                                         {'query': 'DOI:'+doi, 'format': 'json', 'pageSize': 2})
            for article in ((europe_doi or {}).get('resultList') or {}).get('result') or []:
                if normalize_doi(article.get('doi')) == doi and article.get('source') == 'MED':
                    pmid = str(article.get('id') or '')
                    europe = article
                    pubmed = self._pubmed(pmid)
                    break
        if doi:
            cross = (self.fetch_json('https://api.crossref.org/works/'+quote(doi, safe='/')) or {}).get('message')
            oa_candidate = self.fetch_json('https://api.openalex.org/works/'+quote('https://doi.org/'+doi, safe=':/'))
            if oa_candidate and oa_candidate.get('id'):
                oa = oa_candidate
        if not oa and pmid:
            result = self.fetch_json('https://api.openalex.org/works',
                {'filter': 'pmid:https://pubmed.ncbi.nlm.nih.gov/'+pmid, 'per-page': 1})
            oa = next(iter((result or {}).get('results') or []), None)
        page = self.public_page(url) if url else None
        if page:
            meta = page['meta']
            doi = doi or normalize_doi((meta.get('citation_doi') or [''])[0])
            if not pmid:
                value = (meta.get('citation_pmid') or [''])[0]
                pmid = value if value.isdigit() else ''
            if pmid and not pubmed:
                pubmed = self._pubmed(pmid)
            if doi and not cross:
                cross = (self.fetch_json('https://api.crossref.org/works/'+quote(doi, safe='/')) or {}).get('message')
            if doi and not oa:
                oa_candidate = self.fetch_json('https://api.openalex.org/works/'+quote('https://doi.org/'+doi, safe=':/'))
                oa = oa_candidate if oa_candidate and oa_candidate.get('id') else None
        match = {'method': 'reviewer_verified_URL' if verified_url else 'identifier' if doi or pmid else 'none',
                 'status': 'review_required', 'title_similarity': None, 'warnings': list(issue_flags)}
        if verified_url and citation.get('doi') not in ('', 'NR', None) and doi and normalize_doi(citation.get('doi')) != doi:
            match['warnings'].append('Original cited DOI differs from reviewer verified URL; preserve citation error for protocol')
        # Do not turn free-form names such as "NEJM, 2019" into title searches.
        title = citation.get('title') or ''
        title_words = re.findall(r'[A-Za-z]{3,}', title)
        search_hint = title_search_hint(title)
        if not cross and not oa and not pubmed and not doi and search_hint:
            result = self.fetch_json('https://api.crossref.org/works',
                                     {'query.title': search_hint, 'rows': 3})
            items = ((result or {}).get('message') or {}).get('items') or []
            scored = sorted(((quality(search_hint, (it.get('title') or [''])[0]), it)
                             for it in items), key=lambda x: x[0], reverse=True)
            # Multiple near-identical editions or a preprint plus journal
            # article must never silently resolve to the first search hit.
            if scored and scored[0][0] >= .94 and (len(scored) == 1 or
                                                   scored[0][0] - scored[1][0] >= .035):
                candidate = scored[0][1]
                cross = candidate
                doi = normalize_doi(candidate.get('DOI'))
                if doi:
                    oa_candidate = self.fetch_json('https://api.openalex.org/works/'+quote('https://doi.org/'+doi, safe=':/'))
                    oa = oa_candidate if oa_candidate and oa_candidate.get('id') else None
                match['method'] = 'high_similarity_title_candidate'
                match['warnings'].append('Title-only Crossref result is provisional; verify source identity')
            elif scored:
                match['warnings'].append('Crossref title search returned ambiguous or weak matches')
        # For clinical articles, PubMed's exact-title search can recover a
        # missing PMID/DOI when Crossref has no unambiguous candidate.
        if not cross and not oa and not pubmed and not doi and search_hint:
            query = self.fetch_json('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',
                                    {'db':'pubmed', 'term':f'"{search_hint}"[Title]',
                                     'retmode':'json', 'retmax':3,
                                     **({'email':self.email} if self.email else {})})
            ids = ((query or {}).get('esearchresult') or {}).get('idlist') or []
            matches = []
            for possible_id in ids[:3]:
                if not str(possible_id).isdigit():
                    continue
                candidate = self._pubmed(str(possible_id))
                if candidate and candidate.get('title'):
                    matches.append((quality(search_hint, candidate['title']), candidate))
            matches.sort(key=lambda x:x[0], reverse=True)
            if matches and matches[0][0] >= .96 and (len(matches) == 1 or
                                                     matches[0][0] - matches[1][0] >= .035):
                pubmed = matches[0][1]
                pmid = str(pubmed.get('pmid') or '')
                doi = pubmed.get('doi') or ''
                if doi:
                    cross = (self.fetch_json('https://api.crossref.org/works/'+quote(doi, safe='/')) or {}).get('message')
                    a = self.fetch_json('https://api.openalex.org/works/'+quote('https://doi.org/'+doi, safe=':/'))
                    oa = a if a and a.get('id') else None
                match['method'] = 'exact_title_pubmed_candidate'
                match['warnings'].append('Title-only PubMed match requires human verification')
            elif matches:
                match['warnings'].append('PubMed title search ambiguous; no record accepted')
        # Title-only Crossref matches can produce a DOI after the initial
        # DOI-to-PubMed lookup. Recover PubMed issue date, source type and
        # author-specific affiliations using that newly discovered DOI.
        if doi and not pmid and not pubmed and match['method'] == 'high_similarity_title_candidate':
            found = self.fetch_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',
                                    {'query': 'DOI:'+doi, 'format': 'json', 'pageSize': 2})
            for candidate in ((found or {}).get('resultList') or {}).get('result') or []:
                if (normalize_doi(candidate.get('doi')) == doi
                        and candidate.get('source') == 'MED'
                        and str(candidate.get('id') or '').isdigit()):
                    pmid = str(candidate['id'])
                    europe = candidate
                    pubmed = self._pubmed(pmid)
                    break
        if cross and doi:
            cross_doi = normalize_doi(cross.get('DOI'))
            if cross_doi and cross_doi != doi:
                match['warnings'].append('Crossref DOI conflicts with citation identifier')
                cross = None
        if pubmed and doi and pubmed.get('doi') and doi != pubmed['doi']:
            match['warnings'].append('PubMed DOI conflicts with cited DOI; possible mis-citation')
        if oa and doi and normalize_doi((oa.get('ids') or {}).get('doi')) not in (doi, ''):
            match['warnings'].append('OpenAlex record identifier conflicts with cited DOI')
            oa = None
        actual_title = (pubmed or {}).get('title') or (oa or {}).get('display_name') or \
                       ((cross or {}).get('title') or [''])[0] or (europe or {}).get('title') or ''
        if (oa or {}).get('is_retracted') or any('retract' in x.lower() for x in ((pubmed or {}).get('publication_types') or [])):
            match['warnings'].append('Publication flagged retracted; independent verification required')
        if actual_title and title and len(title_words) >= 5:
            similarity, basis = citation_title_similarity(title, raw, actual_title)
            match['title_similarity'] = round(similarity, 3)
            match['title_match_basis'] = basis
            if 'abbreviated label' in basis:
                match['warnings'].append('Abbreviated citation title shares a substantial phrase; independently verify full title')
            elif match['title_similarity'] < .65 and descriptive_source_label(raw):
                match['title_match_basis'] = 'descriptive label, not a complete publication title'
                match['warnings'].append('Descriptive citation label; title cannot be independently confirmed from original wording')
            elif match['title_similarity'] < .65:
                match['warnings'].append('Original cited title differs materially from retrieved publication; manually compare')
        elif actual_title:
            match['warnings'].append('Original title insufficient to confirm publication match')
        if issue_flags:
            match['status'] = 'identifier_conflict'
        elif match['method'] in ('high_similarity_title_candidate','exact_title_pubmed_candidate'):
            match['status'] = 'title_candidate_unverified'
        return {'doi': doi, 'pmid': pmid, 'crossref': cross, 'openalex': oa,
                'europepmc': europe, 'pubmed': pubmed, 'public_page': page,
                'source_url': url if safe_url(url) else '', 'match': match,
                'lookup_events': list(self.events), 'lookup_performed': not self.offline}

    def _affiliation_country(self, text):
        """Classify only a terminal, explicit country in one author's address.

        Do not assume that "University of Georgia" is in the country Georgia,
        nor that a publisher/city/institution establishes country. State,
        province and institution names are NOT reliable country evidence.
        """
        value = ' '.join(str(text or '').split()).strip(' .;')
        if not value:
            return 'NR', 'NR', 'NR'
        # Institutional addresses conventionally finish with a country. Use
        # the final comma/semicolon component; a trailing postal code can
        # follow the literal country and is removed only when unambiguous.
        suffix = re.split(r'[,;]', value)[-1].strip(' .')
        aliases = {
            'usa': 'United States', 'u.s.a.': 'United States',
            'united states of america': 'United States',
            'uk': 'United Kingdom', 'u.k.': 'United Kingdom',
            'great britain': 'United Kingdom',
        }
        lookup = {str(x['name']).lower(): x for x in self.countries.values() if x.get('name')}
        stripped = re.sub(r'\s+[0-9]{4,6}$', '', suffix).strip(' .').lower()
        target = aliases.get(stripped, stripped)
        entry = lookup.get(target)
        if entry and target not in ('georgia',):
            return entry['name'], entry.get('region') or 'NR', entry.get('income') or 'NR'
        # Accept a full country name at the end of an unpunctuated affiliation
        # if it is clearly a terminal geographic designation. Never treat a
        # country name within "University of ..." as location evidence.
        for country_name, candidate in sorted(lookup.items(), key=lambda p: -len(p[0])):
            if (country_name != 'georgia' and
                    re.search(r'(?<![a-z])'+re.escape(country_name)+r'\s*$', value, re.I) and
                    not re.search(r'\b(?:university|college|institute|school) of\s+'+
                                  re.escape(country_name)+r'\s*$', value, re.I)):
                return candidate['name'], candidate.get('region') or 'NR', candidate.get('income') or 'NR'
        # Alias at the final word of an unpunctuated address, e.g. "... UK".
        for token, name in aliases.items():
            if re.search(r'(?<![a-z])'+re.escape(token)+r'\s*$', value, re.I):
                item = lookup.get(name.lower())
                if item:
                    return item['name'], item.get('region') or 'NR', item.get('income') or 'NR'
        return 'NR', 'NR', 'NR'

    def baseline_green(self, evidence):
        """Return conservative 33-field proposals, never human-only verdicts."""
        oa = evidence.get('openalex') or {}
        cr = evidence.get('crossref') or {}
        pm = evidence.get('pubmed') or {}
        ep = evidence.get('europepmc') or {}
        page = evidence.get('public_page') or {}
        rows = {c: 'NR' for c in GREEN_COLS}
        provenance = {}
        review_flags = []
        if pm.get('shared_affiliation_blocks'):
            review_flags.append('PubMed has a multi-author composite affiliation; institutions withheld pending author-level review')

        def put(col, value, source, url='', reason=''):
            if value is None or value == '':
                return
            # Some bibliographic APIs return HTML-escaped journal names, e.g.
            # 'Anesthesia &amp; Analgesia'. Excel must contain human-readable text.
            if isinstance(value, str):
                value = unescape(value)
            rows[col] = value
            provenance[col] = {'source': source, 'url': url or '', 'reason': reason}

        pm_url = 'https://pubmed.ncbi.nlm.nih.gov/'+pm['pmid']+'/' if pm.get('pmid') else ''
        oa_url = oa.get('id') or ''
        cr_url = 'https://doi.org/'+evidence['doi'] if evidence.get('doi') else ''
        first = pm.get('title') or oa.get('display_name') or ((cr.get('title') or [''])[0]) or ep.get('title') or \
                ((page.get('meta') or {}).get('citation_title') or [''])[0]
        put('Z', first or 'NOT FOUND', 'PubMed' if pm.get('title') else 'OpenAlex' if oa.get('display_name') else 'Crossref' if cr else 'Europe PMC / publisher', pm_url or oa_url or cr_url)
        if pm.get('year'):
            put('AA', pm['year'], 'PubMed', pm_url, pm.get('year_basis', ''))
        elif oa.get('publication_year'):
            put('AA', oa['publication_year'], 'OpenAlex', oa_url, 'publication year')
        elif ep.get('pubYear'):
            put('AA', ep['pubYear'], 'Europe PMC', 'https://europepmc.org/article/MED/'+str(evidence.get('pmid') or ''))
        else:
            date = (cr.get('published-print') or cr.get('published') or cr.get('published-online') or {})
            y = ((date.get('date-parts') or [[]])[0] or [''])[0]
            put('AA', y or 'NOT FOUND', 'Crossref', cr_url, 'print or published issue date preferred')
        put('AB', evidence.get('doi') or 'NR', 'identifier lookup', cr_url)
        put('AC', evidence.get('pmid') or 'NR', 'PubMed identifier', pm_url)
        publication_types = [x.lower() for x in pm.get('publication_types') or []]
        ctype = (cr.get('type') or oa.get('type') or '').lower()
        title_type = explicit_source_type_from_published_title(first)
        if any('guideline' in x or 'practice guideline' in x for x in publication_types):
            put('AD', 'Guideline', 'PubMed publication type', pm_url)
        elif any('consensus' in x for x in publication_types):
            put('AD', 'Consensus statement', 'PubMed publication type', pm_url)
        elif title_type:
            put('AD', title_type, 'independently retrieved publication title', pm_url or cr_url or oa_url,
                'explicit guideline/consensus source title, not inferred from as-cited wording')
            review_flags.append('Guideline/consensus source type inferred from official title; verify classification'
                                + (' (practice advisory mapped to study Guideline category)'
                                   if 'practice advisory' in str(first).lower() else ''))
        elif ctype in ('journal-article', 'article', 'review', 'research-article', 'journal article') or pm:
            put('AD', 'Journal article', 'PubMed / Crossref / OpenAlex', pm_url or cr_url or oa_url)
        elif ctype in ('book', 'book-chapter', 'book-section'):
            put('AD', 'Textbook or book chapter', 'Crossref', cr_url)
        elif ctype in ('posted-content', 'preprint'):
            put('AD', 'Preprint', 'Crossref', cr_url)
        elif ctype in ('proceedings-article', 'proceedings'):
            put('AD', 'Conference abstract or proceedings', 'Crossref', cr_url)
        elif 'ncbi.nlm.nih.gov/books/' in evidence.get('source_url', ''):
            put('AD', 'Point-of-care resource topic (e.g. UpToDate, DynaMed, StatPearls)', 'source URL', evidence.get('source_url', ''))
        elif page and any(x in (urlparse(evidence.get('source_url', '')).hostname or '').lower() for x in ('asahq', 'apsf', 'ficm', 'openanesthesia', 'entnet')):
            put('AD', 'Professional society or organization webpage', 'source domain', evidence.get('source_url', ''))
        if rows['AD'] in ('Guideline', 'Consensus statement', 'Textbook or book chapter',
                          'Point-of-care resource topic (e.g. UpToDate, DynaMed, StatPearls)',
                          'Professional society or organization webpage'):
            put('AE', 'Not a research study (guideline, textbook, website...)', 'type-based coding', pm_url or cr_url)
        elif any('randomized controlled trial' in x or 'randomised controlled trial' in x for x in publication_types):
            put('AE', 'Randomized controlled trial', 'PubMed publication type', pm_url)
        elif any('meta-analysis' in x or 'meta analysis' in x for x in publication_types) and any('systematic review' in x or 'meta-analysis' in x or 'meta analysis' in x for x in publication_types):
            put('AE', 'Systematic review with meta-analysis', 'PubMed publication type', pm_url)
        elif any('systematic review' in x for x in publication_types):
            put('AE', 'Systematic review (no meta-analysis)', 'PubMed publication type', pm_url)
        elif any('case reports' in x or 'case report' in x for x in publication_types):
            put('AE', 'Case series or case report', 'PubMed publication type', pm_url)
        elif any(x in ('editorial', 'letter', 'comment') for x in publication_types):
            put('AE', 'Editorial, commentary or letter', 'PubMed publication type', pm_url)
        else:
            # Never automatically classify study designs from a title alone.
            rows['AE'] = 'NR'
        rows['AF'] = 'NR'  # Specialty requires reading source contents.
        rows['AG'] = 'NR'  # Funding requires explicit statement.
        if oa.get('id'):
            put('AH', oa.get('cited_by_count', 'NR'), 'OpenAlex', oa_url, 'count at lookup time; not fixed historically')
        authors = pm.get('authors') or []
        oa_auth = oa.get('authorships') or []
        cr_auth = cr.get('author') or []
        if authors:
            people = [a for a in authors if not a.get('group')]
            groups = [a for a in authors if a.get('group')]
            author_type = 'Individual and group authors' if people and groups else 'Organization / group author only' if groups else 'Individual author(s)'
            put('AI', author_type, 'PubMed author list', pm_url)
            put('AJ', len(people), 'PubMed author list', pm_url)
        elif oa_auth:
            put('AI', 'Individual author(s)', 'OpenAlex author list', oa_url)
            put('AJ', len(oa_auth), 'OpenAlex author list', oa_url)
        elif cr_auth:
            put('AI', 'Individual author(s)', 'Crossref author list', cr_url)
            put('AJ', len(cr_auth), 'Crossref author list', cr_url)
        elif page:
            rows['AI'] = 'NR'  # Missing publisher metadata is NOT proof of no author.
            rows['AJ'] = 'NR'
        # Optional geographic diversity counts require author-specific institutional countries.
        if oa_auth and len(oa_auth) == rows.get('AJ'):
            all_countries = {x for author in oa_auth for x in (author.get('countries') or []) if x}
            if all_countries:
                put('AK', len(all_countries), 'OpenAlex authorships', oa_url, 'author countries as indexed by OpenAlex')

        def set_author(name_col, affiliation_col, country_col, region_col, income_col, author, source, uri):
            if not author:
                return
            name = author.get('name') or ''
            put(name_col, name or 'NR', source, uri)
            affs = author.get('affiliations') or []
            if len(affs) == 1:
                affiliation = affs[0]
                put(affiliation_col, affiliation, source, uri, 'single affiliation explicitly attached to this author')
                country, region, income = self._affiliation_country(affiliation)
                if country != 'NR':
                    for col, value in [(country_col, country), (region_col, region), (income_col, income)]:
                        put(col, value, source, uri, 'country explicitly named in this author affiliation')
            elif len(affs) > 1:
                review_flags.append(f'{name}: multiple author-specific affiliations; most recent cannot be established')
                # Do not choose the last/first affiliation: list order is NOT recency.
            else:
                review_flags.append(f'{name}: no author-specific affiliation available')

        if authors:
            set_author('AL', 'AM', 'AN', 'AO', 'AP', authors[0], 'PubMed author-specific AffiliationInfo', pm_url)
            set_author('AQ', 'AR', 'AS', 'AT', 'AU', authors[-1], 'PubMed author-specific AffiliationInfo', pm_url)
            if not authors[0].get('group') and not authors[-1].get('group'):
                review_flags.append('Corresponding author not independently identified; not inferred from position')
        elif oa_auth:
            for author, col in [(oa_auth[0], 'AL'), (oa_auth[-1], 'AQ')]:
                name = (author.get('author') or {}).get('display_name') or author.get('raw_author_name')
                put(col, name or 'NR', 'OpenAlex indexed authorship', oa_url)
            review_flags.append('OpenAlex affiliations omitted: institution ordering cannot establish most-recent affiliation')
            # Even OpenAlex is_corresponding is not guaranteed to be an author's actual
            # latest institution; omit until source explicit.
        elif cr_auth:
            for author, col in [(cr_auth[0], 'AL'), (cr_auth[-1], 'AQ')]:
                name = ' '.join(filter(None, [author.get('given'), author.get('family')]))
                put(col, name or 'NR', 'Crossref indexed authorship', cr_url)
            review_flags.append('Crossref author affiliations omitted: correspondence/recency unverified')
        # Author-country fallback for the study's primary geography outcome:
        # match the *same author on this paper*, require a unique country, and
        # leave the institution unfilled. OpenAlex institution lists are NOT
        # chronological and must never become invented "most recent" affiliations.
        def propose_openalex_country(author, country_col, region_col, income_col, name):
            if not author:
                return
            geo = _openalex_author_country(author, self.countries)
            if geo is None:
                return
            country, region, income = geo
            existing_country = rows[country_col]
            if existing_country not in ('', 'NR', 'NOT FOUND'):
                if existing_country != country:
                    review_flags.append(
                        f'{name}: conflicting PubMed/OpenAlex country evidence; '
                        'existing PubMed country retained')
                return
            reason = ('unique country in author-specific OpenAlex authorship on '
                      'this publication; author institution recency not inferred')
            for col, val in ((country_col, country), (region_col, region), (income_col, income)):
                if val != 'NR':
                    put(col, val, 'OpenAlex matched author-country', oa_url, reason)
            review_flags.append(
                f'{name}: author-country inferred from a single OpenAlex work-country; '
                'verify before including in geographic outcomes')

        if oa_auth:
            for pos, country_col, region_col, income_col in (
                (0, 'AN', 'AO', 'AP'), (-1, 'AS', 'AT', 'AU')
            ):
                if authors:
                    person = authors[pos]
                    if person.get('group'):
                        continue
                    author_name = person.get('name') or ''
                    norm_name = _author_name_key(author_name)
                    # A unique, exact normalized name match on the same paper
                    # avoids accidental attribution to a similarly placed author.
                    matched = [a for a in oa_auth
                               if norm_name and
                               _author_name_key((a.get('author') or {}).get('display_name')
                                                or a.get('raw_author_name')) == norm_name]
                    candidate = matched[0] if len(matched) == 1 else None
                else:
                    candidate = oa_auth[pos]
                    author_name = ((candidate.get('author') or {}).get('display_name')
                                   or candidate.get('raw_author_name') or '')
                propose_openalex_country(
                    candidate, country_col, region_col, income_col, author_name)

        # Corresponding fields AV-AZ intentionally remain NR unless authoritative
        # full text explicitly identifies that individual's institution and date.
        journal = pm.get('journal') or ((cr.get('container-title') or [''])[0]) or \
                  ((oa.get('primary_location') or {}).get('source') or {}).get('display_name') or \
                  ((page.get('meta') or {}).get('citation_journal_title') or [''])[0]
        put('BA', journal or 'NR', 'PubMed' if pm.get('journal') else 'Crossref / OpenAlex / publisher', pm_url or cr_url or oa_url)
        # SCImago journal origin / licensed 2026 JCR impact factor require separate evidence.
        for col in ('BB', 'BC', 'BD'):
            rows[col] = 'NOT FOUND'
        rows['BE'] = ''
        openaccess = oa.get('open_access') or {}
        status = openaccess.get('oa_status')
        oa_map = {'gold': 'Open - Gold', 'hybrid': 'Open - Hybrid',
                  'bronze': 'Open - Bronze', 'green': 'Open - Green',
                  'closed': 'Closed (paywalled)'}
        if status in oa_map:
            put('BF', oa_map[status], 'OpenAlex OA status', oa_url)
        elif rows['AD'] in ('Professional society or organization webpage',
                             'Point-of-care resource topic (e.g. UpToDate, DynaMed, StatPearls)'):
            put('BF', 'Not applicable (not a scholarly publication)', 'source category', evidence.get('source_url', ''))
        evidence['field_provenance'] = provenance
        evidence['review_flags'] = review_flags
        return rows
