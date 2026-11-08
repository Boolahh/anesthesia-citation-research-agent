#!/usr/bin/env python3
"""Reproducible AI citation audit: PDFs -> as-cited columns -> sourced proposals.

All research assignments remain provisional pending human source verification. No
credentials or original chat PDFs are written to GitHub. Designed for mixed
platforms, resumable batch research, and auditable study data.
"""
from __future__ import annotations

from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import hashlib
import json
import os
import re
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent/'.env')
except ImportError:
    pass

from agent.workbook import TemplateWorkbook, GREEN_COLS
from agent.pdf_extract import (parse_pdf, inspect_unresolved_pdf,
                               citation_identity, weak_visible_citation_label)
from agent.research import Bibliography, quality
from agent.journal_evidence import load_journal_evidence, supplement_journal_fields

ROOT = Path(__file__).resolve().parent
APP_VERSION = '2.1.0'


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def checksum(path):
    dig = hashlib.sha256()
    with open(path, 'rb') as source:
        while True:
            data = source.read(2**18)
            if not data:
                break
            dig.update(data)
    return dig.hexdigest()


def file_tool(path, known, default=None, root=None):
    """Match one of the exact 16 codes, avoiding ChatGPT/Clinicians collisions."""
    path = Path(path)
    parents = [path.parent.name]
    if root:
        try:
            parents = [x.name for x in path.relative_to(root).parents if x.name not in ('.', '')]
        except ValueError:
            pass
    for folder in parents:
        if folder.upper() in known:
            return folder.upper()
    stem = path.stem.lower()
    match = re.match(r'^([a-z]{3})(?:[_\- .]|$)', stem, re.I)
    if match and match.group(1).upper() in known:
        return match.group(1).upper()
    normalized = re.sub(r'[^a-z0-9]', '', stem)
    aliases = {
        'CGC': ['chatgptforclinicians'], 'CGP': ['chatgpt'], 'CLG': ['claude'],
        'CKA': ['clinicalkey'], 'CON': ['consensus'], 'DSK': ['deepseek'],
        'DOX': ['doximity'], 'DRI': ['drinfo'], 'DYN': ['dynaai', 'dynamed'],
        'GLA': ['glasshealth'], 'GEM': ['googlegemini', 'gemini'],
        'HEI': ['heidievidence', 'heidi'], 'COP': ['microsoftcopilot', 'copilot'],
        'OEV': ['openevidence'], 'UTD': ['uptodate'], 'VER': ['verahealth', 'vera'],
    }
    found = sorted([(len(alias), code, alias) for code, words in aliases.items() if code in known
                    for alias in words if alias in normalized], reverse=True)
    if found:
        best = found[0]
        conflicts = [x for x in found[1:] if x[1] != best[1] and x[2] not in best[2]]
        # 'ChatGPT for Clinicians' includes 'ChatGPT': choose the longer one.
        # Independent matches such as 'Claude vs ChatGPT' are ambiguous.
        if not conflicts:
            return best[1]
    return default if default in known else None


def choose_ai(args):
    if args.no_ai or args.offline:
        return None
    if not os.getenv('OPENAI_API_KEY'):
        print('[INFO] AI API key absent; proceeding with public bibliographic lookup only.')
        return None
    from agent.llm import ResearchAI
    return ResearchAI()


