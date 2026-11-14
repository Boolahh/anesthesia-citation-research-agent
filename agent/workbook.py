"""Read / update the supplied, formula-heavy workbook without rewriting its analysis sheets.

The template contains millions of bytes of formulas, formatting and validations. A normal
library round-trip can modify unrelated workbook parts. This module surgically edits only
Data_Extraction and Query_Log sheet XML inside the original XLSX zip package.
No spreadsheets, charts, formulas or reviewer columns are regenerated.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
from agent.source_dedup import source_key
from zipfile import ZipFile
import json
import gzip
import re
import tempfile
from xml.etree import ElementTree as ET

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('', NS)
S = lambda x: '{%s}%s' % (NS, x)


def col_index(ref):
    s = re.match(r'[A-Z]+', ref).group()
    value = 0
    for c in s:
        value = value * 26 + ord(c) - 64
    return value


def col_name(i):
    val = ''
    while i:
        i, d = divmod(i - 1, 26)
        val = chr(65 + d) + val
    return val


def cell_value(cell):
    if cell is None:
        return ''
    if cell.get('t') == 'inlineStr':
        return ''.join(cell.find(S('is')).itertext()) if cell.find(S('is')) is not None else ''
    v = cell.find(S('v'))
    return v.text if v is not None and v.text else ''


def sheet_rows(root):
    return {int(r.get('r')):r for r in root.find(S('sheetData')).findall(S('row'))}


def row_dict(row):
    return {re.match(r'[A-Z]+', c.get('r')).group(): cell_value(c) for c in row.findall(S('c'))}


def set_value(row, col, value):
    colnum = col_index(col)
    ref = f'{col}{row.get("r")}'
    cells = row.findall(S('c'))
    c = next((c for c in cells if c.get('r') == ref), None)
    if c is None:
        c = ET.Element(S('c'), {'r': ref})
        for pos, other in enumerate(cells):
            if col_index(other.get('r')) > colnum:
                row.insert(pos, c)
                break
        else:
            row.append(c)
    # Template rows carry an explicit style for every cell; keep it untouched.
    for child in list(c):
        if child.tag in {S('v'), S('is'), S('f')}:
            c.remove(child)
    if value is None or value == '':
        c.set('t', 'n')
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        c.set('t', 'n')
        ET.SubElement(c, S('v')).text = str(value)
    else:
        c.set('t', 'inlineStr')
        is_el = ET.SubElement(c, S('is'))
        t = ET.SubElement(is_el, S('t'))
        if str(value).startswith(' ') or str(value).endswith(' '):
            t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        t.text = str(value)


BLUE_COLS = list('ABCDEFGHIJKL')
GREEN_COLS = [col_name(i) for i in range(26,59)]  # Z ... BF (33 fields)
assert len(GREEN_COLS) == 33 and GREEN_COLS[-1] == 'BF'


@dataclass
class WorkbookData:
    tool_names: dict
    questions: dict
    countries: dict
    categories: dict
    prompts: dict


class TemplateWorkbook:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            archived = self.path.with_suffix(self.path.suffix + '.gz')
            if archived.exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(archived, 'rb') as source:
                    self.path.write_bytes(source.read())
            else:
                raise FileNotFoundError(f'Missing workbook: {self.path}')
        with ZipFile(self.path) as z:
            book = ET.fromstring(z.read('xl/workbook.xml'))
            rel = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            rels = {x.get('Id'): x.get('Target') for x in rel}
            self.sheet_names = {}
            for entry in book.find(S('sheets')).findall(S('sheet')):
                target = rels[entry.get('{%s}id' % REL)]
                target = target.lstrip('/')
                if not target.startswith('xl/'):
                    target = 'xl/' + target
                self.sheet_names[entry.get('name')] = target
            required = ['Data_Extraction','Query_Log','Questions','Tools','Countries','Lists','AI_Prompt']
            for name in required:
                if name not in self.sheet_names:
                    raise ValueError('Missing template sheet: ' + name)
            self.roots = {name: ET.fromstring(z.read(self.sheet_names[name])) for name in required}
        self.data_rows = sheet_rows(self.roots['Data_Extraction'])
        self.log_rows = sheet_rows(self.roots['Query_Log'])
        self.data = self._read_config()
        self.existing = {}
        self.warnings = []
        for rn, row in self.data_rows.items():
            if rn < 4:
                continue
            d = row_dict(row)
            if d.get('A') and d.get('B') and d.get('C'):
                try:
                    key = (d['A'].strip().upper(), d['B'].strip().upper(), int(float(d['C'])))
                    if key in self.existing:
                        self.warnings.append(f'Existing duplicate row key {key}: {rn}')
                    self.existing[key] = rn
                except ValueError:
                    self.warnings.append(f'Invalid existing citation key in row {rn}')
        self.free_rows = [r for r in sorted(self.data_rows) if r >= 4 and not row_dict(self.data_rows[r]).get('A')]
        self.changed = set()
        self.row_for = {}
        self.existing_by_identity = {}
        self._index_source_identities()

    @staticmethod
    def _source_record(data, rownum):
        return {
            'tool': data.get('A') or '', 'question': data.get('B') or '',
            'order': int(float(data.get('C') or 0)), 'excel_row': rownum,
            'citation': data.get('D') or '', 'url': data.get('E') or 'NR',
            'doi': data.get('J') or '', 'pmid': data.get('K') or '',
        }

    def _index_source_identities(self):
        self.existing_by_identity = {}
        for key, rn in self.existing.items():
            d = row_dict(self.data_rows[rn])
            self.existing_by_identity[(key[0], key[1],
                source_key(self._source_record(d, rn)))] = rn

    def compact_existing_sources(self):
        """Safely migrate old occurrence-level workbooks to unique-source rows.

        Never silently discard human judgments or contradictory research values.
        Merge only consistent populated cells, preserving styles and formulas in
        every unaffected workbook part. Conflict means abort without saving.
        """
        by_question = defaultdict(list)
        for (tool, question, order), rn in self.existing.items():
            d = row_dict(self.data_rows[rn])
            record = self._source_record(d, rn)
            by_question[(tool, question)].append(
                (order, rn, source_key(record)))
        plans = []
        affected = {}
        for group, records in by_question.items():
            records.sort(key=lambda x: (x[0], x[1]))
            grouped = {}
            keepers = []
            for order, rn, identity in records:
                if identity not in grouped:
                    grouped[identity] = rn
                    keepers.append(rn)
                else:
                    plans.append((group, grouped[identity], rn))
            if len(keepers) < len(records):
                affected[group] = (len(records), keepers)
        if not plans:
            self._index_source_identities()
            return 0

        # Fully validate BEFORE making any change to avoid partial migration.
        merged = defaultdict(dict)
        for group, keeper, duplicate in plans:
            left = row_dict(self.data_rows[keeper])
            right = row_dict(self.data_rows[duplicate])
            for colnum in range(13, 71):  # M ... BR (human + proposed green)
                col = col_name(colnum)
                current = merged[keeper].get(col, left.get(col, ''))
                other = right.get(col, '')
                current_good = current not in ('', 'NR', 'NOT FOUND', 'Not applicable')
                other_good = other not in ('', 'NR', 'NOT FOUND', 'Not applicable')
                if current_good and other_good and str(current) != str(other):
                    raise ValueError(
                        f'Cannot safely combine duplicate {group[0]}/{group[1]} '
                        f'Excel rows {keeper} and {duplicate}: conflicting {col} '
                        f'values. Review those rows in the original workbook, '
                        'then rerun. Original file remains unchanged.')
                if not current_good and other_good:
                    merged[keeper][col] = other
            for child in self.data_rows[duplicate].findall(S('c')):
                if col_index(child.get('r')) <= 70 and child.find(S('f')) is not None:
                    raise ValueError(
                        f'Cannot clear duplicate Excel row {duplicate} because '
                        'it contains a formula; inspect original workbook.')
        # Only after all checks succeed, migrate fields and free duplicates.
        for keeper, values in merged.items():
            for col, value in values.items():
                if row_dict(self.data_rows[keeper]).get(col, '') != value:
                    set_value(self.data_rows[keeper], col, value)
        for group, keeper, duplicate in plans:
            row = self.data_rows[duplicate]
            for col in list(row_dict(row)):
                if col_index(col) <= 70:
                    set_value(row, col, '')
            self.warnings.append(
                f'Combined older duplicate source row {duplicate} into '
                f'row {keeper} for {group[0]}/{group[1]}. '
                'Human/research fields were preserved if consistent.')
        for (tool, question), (old_count, keepers) in affected.items():
            for new_order, rn in enumerate(keepers, 1):
                row = self.data_rows[rn]
                if row_dict(row).get('C') != str(new_order):
                    set_value(row, 'C', new_order)
                if row_dict(row).get('L') != 'N':
                    set_value(row, 'L', 'N')
            # Column J is the agent-managed query citation count. Correct a
            # historic raw-appearance count only when it matches the old rows.
            key = f'{tool}-{question}'
            log = next((x for x in self.log_rows.values()
                        if row_dict(x).get('A') == key), None)
            if log is not None:
                old = row_dict(log).get('J', '')
                if old in ('', str(old_count)):
                    set_value(log, 'J', len(keepers))
                    self.changed.add('Query_Log')
                elif old != str(len(keepers)):
                    self.warnings.append(
                        f'Preserved nonstandard Query_Log J for {key}; '
                        f'expected unique source count {len(keepers)}')
        # Rebuild all maps from the now-compacted rows.
        self.existing = {}
        for rn, row in sorted(self.data_rows.items()):
            if rn < 4: continue
            d = row_dict(row)
            if d.get('A') and d.get('B') and d.get('C'):
                key = (d['A'].strip().upper(), d['B'].strip().upper(),
                       int(float(d['C'])))
                if key in self.existing:
                    raise ValueError(f'Legacy workbook row-key collision: {key}')
                self.existing[key] = rn
        self.free_rows = [rn for rn in sorted(self.data_rows)
                          if rn >= 4 and not row_dict(self.data_rows[rn]).get('A')]
        self.changed.add('Data_Extraction')
        self._index_source_identities()
        return len(plans)

    def _read_config(self):
        tools = {}
        for no,r in sheet_rows(self.roots['Tools']).items():
            if no == 1: continue
            d=row_dict(r)
            if d.get('A') and d.get('B'): tools[d['A']] = d['B']
        questions={}
        for no,r in sheet_rows(self.roots['Questions']).items():
            if no > 1:
                d=row_dict(r)
                if d.get('A'): questions[d['A']] = d.get('C', d.get('B',''))
        countries={}
        for no,r in sheet_rows(self.roots['Countries']).items():
            if no>1:
                d=row_dict(r)
                if d.get('A') and d.get('B'):
                    countries[d['A']] = dict(name=d['B'], region=d.get('D',''), income=d.get('E',''))
        categories={}
        listroot=self.roots['Lists']
        rlist=sheet_rows(listroot)
        heads=row_dict(rlist[1])
        for col,head in heads.items():
            categories[col]=[row_dict(r).get(col,'') for n,r in sorted(rlist.items()) if n>1 and row_dict(r).get(col)]
        prompts={}
        for no, r in sheet_rows(self.roots['AI_Prompt']).items():
            prompts[no]=row_dict(r).get('A','')
        return WorkbookData(tools,questions,countries,categories,prompts)

    def _next_free_row(self):
        if not self.free_rows:
            raise RuntimeError('Data_Extraction has no empty rows left (capacity: 3500 citations)')
        return self.free_rows.pop(0)

    def upsert_blue(self, citation):
        tool, question = citation['tool'], citation['question']
        identity = (tool, question, source_key(citation))
        rn = self.existing_by_identity.get(identity)
        if rn is not None:
            # Reuse the previously reviewed/source-enriched row even when a
            # new PDF lists its sources in a different order.
            original = row_dict(self.data_rows[rn])
            citation['order'] = int(float(original['C']))
        else:
            order = int(citation['order'])
            if (tool, question, order) in self.existing:
                order = max(
                    (idx for a, q, idx in self.existing if a == tool and q == question),
                    default=0) + 1
                citation['order'] = order
            rn = self._next_free_row()
            self.existing[(tool, question, order)] = rn
            self.existing_by_identity[identity] = rn
        key = (tool, question, int(citation['order']))
        row=self.data_rows[rn]
        old=row_dict(row)
        fields=[citation['tool'],citation['question'],int(citation['order']),citation.get('citation') or 'NR',
                citation.get('url') or 'NR',citation.get('title') or 'NR',citation.get('authors') or 'NR',
                citation.get('year') or 'NR',citation.get('journal') or 'NR',citation.get('doi') or 'NR',
                citation.get('pmid') or 'NR',citation.get('repeat') or 'N']
        for col,val in zip(BLUE_COLS,fields):
            previous=old.get(col,'')
            if previous and str(previous) != str(val):
                self.warnings.append(f'Preserved existing {col}{rn}; attempted conflicting value for {key}: {str(val)[:90]}')
                continue
            if not previous:
                set_value(row,col,val)
                self.changed.add('Data_Extraction')
        self.row_for[key]=rn
        return rn

    def get_row(self, rownum):
        return row_dict(self.data_rows[rownum])

    def upsert_green(self, rownum, values, policy='verified-only'):
        row=self.data_rows[rownum]
        old=row_dict(row)
        verdict=(old.get('U') or '').lower()
        if policy=='verified-only' and not verdict.startswith('real -'):
            return False
        if verdict.startswith('hallucinated') or verdict.startswith('cannot verify'):
            return False
        if len(values)!=33:
            raise ValueError(f'Expected 33 green fields, found {len(values)}')
        written=False
        for col,val in zip(GREEN_COLS,values):
            # JCR must never be guessed; leave 2026 impact factor empty unless reliably available.
            if col == 'BE' and val in ('NR','NOT FOUND','Not applicable'):val=''
            if val is None:val='NOT FOUND' if col!='BE' else ''
            previous=old.get(col,'')
            if previous and str(previous)!=str(val):
                self.warnings.append(f'Preserved existing human/AI-edited {col}{rownum}; conflicting proposal')
                continue
            if not previous and val!='':
                set_value(row,col,val)
                written=True
        if written:self.changed.add('Data_Extraction')
        return written

    def update_query_log(self, tool, question, count, paths, incomplete=False):
        query=f'{tool}-{question}'
        match = next((r for r in self.log_rows.values() if row_dict(r).get('A')==query), None)
        if match is None:
            self.warnings.append(f'No Query_Log match for {query}')
            return
        data=row_dict(match)
        # User / investigator owns Done?, Date asked, Investigator, and all review metadata.
        if not incomplete and data.get('J') != str(count):
            # J is the agent's citation-count field; after source
            # consolidation it reflects unique sources, not appearances.
            set_value(match, 'J', count)
            self.changed.add('Query_Log')
        if not data.get('K'):
            set_value(match,'K', '; '.join(sorted(set(paths)))[:900])
            self.changed.add('Query_Log')
        if incomplete:self.warnings.append(f'{query} has no preserved clickable citations; inspect the original export')

    def save(self, path):
        out=Path(path);out.parent.mkdir(parents=True, exist_ok=True)
        src=self.path.resolve()
        if src == out.resolve():
            raise ValueError('Refusing to overwrite original workbook; use a different output path')
        modified={self.sheet_names[n]: ET.tostring(self.roots[n],encoding='utf-8',xml_declaration=True) for n in self.changed}
        # Preserve unrelated OOXML components byte-for-byte *after decompression*;
        # preserve metadata, compression and existing parts. No analysis-sheet rewrite.
        with ZipFile(self.path, 'r') as zin, ZipFile(out, 'w') as zout:
            for entry in zin.infolist():
                if entry.filename in modified:
                    zout.writestr(entry,modified[entry.filename])
                else:
                    with zin.open(entry.filename) as fp:
                        zout.writestr(entry,fp.read())
        return out
