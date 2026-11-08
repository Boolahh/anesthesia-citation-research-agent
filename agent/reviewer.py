"""Explicit, audited *human* verification entries into the original workbook.

The agent never constructs these decisions. Only a human-edited CSV (or UI
controls) can set human-only fields, with validation and overwrite protection.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import csv
import hashlib
import json
from datetime import datetime, timezone

from .workbook import TemplateWorkbook, row_dict, set_value

HUMAN_COLUMNS = {
    'verifier_initials': 'T', 'verdict': 'U', 'error_type': 'V',
    'link_status': 'W', 'verified_url': 'X', 'ai_row_checked': 'Y',
    'coding_verifier': 'BP', 'coding_checked': 'BQ', 'notes': 'BR',
}
ENUMS = {
    'verdict': 'K', 'error_type': 'L', 'link_status': 'T',
    'ai_row_checked': 'E', 'coding_checked': 'M',
}


def _id(row):
    return row['tool'].strip().upper(), row['question'].strip().upper(), int(row['order'])


def decision_template(workbook):
    """Build a CSV skeleton to facilitate review, without making any verdicts."""
    rows=[]
    for (tool, question, order), rn in sorted(workbook.existing.items()):
        data=workbook.get_row(rn)
        rows.append({'tool':tool,'question':question,'order':order,
                     'citation_as_shown':data.get('D',''), 'original_url':data.get('E',''),
                     **{key:data.get(col,'') for key,col in HUMAN_COLUMNS.items()}})
    return rows


def _check_value(workbook, key, value):
    if not value:
        return
    if key in ENUMS and value not in workbook.data.categories.get(ENUMS[key], []):
        raise ValueError(f'Invalid {key} choice {value!r}; use the original workbook dropdown values')
    if key == 'verified_url':
        address=urlparse(value)
        if address.scheme not in ('http','https') or not address.hostname or address.username or address.password:
            raise ValueError('verified_url must be a full http(s) URL')
    if key.endswith('initials') or key=='coding_verifier':
        if len(value)>40:
            raise ValueError('Reviewer initials field is too long')
    if len(value)>10000:
        raise ValueError('Human entry exceeds 10,000 characters')


def apply_decisions(workbook, decisions, *, allow_overwrite=False):
    """Atomic validation: reject the entire batch before editing a single cell."""
    pending=[]
    seen=set()
    for decision in decisions:
        key=_id(decision)
        if key in seen:
            raise ValueError(f'Duplicate human decision for {key}')
        seen.add(key)
        rn=workbook.existing.get(key)
        if rn is None:
            raise ValueError(f'Review key not present in workbook: {key}')
        actual=workbook.get_row(rn)
        changes={}
        for name, col in HUMAN_COLUMNS.items():
            new=str(decision.get(name,'') or '').strip()
            if not new:
                continue
            _check_value(workbook, name, new)
            previous=actual.get(col,'')
            if previous and previous != new and not allow_overwrite:
                raise ValueError(f'{col}{rn} already contains a reviewer decision; explicit overwrite required')
            if previous!=new:
                changes[col]=new
        if changes:
            pending.append((key, rn, changes))
    audit=[]
    for key,rn,changes in pending:
        row=workbook.data_rows[rn]
        for col,new in changes.items():
            set_value(row,col,new)
        workbook.changed.add('Data_Extraction')
        audit.append({'tool':key[0], 'question':key[1], 'order':key[2],
                      'excel_row':rn, 'columns_changed':sorted(changes)})
    return audit


def write_review_csv(path,rows):
    import io
    fieldnames=['tool','question','order','citation_as_shown','original_url',*HUMAN_COLUMNS]
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fieldnames,extrasaction='ignore')
        w.writeheader();w.writerows(rows)


def load_review_csv(path):
    with open(path,encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))
