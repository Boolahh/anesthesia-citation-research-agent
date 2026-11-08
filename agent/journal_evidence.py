"""Optional investigator-supplied, source-verified SCImago/JCR journal attributes.

No unlicensed scraping. Supplying a record means the user independently
verified the journal identity and has rights to use the licensed metric.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
import csv
import re

from .research import norm_title


def _valid_url(value, host):
    u=urlparse(value)
    return u.scheme == 'https' and u.hostname and (u.hostname == host or u.hostname.endswith('.'+host))


def load_journal_evidence(path, countries):
    """Validate the entire input file before accepting any supplied values."""
    if not path:
        return {}
    valid_countries={d['name'] for d in countries.values()}
    result={}
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rows=csv.DictReader(f)
        expected={'journal_name','country','scimago_url','impact_factor_2026','jcr_evidence_id','date_checked'}
        if not rows.fieldnames or not expected.issubset(rows.fieldnames):
            raise ValueError('Journal evidence CSV requires headers: '+', '.join(sorted(expected)))
        for number,row in enumerate(rows,2):
            journal=(row.get('journal_name') or '').strip()
            country=(row.get('country') or '').strip()
            scimago=(row.get('scimago_url') or '').strip()
            jif=(row.get('impact_factor_2026') or '').strip()
            jcr=(row.get('jcr_evidence_id') or '').strip()
            date=(row.get('date_checked') or '').strip()
            if not journal:
                continue
            if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}',date):
                raise ValueError(f'Journal evidence row {number}: date_checked must be YYYY-MM-DD')
            if country and (country not in valid_countries or not _valid_url(scimago,'scimagojr.com')):
                raise ValueError(f'Journal evidence row {number}: journal country requires workbook country and a SCImago URL')
            if jif:
                if not jcr:
                    raise ValueError(f'Journal evidence row {number}: JIF requires a JCR source record ID')
                try:
                    numeric=float(jif)
                except ValueError as exc:
                    raise ValueError(f'Journal evidence row {number}: impact factor must be numeric') from exc
                if numeric<0 or numeric>1000 or numeric!=numeric:
                    raise ValueError(f'Journal evidence row {number}: unreasonable impact factor')
            key=norm_title(journal)
            if key in result:
                raise ValueError(f'Journal evidence row {number}: duplicate journal name')
            result[key]={'journal_name':journal,'country':country,'scimago_url':scimago,
                         'impact_factor_2026':jif,'jcr_evidence_id':jcr,'date_checked':date}
    return result


def supplement_journal_fields(green, evidence, database, countries):
    """Only fill a confidently matched journal with investigator verified data."""
    journal=green.get('BA') or ''
    key=norm_title(journal)
    if not key or key not in database or green.get('AD') not in ('Journal article','Guideline','Consensus statement'):
        return green
    entry=database[key]
    if entry.get('country'):
        country=entry['country']
        x=next((x for x in countries.values() if x['name']==country),None)
        if x:
            green['BB'],green['BC'],green['BD']=country,x['region'],x['income']
            for col in ('BB','BC','BD'):
                evidence.setdefault('field_provenance',{})[col]={
                    'source':'Investigator-verified SCImago', 'url':entry['scimago_url'],
                    'reason':'Journal identity confirmed manually; checked '+entry['date_checked']}
    if entry.get('impact_factor_2026'):
        green['BE']=entry['impact_factor_2026']
        evidence.setdefault('field_provenance',{})['BE']={
            'source':'Investigator-supplied licensed 2026 Journal Citation Reports',
            'url':'', 'reason':'JCR record '+entry['jcr_evidence_id']+', checked '+entry['date_checked']}
    return green