def gather(args, workbook, ai):
    root = Path(args.input)
    if root.is_dir():
        paths = sorted(x for x in root.rglob('*.pdf') if x.is_file())
    else:
        paths = [root] if root.is_file() and root.suffix.lower() == '.pdf' else []
    if args.max_docs:
        paths = paths[:args.max_docs]
    if not paths:
        raise RuntimeError('No PDF files found. Upload PDFs for blue/all; for research-only, use a reviewed workbook.')
    collected, warnings, documents, known_hashes = [], [], [], {}
    for path in paths:
        tool = file_tool(path, workbook.data.tool_names, args.tool, root)
        if not tool:
            warnings.append({'file': path.name, 'warning': 'AI tool unknown; use the model selector or a folder named with its tool code'})
            continue
        digest = checksum(path)
        # Identical outputs from DIFFERENT AI tools are independent study data.
        # Skip only repeated byte-for-byte exports within the same model.
        duplicate_key = (tool, digest)
        if duplicate_key in known_hashes:
            warnings.append({'file': path.name, 'warning': f'Duplicate PDF within {tool}, identical to {known_hashes[duplicate_key].name}; skipped'})
            continue
        known_hashes[duplicate_key] = path
        try:
            citations, issues = parse_pdf(path, tool, workbook.data.questions, ai)
        except Exception as exc:
            warnings.append({'file': path.name, 'warning': f'PDF parse failed: {type(exc).__name__}: {str(exc)[:150]}'})
            continue
        collected.extend(citations)
        per_question = defaultdict(list)
        for citation in citations:
            citation['pdf_sha256'] = digest
            per_question[citation['question']].append(citation)
        if not per_question:
            diagnostic = inspect_unresolved_pdf(path)
            inferred = diagnostic.get('question_inferred_from_filename')
            zero_message = ('Zero recoverable citations for '+inferred+
                            '; confirm whether the Claude PDF contains sources'
                            if inferred else
                            'Zero recoverable citations; original question could not be established')
            # A failed extraction is explicitly *not* a verified zero-citation
            # answer. Keep it distinguishable from an investigator-coded zero.
            warnings.append({'file': path.name, 'question': inferred,
                             'warning': zero_message})
            if diagnostic['possible_image_only_export']:
                warnings.append({'file': path.name, 'question': inferred,
                                 'warning': 'Image-only PDF suspected; OCR or text-selectable re-export required'})
            documents.append({'file': path.name, 'tool': tool, 'question': inferred,
                              'citations': 0, 'with_urls': 0, 'pdf_sha256': digest,
                              'warnings': issues+[zero_message], 'pdf_diagnostics': diagnostic})
        for question, rows in per_question.items():
            documents.append({'file': path.name, 'tool': tool, 'question': question,
                              'citations': len(rows), 'with_urls': sum(x['url'] != 'NR' for x in rows),
                              'pdf_sha256': digest, 'warnings': issues})
        warnings.extend({'file': path.name, 'warning': issue} for issue in issues)
        print(f'[PDF] {path.name} [{tool}]: {len(citations)} citation candidate(s)')
    grouped = defaultdict(list)
    for citation in collected:
        grouped[(citation['tool'], citation['question'])].append(citation)
    result = []
    for key in sorted(grouped):
        seen = set()
        for i, citation in enumerate(grouped[key], 1):
            citation['order'] = i
            identity = citation_identity(citation)
            citation['repeat'] = 'Y' if identity in seen else 'N'
            seen.add(identity)
            result.append(citation)
    return result, documents, warnings


def clean_category(value, allowed):
    if value in allowed or value in ('NR', 'NOT FOUND', 'Not applicable', ''):
        return value
    return 'NR'


def refine_green(green, workbook):
    categories = workbook.data.categories
    for col, code in [('AD', 'F'), ('AE', 'H'), ('AF', 'N'), ('AG', 'J'), ('AI', 'G'), ('BF', 'I')]:
        green[col] = clean_category(green.get(col, 'NR'), categories.get(code, []))
    country_map = {x['name']: (x['region'], x['income']) for x in workbook.data.countries.values()}
    for c, r, i in [('AN', 'AO', 'AP'), ('AS', 'AT', 'AU'), ('AX', 'AY', 'AZ'), ('BB', 'BC', 'BD')]:
        country = green.get(c, 'NR')
        if country in country_map:
            green[r], green[i] = country_map[country]
        elif country in ('', 'NR', 'NOT FOUND', 'Not applicable'):
            green[r] = 'NR' if country != 'NOT FOUND' else 'NOT FOUND'
            green[i] = green[r]
        else:
            # Unsupported country spelling: review it; never guess WHO/income.
            green[c], green[r], green[i] = 'NOT FOUND', 'NOT FOUND', 'NOT FOUND'
    green['BE'] = ''  # 2026 JCR requires a licensed verified source.
    return green


