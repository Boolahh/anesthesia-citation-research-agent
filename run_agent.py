#!/usr/bin/env python3
"""Reproducible AI citation audit: PDFs -> as-cited columns -> sourced proposals.

All research assignments remain provisional pending human source verification. No
credentials or original chat PDFs are written to GitHub. Designed for mixed
platforms, resumable batch research, and auditable study data.
"""
from __future__ import annotations

from collections import defaultdict
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
from agent.pdf_extract import parse_pdf
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
            documents.append({'file': path.name, 'tool': tool, 'question': None, 'citations': 0,
                              'with_urls': 0, 'pdf_sha256': digest, 'warnings': issues})
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
            identity = citation['doi'] if citation['doi'] != 'NR' else citation['pmid'] if citation['pmid'] != 'NR' else citation['url'] if citation['url'] != 'NR' else citation['citation']
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
                warnings.append({'tool': tool, 'question': question,
                                 'warning': 'Zero citations extracted; manually confirm the conversation'})
    research = []
    if args.stage in ('research', 'all'):
        bibliography = Bibliography(wb.data.countries, ROOT/'cache', args.contact_email,
                                   offline=args.offline)
        journal_database = load_journal_evidence(args.journal_evidence, wb.data.countries)
        attempts = 0
        for item in rows:
            if args.max_sources and attempts >= args.max_sources:
                break
            key = (item['tool'], item['question'], int(item['order']))
            rownum = wb.existing.get(key)
            if rownum is None:
                continue
            has_identifier = any(item.get(k) not in ('', 'NR', None) for k in ('url','doi','pmid'))
            # Permit a constrained title lookup if there is no URL/ID. Original blue
            # fields remain unchanged, and results require human confirmation.
            title = item.get('title', '')
            title_candidate = len(re.findall(r'[A-Za-z]{3,}', title)) >= 7 and 25 <= len(title) <= 240
            if not has_identifier and not title_candidate:
                warnings.append({'tool': key[0], 'question': key[1], 'order': key[2],
                                 'warning': 'No source identifier and insufficient title; research skipped'})
                continue
            attempts += 1
            record = {'tool': key[0], 'question': key[1], 'order': key[2], 'row': rownum}
            # A previously reviewed workbook can also be used in combined mode.
            # Research from its human verified X link; do not mutate blue E/J.
            reviewed = wb.get_row(rownum).get('X', '')
            lookup_item = ({**item, 'url': reviewed, 'source_url_verified': True}
                           if reviewed not in ('', 'NR', 'NOT FOUND') else item)
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
    queue = _review_rows(rows, research, warnings)
    write_csv(report_dir/'review_queue.csv', queue,
        ['tool','question','citation_order','source_file','pdf_page','original_citation','original_url','priority','reason'])
    tool_coverage = defaultdict(set)
    for item in rows:
        tool_coverage[item['tool']].add(item['question'])
    # Report actual substantive values saved, not mere NR/NOT FOUND placeholders.
    informative_output_cells = sum(
        wb.get_row(rownum).get(col) not in ('', 'NR', 'NOT FOUND', 'Not applicable', None)
        for rownum in wb.existing.values() for col in GREEN_COLS
    )
    report = {
        'version': APP_VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'input_documents': documents, 'citations_extracted': len(rows),
        'citations_with_urls': sum(item['url'] not in ('', 'NR') for item in rows),
        'sources_researched': len(research),  # candidates evaluated; may run fully offline
        'external_lookup_successes': sum(
            sum(event.get('status') == 'ok' for event in item.get('lookup_events', []))
            for item in research),
        'sources_with_metadata': sum(bool(item.get('has_metadata')) for item in research),
        'rows_written_green': sum(bool(item.get('written_to_workbook')) for item in research),
        'informative_green_cells_in_output_workbook': informative_output_cells,
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
