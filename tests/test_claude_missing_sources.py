"""Claude zero-source PDF diagnostics; synthetic local samples only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import fitz

from agent.pdf_extract import inspect_unresolved_pdf, heuristic_question, parse_pdf
from agent.workbook import TemplateWorkbook
from run_agent import gather
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class ClaudeNoSourceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = TemplateWorkbook(ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx')

    def test_all_twelve_claude_filenames_have_unique_question_hint(self):
        examples = {
            'Postoperative nausea prevention strategies - Claude.pdf': 'Q01',
            'Intraoperative hypotension management - Claude.pdf': 'Q02',
            'Intraoperative hemorrhage management - Claude.pdf': 'Q03',
            'Local anesthetic systemic toxicity - Claude.pdf': 'Q04',
            'Anticipated difficult airway management - Claude.pdf': 'Q05',
            'Hypoxemia during one-lung ventilation - Claude.pdf': 'Q06',
            'Anesthesia for cesarean delivery - Claude.pdf': 'Q07',
            'Kidney injury risk in hip arthroplasty - Claude.pdf': 'Q08',
            'Postoperative delirium prevention in elderly - Claude.pdf': 'Q09',
            'Pediatric anesthesia with recent URTI - Claude.pdf': 'Q10',
            'Volatile vs TIVA in CABG - Claude.pdf': 'Q11',
            'Anesthesia management for raised ICP - Claude.pdf': 'Q12',
        }
        for filename, question in examples.items():
            with self.subTest(filename=filename):
                self.assertEqual(heuristic_question(Path(filename).stem, []), question)

    def test_no_sources_still_reports_question_and_text_diagnostics(self):
        with TemporaryDirectory() as d:
            folder = Path(d)
            path = folder/'Anesthesia management for raised ICP - Claude.pdf'
            with fitz.open() as pdf:
                page = pdf.new_page()
                page.insert_text((40,70), 'No references or linked publications provided.')
                pdf.save(path)
            args = SimpleNamespace(input=str(folder), tool='CLG', max_docs=0)
            citations, docs, warnings = gather(args, self.book, None)
            self.assertEqual(citations, [])
            self.assertEqual(len(docs),1)
            self.assertEqual(docs[0]['question'],'Q12')
            self.assertEqual(docs[0]['citations'],0)
            self.assertGreater(docs[0]['pdf_diagnostics']['selectable_text_characters'],0)
            self.assertEqual(docs[0]['pdf_diagnostics']['uri_link_annotations'],0)
            self.assertTrue(any('Zero recoverable' in w['warning'] for w in warnings))

    def test_blank_pdf_not_invented_citations_or_details(self):
        with TemporaryDirectory() as d:
            path = Path(d)/'Kidney injury risk in hip arthroplasty - Claude.pdf'
            with fitz.open() as pdf:
                pdf.new_page()
                pdf.save(path)
            info=inspect_unresolved_pdf(path)
            self.assertEqual(info['question_inferred_from_filename'],'Q08')
            self.assertEqual(info['selectable_text_characters'],0)
            rows,warnings=parse_pdf(path,'CLG',self.book.data.questions)
            self.assertEqual(rows,[])
            self.assertTrue(any('No explicit citations recoverable' in w for w in warnings))

    def test_image_only_pdf_triggers_diagnostics_without_claiming_sources(self):
        with TemporaryDirectory() as d:
            path=Path(d)/'Anesthesia for cesarean delivery - Claude.pdf'
            with fitz.open() as pdf:
                page=pdf.new_page()
                pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,30,30),False)
                page.insert_image(fitz.Rect(30,30,180,180),pixmap=pix)
                pdf.save(path)
            info=inspect_unresolved_pdf(path)
            self.assertEqual(info['question_inferred_from_filename'],'Q07')
            self.assertTrue(info['possible_image_only_export'])
            self.assertEqual(info['uri_link_annotations'],0)
