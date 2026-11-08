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


def normalize_doi(s):
    m = DOI_RE.search(unquote(str(s or '')))
    return m.group().rstrip('.,;)').lower() if m else ''


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
                return json.loads(result) if accept == 'application/json' else result
            except (ValueError, OSError):
                pass
        if self.offline:
            return None
        for attempt in range(3):
            address = url
            try:
                for hop in range(6):
                    if not safe_url(address):
                        raise ValueError('Unsafe redirected URL')
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

    def _pubmed(self, pmid):
        if not pmid:
            return None
        # NCBI's EFetch XML exposes author-specific affiliations and issue dates.
        body = self._get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',
                         {'db': 'pubmed', 'id': pmid, 'retmode': 'xml', 'tool': 'anesthesia-citation-agent',
                          **({'email': self.email} if self.email else {})}, 'application/xml')
        if body and '<!DOCTYPE' not in body[:1000] and '<!ENTITY' not in body[:1000]:
            try:
                return parse_pubmed_xml(body)
            except ET.ParseError:
                self.events.append({'url': 'NCBI PubMed EFetch', 'status': 'invalid_xml'})
        return None

    def metadata(self, citation):
        """Independent lookup pipeline: explicit IDs > PubMed > publisher > constrained title."""
        self.events = []
        url = citation.get('url') or ''
        if url == 'NR':
            url = ''
        raw = citation.get('citation') or ''
        doi = normalize_doi(citation.get('doi')) or normalize_doi(url) or normalize_doi(raw)
        pmid = str(citation.get('pmid') or '')
        if not pmid.isdigit():
            m = re.search(r'(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d{6,9})', url, re.I)
            pmid = m.group(1) if m else ''
        pmc = re.search(r'\bPMC\d{5,10}\b', url, re.I)
        europe = self._europe(pmid, pmc.group() if pmc else '') if pmid or pmc else None
        if europe:
            doi = doi or normalize_doi(europe.get('doi'))
            if not pmid and europe.get('source') == 'MED':
                pmid = str(europe.get('id') or '')
        pubmed = self._pubmed(pmid) if pmid else None
        if pubmed:
            doi = doi or pubmed.get('doi', '')
        cross = None
        oa = None
        if doi and not pmid:
            # Even DOI-only citations can be linked to author-specific PubMed XML.
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
        match = {'method': 'identifier' if doi or pmid else 'none', 'status': 'review_required',
                 'title_similarity': None, 'warnings': []}
        # Do not turn free-form names such as "NEJM, 2019" into title searches.
        title = citation.get('title') or ''
        title_words = re.findall(r'[A-Za-z]{3,}', title)
        if not cross and not oa and not pubmed and not doi and len(title_words) >= 7 and 25 <= len(title) <= 240:
            result = self.fetch_json('https://api.crossref.org/works',
                                     {'query.title': title, 'rows': 2})
            items = ((result or {}).get('message') or {}).get('items') or []
            candidate = items[0] if items else None
            if candidate and quality(title, (candidate.get('title') or [''])[0]) >= .94:
                cross = candidate
                doi = normalize_doi(candidate.get('DOI'))
                if doi:
                    oa_candidate = self.fetch_json('https://api.openalex.org/works/'+quote('https://doi.org/'+doi, safe=':/'))
                    oa = oa_candidate if oa_candidate and oa_candidate.get('id') else None
                match['method'] = 'high_similarity_title_candidate'
                match['warnings'].append('Title search candidate must be verified against original source')
            elif candidate:
                match['warnings'].append('Title search ambiguous; no bibliographic candidate accepted')
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
        if actual_title and title and len(title_words) >= 5:
            match['title_similarity'] = round(quality(title, actual_title), 3)
            if match['title_similarity'] < .65:
                match['warnings'].append('Original cited title differs materially from retrieved publication; manually compare')
        elif actual_title:
            match['warnings'].append('Original title insufficient to confirm publication match')
        return {'doi': doi, 'pmid': pmid, 'crossref': cross, 'openalex': oa,
                'europepmc': europe, 'pubmed': pubmed, 'public_page': page,
                'source_url': url if safe_url(url) else '', 'match': match,
                'lookup_events': list(self.events), 'lookup_performed': not self.offline}

    def _affiliation_country(self, text):
        """Only literal country names/codes in a *specific author's* affiliation."""
        value = str(text or '')
        if not value:
            return 'NR', 'NR', 'NR'
        # Limit this to explicit country tokens, not city/institution assumptions.
        for candidate in sorted(self.countries.values(), key=lambda c: len(c.get('name', '')), reverse=True):
            country = candidate.get('name') or ''
            if country and re.search(r'(?<![a-z])'+re.escape(country)+r'(?![a-z])', value, re.I):
                return country, candidate.get('region') or 'NR', candidate.get('income') or 'NR'
        aliases = {'USA': 'United States', 'U.S.A.': 'United States', 'UK': 'United Kingdom',
                   'U.K.': 'United Kingdom'}
        for alias, full in aliases.items():
            if re.search(r'(?<![a-z])'+re.escape(alias)+r'(?![a-z])', value, re.I):
                match = next((c for c in self.countries.values() if c.get('name') == full), None)
                if match:
                    return full, match.get('region') or 'NR', match.get('income') or 'NR'
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

        def put(col, value, source, url='', reason=''):
            if value is None or value == '':
                return
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
        if any('guideline' in x or 'practice guideline' in x for x in publication_types):
            put('AD', 'Guideline', 'PubMed publication type', pm_url)
        elif any('consensus' in x for x in publication_types):
            put('AD', 'Consensus statement', 'PubMed publication type', pm_url)
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