def enrich(citation, workbook, bibliography, ai, journal_evidence=None):
    evidence = bibliography.metadata(citation)
    proposed = bibliography.baseline_green(evidence)
    warnings = list(evidence.get('match', {}).get('warnings') or []) + list(evidence.get('review_flags') or [])
    match = evidence.get('match', {})
    # A guideline's title year and an article's online-first year often differ
    # from its journal issue year. Flag the discrepancy for a reviewer, but
    # never autonomously classify it as a citation error.
    blue_year = str(citation.get('year') or '').strip()
    issue_year = str(proposed.get('AA') or '').strip()
    if (re.fullmatch(r'(?:19|20)\d{2}', blue_year)
            and re.fullmatch(r'(?:19|20)\d{2}', issue_year)
            and blue_year != issue_year):
        online_year = str((evidence.get('pubmed') or {}).get('online_year') or '').strip()
        context = ('original year matches the online-first publication year'
                   if online_year == blue_year else
                   'may reflect a guideline-version year or online-first date')
        warnings.append(
            f'As-cited year {blue_year} differs from journal issue year {issue_year}; '
            f'{context}. Reviewer must determine whether this is an actual citation error.'
        )
    if ai and any(evidence.get(k) for k in ('crossref', 'openalex', 'pubmed', 'europepmc', 'public_page')):
        source_context = {k: evidence.get(k) for k in ('doi', 'pmid', 'crossref', 'openalex', 'pubmed', 'europepmc', 'public_page')}
        guidelines = '\n'.join(workbook.data.prompts.get(n, '') for n in range(44, 88))
        try:
            coded = ai.code_source(citation, source_context,
                {name: workbook.data.categories.get(code, []) for code, name in [
                    ('F', 'Type of source'), ('G', 'Author type'), ('H', 'Study design'),
                    ('I', 'Open access'), ('J', 'Funding'), ('N', 'Subspecialty')]}, guidelines)
            if len(coded) != len(GREEN_COLS):
                raise ValueError('AI returned an incorrect number of research fields')
            # AI may propose missing columns, but must not override sourced facts;
            # author affiliations and corresponding-author details need primary evidence.
            restricted = {'AL','AM','AN','AO','AP','AQ','AR','AS','AT','AU','AV','AW','AX','AY','AZ','BB','BC','BD','BE'}
            for col, value in zip(GREEN_COLS, coded):
                if col in restricted or value in ('', 'NR', 'NOT FOUND', None):
                    continue
                if proposed[col] in ('NR', 'NOT FOUND', ''):
                    proposed[col] = value
                    evidence.setdefault('field_provenance', {})[col] = {
                        'source': 'AI proposal from retrieved evidence', 'url': '',
                        'reason': 'Requires independent reviewer verification'}
        except Exception as exc:
            warnings.append('Optional AI coding failed: '+str(exc)[:160])
    proposed = refine_green(proposed, workbook)
    if journal_evidence:
        proposed = supplement_journal_fields(proposed, evidence, journal_evidence, workbook.data.countries)
    has_metadata = any(evidence.get(k) for k in ('crossref', 'openalex', 'pubmed', 'europepmc', 'public_page'))
    informative_fields = sum(value not in ('', 'NR', 'NOT FOUND', 'Not applicable', None)
                             for value in proposed.values())
    critical = any('conflicts with' in msg or 'differs materially' in msg for msg in warnings)
    return {
        'fields': proposed, 'has_metadata': has_metadata,
        'informative_fields': informative_fields,
        'can_autowrite': has_metadata and informative_fields > 0 and not critical,
        'record_url': evidence.get('source_url', ''),
        'match': match, 'review_flags': warnings,
        'field_provenance': evidence.get('field_provenance', {}),
        'lookup_events': evidence.get('lookup_events', []),
        'identifiers': {'doi': evidence.get('doi'), 'pmid': evidence.get('pmid')},
    }


def _review_rows(rows, proposals, warnings):
    queue = []
    by_key = {(r['tool'], r['question'], r['order']): r for r in proposals}
    for item in rows:
        key = (item['tool'], item['question'], item['order'])
        p = by_key.get(key, {})
        reasons = []
        if item['url'] == 'NR':
            reasons.append('No original source URL')
        if item.get('extraction_confidence') in ('low', 'review'):
            reasons.append('Low-confidence PDF extraction')
        if p.get('error'):
            reasons.append('Research exception: '+str(p['error'])[:100])
        if p and not p.get('has_metadata'):
            reasons.append('Publication metadata not retrieved')
        if p.get('review_flags'):
            reasons.extend(p['review_flags'][:5])
        if reasons:
            queue.append({'tool': key[0], 'question': key[1], 'citation_order': key[2],
                          'source_file': item.get('source_file', ''), 'pdf_page': item.get('source_page', ''),
                          'original_citation': item.get('citation', ''), 'original_url': item.get('url', ''),
                          'priority': 'High' if item['url'] == 'NR' or p.get('error') else 'Review',
                          'reason': '; '.join(reasons)})
    for warning in warnings:
        if any(term in warning.get('warning', '').lower() for term in ('collapsed', 'unknown', 'failed', 'zero')):
            queue.append({'tool': warning.get('tool', ''), 'question': warning.get('question', ''),
                          'citation_order': warning.get('order', ''), 'source_file': warning.get('file', ''),
                          'pdf_page': '', 'original_citation': '', 'original_url': '',
                          'priority': 'High', 'reason': warning.get('warning', '')})
    return queue


