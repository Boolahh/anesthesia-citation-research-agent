"""Evidence collection from public Crossref, OpenAlex, Europe PMC and citation URLs.

This module proposes bibliographic fields; it does NOT make a human citation-verdict decision.
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse, quote, unquote, urljoin
from collections import OrderedDict
from difflib import SequenceMatcher
import ipaddress
import json
import os
import re
import socket
import time

import requests
from bs4 import BeautifulSoup

from .pdf_extract import DOI_RE, rough_fields
from .workbook import GREEN_COLS

USER_AGENT='AnesthesiaCitationBiasResearchAgent/1.0 (bibliographic-research; contact configured by operator)'
PUBLIC_APIS={'api.crossref.org','api.openalex.org','www.ebi.ac.uk'}


def safe_url(url):
    """Reject local / private URLs in material supplied by third-party AI models."""
    try:
        u=urlparse(url)
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:
            return False
        h=u.hostname.lower().rstrip('.')
        if h in ('localhost','localhost.localdomain') or h.endswith(('.localhost','.local','.internal','.onion','.test')):
            return False
        try:
            ip=ipaddress.ip_address(h)
            if not ip.is_global:return False
        except ValueError: pass
        return True
    except Exception:return False


def norm_title(s):
    return re.sub(r'[^a-z0-9]','',s.lower())


def quality(a,b):
    a=norm_title(a or '')
    b=norm_title(b or '')
    if not a or not b:return 0
    return SequenceMatcher(None,a,b).ratio()


def normalize_doi(s):
    m=DOI_RE.search(unquote(str(s or '')))
    return m.group().rstrip('.,;').lower() if m else ''


def iso2_country(code,countries):
    if not code:return ('NR','NR','NR')
    iso3=''
    try:
        import pycountry
        country=pycountry.countries.get(alpha_2=code.upper())
        iso3=country.alpha_3 if country else ''
    except (ImportError,LookupError):pass
    if code.upper()=='XK':iso3='XKX'
    d=countries.get(iso3)
    if not d:return ('NR','NR','NR')
    return d.get('name','NR') or 'NR', d.get('region','NR') or 'NR', d.get('income','NR') or 'NR'


class Bibliography:
    def __init__(self,countries,cache_dir,email='',timeout=18,offline=False):
        self.countries=countries
        self.cache_dir=Path(cache_dir);self.cache_dir.mkdir(parents=True,exist_ok=True)
        self.timeout=timeout;self.offline=offline
        self.s=requests.Session()
        self.s.headers['User-Agent']=USER_AGENT+(f' mailto:{email}' if email else '')
        self.email=email

    def fetch_json(self,url,params=None):
        import hashlib
        if not safe_url(url):return None
        key=json.dumps([url,params],sort_keys=True)
        cache=self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:24]+'.json')
        if cache.exists():
            try:return json.loads(cache.read_text(encoding='utf-8'))
            except (ValueError,OSError):pass
        if self.offline:return None
        for attempt in range(3):
            try:
                r=self.s.get(url,params=params,timeout=self.timeout,allow_redirects=False)
                if r.is_redirect:
                    url=urljoin(url,r.headers.get('Location',''))
                    if not safe_url(url):return None
                    continue
                if r.status_code in (429,500,502,503) and attempt<2:
                    time.sleep(1+attempt*2);continue
                if r.status_code!=200:return None
                data=r.json()
                cache.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
                return data
            except (requests.RequestException,ValueError):return None
        return None

    def public_page(self,url):
        if self.offline or not safe_url(url):return None
        # Only use HTML on accessible public sources. Never enter credentials/cookies.
        try:
            for _ in range(3):
                r=self.s.get(url,timeout=self.timeout,allow_redirects=False,headers={'Accept':'text/html,application/xhtml+xml'})
                if r.is_redirect:
                    url=urljoin(url,r.headers.get('Location',''))
                    if not safe_url(url):return None
                    continue
                if r.status_code!=200:return None
                if 'html' not in r.headers.get('Content-Type','').lower():return None
                if len(r.content)>5_000_000:return None
                soup=BeautifulSoup(r.text,'html.parser')
                meta={}
                for m in soup.find_all('meta'):
                    key=m.get('name') or m.get('property')
                    value=m.get('content')
                    if key and value and key.lower() in ('citation_title','citation_doi','citation_author','citation_date','citation_publication_date',
                                'citation_journal_title','citation_pmid','og:title','dc.title'):
                        meta.setdefault(key,[]).append(value)
                for x in soup(['script','style','nav','footer','header','noscript']):x.decompose()
                # Do not submit entire copyrighted articles to the model: only a short passage.
                body=' '.join(soup.stripped_strings)
                return {'url':url,'title':soup.title.get_text(' ',strip=True) if soup.title else '',
                        'meta':meta,'excerpt':body[:7500]}
        except (requests.RequestException,ValueError):pass
        return None

    def metadata(self,citation):
        url=citation.get('url','')
        raw=citation.get('citation','')
        doi=normalize_doi(citation.get('doi')) or normalize_doi(url) or normalize_doi(raw)
        pmid=str(citation.get('pmid','')) if str(citation.get('pmid','')).isdigit() else ''
        pmc=re.search(r'/articles/(PMC\d+)',url,re.I)
        cross=None; openalex=None; europe=None
        if pmid or pmc:
            query=('EXT_ID:'+pmc.group(1)) if pmc else ('EXT_ID:'+pmid+' AND SRC:MED')
            e=self.fetch_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':query,'format':'json','pageSize':1})
            try:europe=e.get('resultList',{}).get('result',[])[0]
            except (TypeError,IndexError,AttributeError): pass
            if europe:
                doi=doi or normalize_doi(europe.get('doi',''))
                pmid=pmid or europe.get('id','') if europe.get('source')=='MED' else pmid
        if doi:
            c=self.fetch_json('https://api.crossref.org/works/'+quote(doi,safe='/'))
            cross=(c or {}).get('message')
            a=self.fetch_json('https://api.openalex.org/works/'+quote('https://doi.org/'+doi,safe=':/'))
            if a and a.get('id'):openalex=a
        if not openalex and pmid:
            a=self.fetch_json('https://api.openalex.org/works',{'filter':'pmid:https://pubmed.ncbi.nlm.nih.gov/'+pmid,'per-page':1})
            results=(a or {}).get('results',[])
            if results:openalex=results[0]
        # Constrained title search only when the title is substantial; never accept it as verified automatically.
        label=citation.get('title','')
        if not cross and not openalex and not doi and len(label)>28:
            c=self.fetch_json('https://api.crossref.org/works',{'query.title':label,'rows':1})
            items=((c or {}).get('message') or {}).get('items',[])
            if items and quality(label, (items[0].get('title') or [''])[0])>=.87:
                cross=items[0];doi=normalize_doi(cross.get('DOI',''))
                a=self.fetch_json('https://api.openalex.org/works/'+quote('https://doi.org/'+doi,safe=':/')) if doi else None
                if a and a.get('id'):openalex=a
        page=self.public_page(url) if url and url!='NR' else None
        # Retrieve DOI from publisher meta tags when no DOI supplied, without assuming it is a match.
        if not doi and page:
            extra=page['meta'].get('citation_doi',[])
            if extra:doi=normalize_doi(extra[0])
            if doi:
                c=self.fetch_json('https://api.crossref.org/works/'+quote(doi,safe='/'))
                cross=(c or {}).get('message') or cross
                a=self.fetch_json('https://api.openalex.org/works/'+quote('https://doi.org/'+doi,safe=':/'))
                if a and a.get('id'):openalex=a
        return {'doi':doi,'pmid':pmid,'crossref':cross,'openalex':openalex,'europepmc':europe,'public_page':page,
                'source_url':url if safe_url(url) else '',
                'lookup_performed':not self.offline}

    def baseline_green(self, evidence):
        oa=evidence.get('openalex') or {};cr=evidence.get('crossref') or {}; ep=evidence.get('europepmc') or {}
        page=evidence.get('public_page') or {}
        rows={col:'NOT FOUND' for col in GREEN_COLS}
        rows['Z']=oa.get('display_name') or ((cr.get('title') or [''])[0]) or ep.get('title') or \
                  ((page.get('meta') or {}).get('citation_title') or [''])[0] or 'NOT FOUND'
        rows['AA']=oa.get('publication_year') or ep.get('pubYear') or ''
        if not rows['AA']:
            dp=cr.get('published') or cr.get('created') or {}
            rows['AA']=((dp.get('date-parts') or [[]])[0] or [''])[0]
        if not rows['AA']:rows['AA']='NOT FOUND'
        rows['AB']=evidence.get('doi') or 'NR'
        rows['AC']=evidence.get('pmid') or 'NR'
        ct=(cr.get('type') or oa.get('type') or '').lower()
        pageurl=evidence.get('source_url','')
        if ct in ('journal-article','article','review','research-article','journal article'):
            rows['AD']='Journal article'
        elif ct in ('book','book-chapter','book-section'):rows['AD']='Textbook or book chapter'
        elif ct in ('posted-content','preprint'):rows['AD']='Preprint'
        elif ct in ('proceedings-article','proceedings'):rows['AD']='Conference abstract or proceedings'
        elif ct in ('report','report-series'):rows['AD']='Other (describe in Notes)'
        elif 'ncbi.nlm.nih.gov/books/' in pageurl:rows['AD']='Point-of-care resource topic (e.g. UpToDate, DynaMed, StatPearls)'
        elif page:rows['AD']='Professional society or organization webpage' if \
               any(x in urlparse(pageurl).hostname.lower() for x in ('asahq','apsf','ficm','openanesthesia','entnet')) else 'NR'
        else:rows['AD']='NR'
        rows['AE']='Not a research study (guideline, textbook, website...)' if rows['AD'] in (
           'Guideline','Consensus statement','Textbook or book chapter',
           'Point-of-care resource topic (e.g. UpToDate, DynaMed, StatPearls)',
           'Professional society or organization webpage') else 'NR'
        rows['AF']='NR';rows['AG']='NR'
        rows['AH']=oa.get('cited_by_count') if oa.get('id') else 'NR'
        authorships=oa.get('authorships',[])
        ca=cr.get('author',[])
        rows['AI']='Individual author(s)' if authorships or ca else 'No author listed' if page else 'NR'
        rows['AJ']=len(authorships) if authorships else len(ca) if ca else 0 if page else 'NR'
        countries_all=set()
        for author in authorships:
            for country in author.get('countries',[]):
                if country:countries_all.add(country)
            for ins in author.get('institutions',[]):
                if ins.get('country_code'):countries_all.add(ins['country_code'])
        rows['AK']=len(countries_all) if authorships else 'NR'

        def author_fields(author,prefix):
            if not author:return
            name=(author.get('author') or {}).get('display_name') or author.get('raw_author_name')
            rows[prefix[0]]=name or 'NR'
            institution='NR';country='NR';region='NR';income='NR'
            # Crossref+OpenAlex often omit author-affiliation chronology. Use *last listed* only as provisional.
            ins=author.get('institutions') or []
            if ins:
                institution=ins[-1].get('display_name') or 'NR'
                country,region,income=iso2_country(ins[-1].get('country_code'),self.countries)
            if institution=='NR' and author.get('raw_affiliation_strings'):
                institution=author['raw_affiliation_strings'][-1]
            rows[prefix[1]],rows[prefix[2]],rows[prefix[3]],rows[prefix[4]]=institution,country,region,income
        if authorships:
            author_fields(authorships[0],['AL','AM','AN','AO','AP'])
            author_fields(authorships[-1],['AQ','AR','AS','AT','AU'])
            correspond=next((x for x in authorships if x.get('is_corresponding') is True),None)
            author_fields(correspond,['AV','AW','AX','AY','AZ'])
        elif ca:
            for a,p in [(ca[0],['AL','AM','AN','AO','AP']),(ca[-1],['AQ','AR','AS','AT','AU'])]:
                rows[p[0]]=' '.join([a.get('given',''),a.get('family','')]).strip() or 'NR'
                aff=a.get('affiliation') or []
                if aff:rows[p[1]]=aff[-1].get('name') or 'NR'
        src=(oa.get('primary_location') or {}).get('source') or {}
        rows['BA']=src.get('display_name') or ((cr.get('container-title') or [''])[0]) or \
                   ((page.get('meta') or {}).get('citation_journal_title') or [''])[0] or 'NR'
        # Journal country must come from SCImago per the protocol; NOT from OA publisher location.
        rows['BB']='NOT FOUND';rows['BC']='NOT FOUND';rows['BD']='NOT FOUND';rows['BE']=''
        openaccess=oa.get('open_access') or {}
        status=openaccess.get('oa_status')
        oa_map={'gold':'Open - Gold','hybrid':'Open - Hybrid','bronze':'Open - Bronze',
                'green':'Open - Green','closed':'Closed (paywalled)'}
        rows['BF']=oa_map.get(status,'Not applicable (not a scholarly publication)' if rows['AD'] in (
            'Professional society or organization webpage','Point-of-care resource topic (e.g. UpToDate, DynaMed, StatPearls)')
             else 'NR')
        return rows
