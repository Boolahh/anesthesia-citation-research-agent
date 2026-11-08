#!/usr/bin/env python3
"""Citation Bias Extraction Agent -- offline PDF extraction + optional AI/web enrichment.

Examples:
  python run_agent.py scan --no-ai
  python run_agent.py run --stage blue --no-ai
  python run_agent.py run --stage all --max-sources 10
  python run_agent.py run --stage research --green-policy verified-only --template outputs/research_blue.xlsx
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
import csv
import hashlib
import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent/'.env')
except ImportError:pass

from agent.workbook import TemplateWorkbook, GREEN_COLS
from agent.pdf_extract import parse_pdf
from agent.research import Bibliography, quality, norm_title

ROOT=Path(__file__).resolve().parent


def file_tool(path, known, default=None):
    for part in (path.parent.name, path.stem[:3]):
        if part.upper() in known:return part.upper()
    for code,name in known.items():
        if name.lower().replace(' ','') in path.name.lower().replace(' ',''):
            return code
    if default and default in known:return default
    return None


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str),encoding='utf-8')


def write_csv(path,rows,fields):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)


def choose_ai(args):
    if args.no_ai or args.offline:return None
    if not os.getenv('OPENAI_API_KEY'):
        print('[INFO] OPENAI_API_KEY absent; deterministic parsing and bibliographic API lookup only.')
        return None
    from agent.llm import ResearchAI
    return ResearchAI()


def gather(args,workbook,ai):
    root=Path(args.input)
    paths=sorted(p for p in root.rglob('*.pdf') if p.is_file()) if root.is_dir() else ([root] if root.suffix.lower()=='.pdf' else [])
    if args.max_docs:paths=paths[:args.max_docs]
    if not paths:raise RuntimeError(f'No PDF files found under {root}')
    collected=[];issues=[];documents=[]
    for p in paths:
        tool=file_tool(p,workbook.data.tool_names,args.tool)
        if not tool:
            issues.append({'file':str(p),'warning':'Unknown AI platform; place under inputs/TOOL_CODE/ (e.g. CGP)'})
            continue
        try: found, warnings=parse_pdf(p,tool,workbook.data.questions,api=ai)
        except Exception as exc:
            issues.append({'file':p.name,'warning':'PDF parsing failed: '+str(exc)})
            continue
        collected+=found
        per_question=defaultdict(list)
        for c in found:per_question[c['question']].append(c)
        if not per_question:
            documents.append({'file':p.name,'tool':tool,'question':None,'citations':0,'with_urls':0,
                              'warnings':warnings})
        for question,items in per_question.items():
            documents.append({'file':p.name,'tool':tool,'question':question,
                              'citations':len(items),'with_urls':sum(1 for c in items if c['url']!='NR'),
                              'warnings':warnings})
        for w in warnings:issues.append({'file':p.name,'warning':w})
        print(f'[PDF] {p.name}: {len(found)} citation(s), {sum(c["url"]!="NR" for c in found)} with URLs')
    # Renumber across multiple files for the same tool/question; require separate source PDFs
    # to preserve order if multiple documents are supplied for one response.
    grouped=defaultdict(list)
    for c in collected:grouped[(c['tool'],c['question'])].append(c)
    result=[]
    for key, rows in sorted(grouped.items()):
        seen=set()
        for i,c in enumerate(rows,1):
            c['order']=i
            identity=c['doi'] if c['doi']!='NR' else c['pmid'] if c['pmid']!='NR' else c['url'] if c['url']!='NR' else c['citation']
            c['repeat']='Y' if identity in seen else 'N'
            seen.add(identity)
            result.append(c)
    return result,documents,issues


def clean_category(value, allowed, fallback='NR'):
    if value in allowed:return value
    if value in ('NR','NOT FOUND','Not applicable','') and value:return value
    return fallback


def refine_green(green,workbook):
    # Never fill human-only columns. Limit only known categorical columns to list values.
    cat=workbook.data.categories
    for col,key in [('AD','F'),('AE','H'),('AF','N'),('AG','J'),('AI','G'),('BF','I')]:
        green[col]=clean_category(green.get(col,'NR'),cat.get(key,[]))
    country_lookup={x['name']:(x['region'],x['income']) for x in workbook.data.countries.values()}
    for c,r,i in [('AN','AO','AP'),('AS','AT','AU'),('AX','AY','AZ'),('BB','BC','BD')]:
        name=green.get(c,'')
        if name in country_lookup:
            green[r],green[i]=country_lookup[name]
        else:
            if name not in ('NR','NOT FOUND','Not applicable'):
                green[c]='NOT FOUND' # Unsupported country spelling; do not silently misclassify.
            green[r]='NOT FOUND' if green[c]=='NOT FOUND' else 'NR'
            green[i]='NOT FOUND' if green[c]=='NOT FOUND' else 'NR'
    green['BE']=''  # 2026 JCR value is inaccessible without the licensed release; never guess.
    return green


def enrich(citation,workbook,bibliography,ai):
    evidence=bibliography.metadata(citation)
    proposed=bibliography.baseline_green(evidence)
    # An external DOI or title candidate is not the human verification verdict.
    title=proposed.get('Z','')
    score=quality(title,citation.get('title'))
    has_doi=(proposed.get('AB') not in ('NR','NOT FOUND','') and 
             proposed.get('AB') == citation.get('doi'))
    method='DOI identifier present' if has_doi else 'metadata match requires review'
    if ai and (evidence.get('crossref') or evidence.get('openalex') or evidence.get('public_page') or evidence.get('europepmc')):
        source_context={
            'doi':evidence.get('doi'),'pmid':evidence.get('pmid'),
            'crossref':evidence.get('crossref'),'openalex':evidence.get('openalex'),
            'europepmc':evidence.get('europepmc'),'public_page':evidence.get('public_page')
        }
        # Only send a bounded, structured excerpt to reduce cost.
        from agent.llm import ResearchAI
        guidelines='\n'.join(workbook.data.prompts.get(n,'') for n in range(44,88))
        try:
            coded=ai.code_source(citation,source_context,
               {name:workbook.data.categories.get(col,[]) for col,name in [
                 ('F','Type of source'),('G','Author type'),('H','Study design'),
                 ('I','Open access'),('J','Funding'),('N','Subspecialty')]},guidelines)
            for col,val in zip(GREEN_COLS,coded):
                if val not in (None,'','NOT FOUND','NR'):
                    # Structured metadata takes precedence for identifiers, publication date, citation counts.
                    if col in {'Z','AA','AB','AC','AH','AJ','AK','AL','AQ','BA'} and proposed[col] not in ('NOT FOUND','NR',''):
                        continue
                    proposed[col]=val
        except Exception as exc:
            method+='; AI coding failed: '+str(exc)[:130]
    proposed=refine_green(proposed,workbook)
    has_source=bool(evidence.get('crossref') or evidence.get('openalex') or evidence.get('europepmc') or evidence.get('public_page'))
    return {'fields':proposed,'match_method':method,'title_similarity':round(score,3),
            'has_metadata':has_source,'record_url':evidence.get('source_url',''),
            'identifiers':{'doi':evidence.get('doi'),'pmid':evidence.get('pmid')},
            'sources_queried':['Crossref','OpenAlex','Europe PMC','public source URL']}


def main(argv=None):
    ap=argparse.ArgumentParser(description='Citation-bias AI agent: PDFs -> evidence -> original Excel template')
    ap.add_argument('command',choices=['scan','run'])
    ap.add_argument('--input',default=str(ROOT/'inputs'),help='Folder containing TOOL_CODE subfolders of PDF exports')
    ap.add_argument('--template',default=str(ROOT/'template'/'AI_Citation_Bias_Extraction_Workbook.xlsx'))
    ap.add_argument('--output',default=str(ROOT/'outputs'/'citation_extraction_filled.xlsx'))
    ap.add_argument('--report-dir',default=str(ROOT/'outputs'))
    ap.add_argument('--tool',default=None,help='Optional default tool code (e.g. CGP)')
    ap.add_argument('--no-ai',action='store_true',help='Disable paid AI calls; links and basic metadata still extracted')
    ap.add_argument('--offline',action='store_true',help='Do not access any network; PDF-only extraction')
    ap.add_argument('--stage',choices=['blue','research','all'],default='all')
    ap.add_argument('--green-policy',choices=['verified-only','provisional'],default='verified-only',
      help='verified-only requires U column already marked real; provisional writes AI suggestions for manual checking')
    ap.add_argument('--max-sources',type=int,default=0,help='Limit new source lookups for pilot tests (0 = all)')
    ap.add_argument('--max-docs',type=int,default=0)
    ap.add_argument('--contact-email',default=os.getenv('RESEARCH_CONTACT_EMAIL',''))
    args=ap.parse_args(argv)
    reportdir=Path(args.report_dir);reportdir.mkdir(parents=True,exist_ok=True)
    wb=TemplateWorkbook(args.template)
    ai=choose_ai(args)
    rows,docs,warnings=gather(args,wb,ai)
    write_json(reportdir/'citations_extracted.json',rows)
    write_csv(reportdir/'citation_preview.csv',rows,['tool','question','order','citation','url',
              'title','authors','year','journal','doi','pmid','repeat','source_file','source_page','extraction_method'])
    counts=defaultdict(list)
    for c in rows:counts[(c['tool'],c['question'])].append(c)
    if args.command=='scan':
        write_json(reportdir/'scan_report.json',{'documents':docs,'citations':len(rows),'warnings':warnings})
        print(f'[SCAN COMPLETE] {len(rows)} citations; see {reportdir/"citation_preview.csv"}')
        return 0
    if args.stage in ('blue','all'):
        for c in rows:
            try: c['excel_row']=wb.upsert_blue(c)
            except Exception as exc: warnings.append({'file':c['source_file'],'warning':str(exc)})
        by_doc=defaultdict(list)
        for doc in docs:
            if doc['question']:
                by_doc[(doc['tool'],doc['question'])].append(doc)
        for key, subdocs in by_doc.items():
            incomplete=any(d['with_urls']==0 for d in subdocs)
            # A blank citation list might be legitimate or a PDF export bug. Flag, don't claim no citations.
            if counts[key]:
                wb.update_query_log(key[0],key[1],len(counts[key]),[d['file'] for d in subdocs],incomplete)
            else:
                warnings.append({'tool':key[0],'question':key[1],
                                 'warning':'Zero extracted citations: confirm with original conversation before recording zero'})
    research=[]
    if args.stage in ('research','all'):
        bibliography=Bibliography(wb.data.countries,ROOT/'cache',args.contact_email,offline=args.offline)
        candidates=rows
        if args.stage=='research':
            candidates=[]
            # Re-process existing citation rows including original URLs, even without original PDFs.
            for (tool,q,order),rn in sorted(wb.existing.items()):
                d=wb.get_row(rn)
                candidates.append({'tool':tool,'question':q,'order':order,'citation':d.get('D',''),
                    'url':d.get('X') if d.get('X') not in ('','NR') else d.get('E',''),
                    'title':d.get('F',''),'authors':d.get('G',''),'year':d.get('H',''),
                    'journal':d.get('I',''),'doi':d.get('J',''),'pmid':d.get('K',''),
                    'excel_row':rn})
        seen=0
        for c in candidates:
            if args.max_sources and seen>=args.max_sources:break
            rn=wb.existing.get((c['tool'],c['question'],int(c['order'])))
            if rn is None:continue
            if c.get('url') in ('','NR') and c.get('doi') in ('','NR') and c.get('pmid') in ('','NR'):
                warnings.append({'tool':c['tool'],'question':c['question'],'order':c['order'],
                                 'warning':'No retrievable source link/DOI/PMID; research skipped'})
                continue
            seen+=1
            report={'tool':c['tool'],'question':c['question'],'order':c['order'], 'row':rn}
            try:
                info=enrich(c,wb,bibliography,ai)
                report.update(info)
                report['written_to_workbook']=bool(info['has_metadata'] and wb.upsert_green(rn,[info['fields'][k] for k in GREEN_COLS],args.green_policy))
                if not info['has_metadata']:
                    warnings.append({'tool':c['tool'],'question':c['question'],'order':c['order'],
                                     'warning':'No real-source metadata could be retrieved; verify manually'})
                print(f'[SOURCE] {c["tool"]}/{c["question"]} #{c["order"]}: '
                      f'{"coded" if report["written_to_workbook"] else "proposal only"} '
                      f'(metadata={info["has_metadata"]})')
            except Exception as exc:
                report['error']=str(exc)
                warnings.append({'tool':c['tool'],'question':c['question'],'order':c['order'],
                                 'warning':'Source research failure: '+str(exc)[:240]})
            research.append(report)
            # Restart-safe per-source checkpoint; never record an unverified hallucination verdict.
            write_json(reportdir/'research_proposals.json',research)
    outfile=wb.save(args.output)
    report={'created_utc':datetime.now(timezone.utc).isoformat(),
            'input_documents':docs,'citations_extracted':len(rows),
            'citations_with_urls':sum(c.get('url') not in ('','NR') for c in rows),
            'sources_researched':len(research),'green_cells_policy':args.green_policy,
            'stages':args.stage,'ai_used':bool(ai),'offline':args.offline,
            'warning_count':len(warnings)+len(wb.warnings),
            'warnings':warnings+[{'warning':x} for x in wb.warnings],
            'output_workbook':str(outfile)}
    write_json(reportdir/'run_report.json',report)
    print(f'\n[SAVED] {outfile}\n[REPORT] {reportdir/"run_report.json"}\n'
          f'[SUMMARY] {len(rows)} citations, {len(research)} research attempts, '
          f'{report["warning_count"]} review warnings')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print('[ERROR]',type(exc).__name__,str(exc),file=sys.stderr)
        sys.exit(1)