SOURCE_QUALITY_FIELDS = [
    'tool','question','citation_order','source_file','pdf_page',
    'original_citation','original_url','source_identity',
    'occurrences_of_source_in_question','short_or_generic_label',
    'extraction_confidence','repeat_occurrence','review_priority','review_reason',
]


def _source_quality_review(rows):
    """Audit citation *occurrences* separately from unique source identities."""
    identity_counts = Counter(
        (item['tool'], item['question'], citation_identity(item)) for item in rows)
    output = []
    for item in rows:
        ident = citation_identity(item)
        num = identity_counts[(item['tool'], item['question'], ident)]
        weak = weak_visible_citation_label(item.get('citation', ''), item.get('url', ''))
        notes = []
        if weak:
            notes.append('Short/domain-only linked label is not a full bibliographic citation')
        if num > 1:
            notes.append(f'{num} occurrences of the same source identity; verify citation occurrence count')
        if item.get('extraction_confidence') in ('review','low'):
            notes.append('PDF extraction needs human review')
        if item.get('url') in ('','NR',None):
            notes.append('Original PDF lacks a recoverable linked URL')
        output.append({
            'tool': item['tool'], 'question': item['question'],
            'citation_order': item['order'], 'source_file': item.get('source_file',''),
            'pdf_page': item.get('source_page',''), 'original_citation': item['citation'],
            'original_url': item.get('url',''), 'source_identity': ident,
            'occurrences_of_source_in_question': num,
            'short_or_generic_label': 'Y' if weak else 'N',
            'extraction_confidence': item.get('extraction_confidence',''),
            'repeat_occurrence': item.get('repeat',''),
            'review_priority': ('High' if weak and num>=3 else 'Review' if notes else 'Low'),
            'review_reason': '; '.join(notes),
        })
    return output


GEOGRAPHY_REVIEW_FIELDS = [
    'tool', 'question', 'citation_order', 'excel_row', 'original_citation',
    'original_url', 'research_status', 'publication_title', 'source_type',
    'first_author', 'first_author_affiliation', 'first_author_country',
    'first_author_who_region', 'first_author_income',
    'first_country_evidence_source', 'first_country_evidence_url',
    'first_country_evidence_reason', 'last_author', 'last_author_country',
    'last_country_evidence_source', 'review_priority', 'review_action',
    'source_review_flags',
]


