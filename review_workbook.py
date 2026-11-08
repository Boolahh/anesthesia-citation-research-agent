#!/usr/bin/env python3
"""Apply explicit human-authored reviewer CSV decisions; never infer verdicts."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import json
import hashlib

from agent.workbook import TemplateWorkbook
from agent.reviewer import apply_decisions, decision_template, write_review_csv, load_review_csv


def main(argv=None):
    p=argparse.ArgumentParser(description='Export reviewer form or apply human decisions to the study workbook')
    p.add_argument('--workbook',required=True)
    p.add_argument('--decisions',help='CSV manually completed by a human reviewer')
    p.add_argument('--export-review-template',help='Write a reviewer CSV with blank verdicts')
    p.add_argument('--output',help='Result workbook path (required when applying decisions)')
    p.add_argument('--allow-review-overwrite',action='store_true')
    args=p.parse_args(argv)
    wb=TemplateWorkbook(args.workbook)
    if args.export_review_template:
        write_review_csv(args.export_review_template, decision_template(wb))
        print('[REVIEW TEMPLATE]',args.export_review_template)
        if not args.decisions:return 0
    if not args.decisions or not args.output:
        p.error('Pass both --decisions and --output, or only --export-review-template')
    if Path(args.output).resolve()==Path(args.workbook).resolve():
        p.error('Output workbook must differ from source workbook')
    changes=apply_decisions(wb,load_review_csv(args.decisions),allow_overwrite=args.allow_review_overwrite)
    wb.save(args.output)
    audit={'date_utc':datetime.now(timezone.utc).isoformat(), 'source_workbook_sha256':hashlib.sha256(Path(args.workbook).read_bytes()).hexdigest(),
           'review_csv_sha256':hashlib.sha256(Path(args.decisions).read_bytes()).hexdigest(),
           'changes':changes, 'human_supplied':True}
    audit_file=Path(args.output).with_suffix('.review_audit.json')
    audit_file.write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print('[REVIEWED]',args.output,'[CHANGES]',len(changes),'[AUDIT]',audit_file)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