def _geography_review(rows, proposals, workbook):
    """One provenance-linked review decision per original citation.

    This audit does not invent an author, infer country from an institution
    name, or treat OpenAlex's publication-specific country as final verified
    author geography. Review decisions stay outside the original workbook.
    """
    indexed = {(p['tool'], p['question'], int(p['order'])): p for p in proposals}
    output = []
    for citation in rows:
        key = (citation['tool'], citation['question'], int(citation['order']))
        rownum = workbook.existing.get(key)
        if rownum is None:
            continue
        data = workbook.get_row(rownum)
        proposal = indexed.get(key, {})
        provenance = proposal.get('field_provenance') or {}
        first = provenance.get('AN') or {}
        last = provenance.get('AS') or {}
        country = data.get('AN') or 'NR'
        author = data.get('AL') or 'NR'
        source_type = data.get('AD') or 'NR'
        has_country = country not in ('', 'NR', 'NOT FOUND', None)
        if not has_country and author in ('NR', 'NOT FOUND', '') and source_type in (
                'Professional society or organization webpage',
                'Point-of-care resource topic (e.g. UpToDate, DynaMed, StatPearls)'):
            priority = 'Applicability review'
            action = 'Determine whether a named first author and author geography apply to this source'
        elif not has_country:
            priority = 'High - primary outcome missing'
            action = 'Locate the actual first-author affiliation, confirm country and WHO region'
        elif 'OpenAlex' in first.get('source', ''):
            priority = 'High - verify OpenAlex inference'
            action = 'Verify this author-specific country against the publication, not institution order'
        elif first.get('source'):
            priority = 'Review - verify source evidence'
            action = 'Confirm source affiliation and WHO-region coding against the original publication'
        else:
            priority = 'High - provenance missing'
            action = 'Confirm first-author country and obtain supporting evidence before accepting it'
        output.append({
            'tool': key[0], 'question': key[1], 'citation_order': key[2],
            'excel_row': rownum,
            'original_citation': citation.get('citation', ''),
            'original_url': citation.get('url', ''),
            'research_status': ('written_provisional' if proposal.get('written_to_workbook')
                                else 'not_written' if proposal else 'not_researched'),
            'publication_title': data.get('Z', ''),
            'source_type': source_type,
            'first_author': author,
            'first_author_affiliation': data.get('AM', ''),
            'first_author_country': country,
            'first_author_who_region': data.get('AO', ''),
            'first_author_income': data.get('AP', ''),
            'first_country_evidence_source': first.get('source', ''),
            'first_country_evidence_url': first.get('url', ''),
            'first_country_evidence_reason': first.get('reason', ''),
            'last_author': data.get('AQ', ''),
            'last_author_country': data.get('AS', ''),
            'last_country_evidence_source': last.get('source', ''),
            'review_priority': priority,
            'review_action': action,
            'source_review_flags': '; '.join(str(f) for f in proposal.get('review_flags', [])),
        })
    return output


RESEARCH_AUDIT_FIELDS = [
    'tool','question','order','excel_row','original_citation','original_url',
    'research_status','publication_title','research_doi','research_pmid',
    'informative_green_fields','metadata_sources','review_reasons',
]


def _research_audit(rows, proposals):
    """One traceable status per citation, including those skipped by the cap.

    This is a reviewer-facing index, NOT a replacement for field-level
    provenance in research_proposals.json or a human verification decision.
    """
    proposals_by_key = {(p['tool'], p['question'], int(p['order'])): p for p in proposals}
    result = []
    for citation in rows:
        key = (citation['tool'], citation['question'], int(citation['order']))
        proposed = proposals_by_key.get(key)
        status = 'not_researched'
        if proposed:
            if proposed.get('error'):
                status = 'lookup_error'
            elif not proposed.get('has_metadata'):
                status = 'metadata_unavailable'
            elif not proposed.get('can_autowrite', False):
                flags = proposed.get('review_flags') or []
                identity_problem = any('conflicts with' in msg or 'differs materially' in msg
                                       for msg in flags)
                status = ('identity_conflict_or_ambiguous_source' if identity_problem
                          else 'metadata_without_informative_fields')
            elif proposed.get('written_to_workbook'):
                status = 'written_provisional_or_reviewer_gated'
            else:
                status = 'proposed_only_human_verification_required'
        fields = proposed.get('fields') or {} if proposed else {}
        meaningful = sum(v not in (None, '', 'NR', 'NOT FOUND', 'Not applicable')
                         for v in fields.values()) if proposed and proposed.get('has_metadata') else 0
        sources = sorted({v.get('source', '') for v in (proposed.get('field_provenance') or {}).values()
                          if isinstance(v, dict) and v.get('source')}) if proposed else []
        reasons = proposed.get('review_flags') or [] if proposed else []
        if proposed and proposed.get('error'):
            reasons = list(reasons) + [str(proposed['error'])[:250]]
        result.append({
            'tool':key[0], 'question':key[1], 'order':key[2],
            'excel_row': citation.get('excel_row') or (proposed or {}).get('row',''),
            'original_citation':citation.get('citation',''),
            'original_url':citation.get('url',''),
            'research_status':status,
            'publication_title':fields.get('Z',''),
            'research_doi':(proposed or {}).get('identifiers',{}).get('doi',''),
            'research_pmid':(proposed or {}).get('identifiers',{}).get('pmid',''),
            'informative_green_fields':meaningful,
            'metadata_sources':'; '.join(sources),
            'review_reasons':'; '.join(str(x) for x in reasons[:12]),
        })
    return result


def _original_rows(workbook):
    result = []
    for (tool, question, order), excel_row in sorted(workbook.existing.items()):
        d = workbook.get_row(excel_row)
        is_verified = d.get('X') not in ('', 'NR', 'NOT FOUND')
        preferred = d.get('X') if is_verified else d.get('E')
        result.append({'tool': tool, 'question': question, 'order': order,
                       'citation': d.get('D', ''), 'url': preferred or 'NR',
                       'source_url_verified': is_verified,
                       'title': d.get('F', ''), 'authors': d.get('G', ''),
                       'year': d.get('H', ''), 'journal': d.get('I', ''),
                       'doi': d.get('J', ''), 'pmid': d.get('K', ''),
                       'source_file': 'reviewed workbook', 'source_page': 0,
                       'excel_row': excel_row, 'extraction_method': 'previous_workbook',
                       'extraction_confidence': 'reviewed'})
    return result


def research_candidate(item, wb):
    """Resolve a source for research, including reviewer-verified column X.

    A citation with no original URL/DOI and a short title must still be
    researchable if a human reviewer provides a verified link in column X.
    The as-cited blue fields remain immutable.
    """
    key = (item['tool'], item['question'], int(item['order']))
    rownum = wb.existing.get(key)
    if rownum is None:
        return None, item, False
    reviewed = wb.get_row(rownum).get('X', '')
    if reviewed not in ('', 'NR', 'NOT FOUND', None):
        source = {**item, 'url': reviewed, 'source_url_verified': True}
    else:
        source = item
    has_identifier = any(source.get(k) not in ('', 'NR', 'NOT FOUND', None)
                         for k in ('url', 'doi', 'pmid'))
    title = str(source.get('title') or '')
    searchable_title = (len(re.findall(r'[A-Za-z]{3,}', title)) >= 7
                        and 25 <= len(title) <= 240)
    return rownum, source, (has_identifier or searchable_title)


def main(argv=None):
    ap = argparse.ArgumentParser(description='AI citation evidence pipeline: original PDFs to research workbook')
    ap.add_argument('command', choices=['scan', 'run'])
    ap.add_argument('--input', default=str(ROOT/'inputs'), help='PDF folder, including CODE/ subfolders for mixed models')
    ap.add_argument('--template', default=str(ROOT/'template'/'AI_Citation_Bias_Extraction_Workbook.xlsx'))
    ap.add_argument('--output', default=str(ROOT/'outputs'/'citation_extraction_filled.xlsx'))
    ap.add_argument('--report-dir', default=str(ROOT/'outputs'))
    ap.add_argument('--tool', help='Default tool code for unlabelled files; omit to auto-detect from filename/folder')
    ap.add_argument('--stage', choices=['blue', 'research', 'all'], default='all')
    ap.add_argument('--green-policy', choices=['verified-only', 'provisional'], default='verified-only')
    ap.add_argument('--no-ai', action='store_true')
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--max-sources', type=int, default=0)
    ap.add_argument('--max-docs', type=int, default=0)
    ap.add_argument('--contact-email', default=os.getenv('RESEARCH_CONTACT_EMAIL', ''))
    ap.add_argument('--journal-evidence', help='Optional investigator-verified SCImago and licensed 2026 JCR CSV')
    args = ap.parse_args(argv)
    if args.max_sources < 0 or args.max_docs < 0:
        ap.error('max-sources/max-docs must be nonnegative')
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    wb = TemplateWorkbook(args.template)
    ai = choose_ai(args)
    if args.command == 'scan' or args.stage in ('blue', 'all'):
        rows, documents, warnings = gather(args, wb, ai)
    else:
        # Research-only resumes from an edited/reviewed workbook, with no PDFs.
        rows, documents, warnings = _original_rows(wb), [], []
    write_json(report_dir/'citations_extracted.json', rows)
    write_csv(report_dir/'citation_preview.csv', rows,
        ['tool','question','order','citation','url','title','authors','year','journal','doi','pmid','repeat',
         'source_file','source_page','extraction_method','extraction_confidence','pdf_sha256'])
    source_review = _source_quality_review(rows)
    write_csv(report_dir/'source_quality_review.csv', source_review, SOURCE_QUALITY_FIELDS)
    if args.command == 'scan':
        write_json(report_dir/'scan_report.json', {'documents': documents, 'citations': len(rows), 'warnings': warnings})
        queue = _review_rows(rows, [], warnings)
        write_csv(report_dir/'review_queue.csv', queue,
            ['tool','question','citation_order','source_file','pdf_page','original_citation','original_url','priority','reason'])
        print(f'[SCAN COMPLETE] {len(rows)} candidate citations; see {report_dir/"citation_preview.csv"}')
        return 0
    if args.stage in ('blue', 'all'):
        for item in rows:
            try:
                item['excel_row'] = wb.upsert_blue(item)
            except Exception as exc:
                warnings.append({'file': item['source_file'], 'warning': f'Workbook row failure: {exc}'})
        by_question = defaultdict(list)
        for doc in documents:
            if doc['question']:
                by_question[(doc['tool'], doc['question'])].append(doc)
        for (tool, question), docs in by_question.items():
            source_rows = [x for x in rows if x['tool'] == tool and x['question'] == question]
            if source_rows:
                wb.update_query_log(tool, question, len(source_rows),
                    [x['file'] for x in docs], incomplete=any(x['with_urls'] == 0 for x in docs))
            else:
                wb.update_query_log(tool, question, 0, [x['file'] for x in docs], incomplete=True)
                warnings.append({'tool': tool, 'question': question,
                                 'warning': 'Zero citations extracted; manually confirm the conversation'})
    research = []
    researchable_count = 0
    if args.stage in ('research', 'all'):
        bibliography = Bibliography(wb.data.countries, ROOT/'cache', args.contact_email,
                                   offline=args.offline)
        journal_database = load_journal_evidence(args.journal_evidence, wb.data.countries)
        # Compute eligibility *after* considering column X, so reports can
        # distinguish skipped citations from those left out by the research cap.
        researchable_count = sum(research_candidate(item, wb)[2] for item in rows)
        attempts = 0
        for item in rows:
            if args.max_sources and attempts >= args.max_sources:
                break
            key = (item['tool'], item['question'], int(item['order']))
            rownum, lookup_item, eligible = research_candidate(item, wb)
            if rownum is None:
                continue
            if not eligible:
                warnings.append({'tool': key[0], 'question': key[1], 'order': key[2],
                                 'warning': 'No source identifier and insufficient title; research skipped'})
                continue
            attempts += 1
            record = {'tool': key[0], 'question': key[1], 'order': key[2], 'row': rownum}
            try:
                info = enrich(lookup_item, wb, bibliography, ai, journal_database)
                record.update(info)
                written = bool(info['can_autowrite'] and wb.upsert_green(rownum,
                    [info['fields'][k] for k in GREEN_COLS], args.green_policy))
                record['written_to_workbook'] = written
                if not info['has_metadata']:
                    warnings.append({'tool': key[0], 'question': key[1], 'order': key[2],
                                     'warning': 'No publication metadata retrieved; manual verification required'})
                if info['has_metadata'] and not info['can_autowrite']:
                    identity_problem = any('conflicts with' in msg or 'differs materially' in msg
                                           for msg in info.get('review_flags', []))
                    warnings.append({'tool': key[0], 'question': key[1], 'order': key[2],
                                     'warning': ('Publication identity mismatch; green fields withheld pending review'
                                                 if identity_problem else
                                                 'Metadata retrieved without informative fields; no green data written')})
                print(f'[SOURCE] {key[0]}/{key[1]} #{key[2]} '
                      f'{"written" if written else "proposal only"} metadata={info["has_metadata"]}')
            except Exception as exc:
                record['error'] = f'{type(exc).__name__}: {str(exc)[:250]}'
                record['written_to_workbook'] = False
                warnings.append({'tool': key[0], 'question': key[1], 'order': key[2],
                                 'warning': 'Research exception: '+record['error']})
            research.append(record)
            # Crash-recovery checkpoint: proposals are *not* accepted/verified by this.
            write_json(report_dir/'research_proposals.json', research)
    if not research:
        # Avoid leaving a previous run's unrelated proposals in reused folders.
        write_json(report_dir/'research_proposals.json', [])
    output = wb.save(args.output)
    audit = _research_audit(rows, research)
    write_csv(report_dir/'research_audit.csv', audit, RESEARCH_AUDIT_FIELDS)
    geography = _geography_review(rows, research, wb)
    write_csv(report_dir/'geography_review.csv', geography, GEOGRAPHY_REVIEW_FIELDS)
    queue = _review_rows(rows, research, warnings)
    write_csv(report_dir/'review_queue.csv', queue,
        ['tool','question','citation_order','source_file','pdf_page','original_citation','original_url','priority','reason'])
    tool_coverage = defaultdict(set)
    for item in rows:
        tool_coverage[item['tool']].add(item['question'])
    # Include unresolved documents in coverage. Their question is still
    # observed/inferred, but cannot be treated as completed extraction.
    for doc in documents:
        if doc.get('question'):
            tool_coverage[doc['tool']].add(doc['question'])
    # Report actual substantive values saved, not mere NR/NOT FOUND placeholders.
    informative_output_cells = sum(
        wb.get_row(rownum).get(col) not in ('', 'NR', 'NOT FOUND', 'Not applicable', None)
        for rownum in wb.existing.values() for col in GREEN_COLS
    )
    report = {
        'version': APP_VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'input_documents': documents, 'citations_extracted': len(rows),
        'documents_with_no_citations': sum(doc.get('citations') == 0 for doc in documents),
        'documents_with_unresolved_question': sum(not doc.get('question') for doc in documents),
        'documents_suspected_image_only': sum(
            bool((doc.get('pdf_diagnostics') or {}).get('possible_image_only_export'))
            for doc in documents),
        'citations_with_urls': sum(item['url'] not in ('', 'NR') for item in rows),
        'distinct_sources_within_questions': len({
            (item['tool'],item['question'],citation_identity(item)) for item in rows}),
        'repeated_source_occurrences': sum(item.get('repeat') == 'Y' for item in rows),
        'short_or_generic_source_labels': sum(
            item['short_or_generic_label'] == 'Y' for item in source_review),
        'high_priority_source_quality_rows': sum(
            item['review_priority'] == 'High' for item in source_review),
        'sources_researched': len(research),  # candidates evaluated; may run fully offline
        'eligible_sources_for_research': researchable_count,
        'publication_lookup_limit': args.max_sources,  # 0 = all
        'eligible_sources_not_researched': max(0, researchable_count - len(research)),
        'research_truncated_by_limit': bool(args.max_sources and
                                            researchable_count > len(research)),
        'external_lookup_successes': sum(
            sum(event.get('status') == 'ok' for event in item.get('lookup_events', []))
            for item in research),  # fresh network responses; backward compatible
        'cached_lookup_reuses': sum(
            sum(event.get('status') == 'cache_hit' for event in item.get('lookup_events', []))
            for item in research),
        'sources_with_metadata': sum(bool(item.get('has_metadata')) for item in research),
        'rows_written_green': sum(bool(item.get('written_to_workbook')) for item in research),
        'informative_green_cells_in_output_workbook': informative_output_cells,
        'geography_review_rows': len(geography),
        'geography_review_high_priority': sum(
            item['review_priority'].startswith('High') for item in geography),
        'first_author_country_rows': sum(
            wb.get_row(rownum).get('AN') not in ('', 'NR', 'NOT FOUND', None)
            for rownum in wb.existing.values()),
        'last_author_country_rows': sum(
            wb.get_row(rownum).get('AS') not in ('', 'NR', 'NOT FOUND', None)
            for rownum in wb.existing.values()),
        'review_queue_items': len(queue),
        'sources_with_identity_conflicts': sum(x['research_status'] == 'identity_conflict_or_ambiguous_source' for x in audit),
        'informative_green_cells_proposed': sum(x['informative_green_fields'] for x in audit),
        'green_cells_policy': args.green_policy, 'stages': args.stage,
        'investigator_journal_evidence_used': bool(args.journal_evidence),
        'ai_used': bool(ai), 'offline': args.offline,
        'tools_detected': {k: sorted(v) for k,v in tool_coverage.items()},
        'warning_count': len(warnings)+len(wb.warnings),
        'warnings': warnings+[{'warning': x} for x in wb.warnings],
        'output_workbook': str(output),
        'metadata_provenance_file': str(report_dir/'research_proposals.json') if research else None,
    }
    write_json(report_dir/'run_report.json', report)
    print(f'\n[SAVED] {output}\n[REPORT] {report_dir/"run_report.json"}\n'
          f'[SUMMARY] {len(rows)} citation candidates, {len(research)} source lookups, '
          f'{report["rows_written_green"]} green rows, {len(queue)} review items')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('[ERROR]', type(exc).__name__, str(exc), file=sys.stderr)
        sys.exit(1)
