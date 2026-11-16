"""Regression tests for Copilot's on-screen viewport PDFs.

Real study pilot: 13 single-page Copilot prints, 18 clickable Copilot UI
navigation URLs per PDF and unlinked 7.5pt source badges in the answer.
Do not commit the original clinical PDF corpus or inventoried source URLs.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import fitz

from agent.copilot_export import is_sidebar_link, is_viewport_print, visible_unlinked_badges
from agent.pdf_extract import parse_pdf
from agent.workbook import TemplateWorkbook
from run_agent import reject_contaminated_copilot_workbook, require_single_pdf_per_question

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'template' / 'AI_Citation_Bias_Extraction_Workbook.xlsx'


def synthetic_copilot_viewport(path, badge_labels=(), real_url=''):
    """Make a PDF with browser/sidebar links and no invented source URLs."""
    with fitz.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_text((105, 90), 'PONV prevention and treatment', fontsize=12)
        page.insert_text((310, 758), 'Copilot is an AI and may make mistakes', fontsize=8)
        page.insert_text((110, 745), 'Message Copilot', fontsize=11)
        for idx, (label, y) in enumerate(badge_labels):
            x = 250
            page.insert_text((x,y), label, fontsize=7.5, color=(.365,.365,.365))
            if idx == 0 and real_url:
                page.insert_link({
                    'kind':fitz.LINK_URI,
                    'from':fitz.Rect(x,y-9,x+66,y+2),
                    'uri':real_url,
                })
        for i, url in enumerate([
                'https://copilot.com/chat?fromcode=test',
                'https://copilot.com/search?fromcode=test',
                'https://copilot.com/library/all',
                'https://copilot.com/projects',
                'https://copilot.com/chat/all',
                'https://copilot.com/chat/conversation/abc-def-123?fromcode=test',
            ]):
            page.insert_link({'kind':fitz.LINK_URI,
                              'from':fitz.Rect(35,130+i*27,59,154+i*27),
                              'uri':url})
        pdf.save(path)


class CopilotNavigationTests(TestCase):
    def test_only_known_sidebar_urls_are_excluded(self):
        self.assertTrue(is_sidebar_link('https://copilot.com/chat?fromcode=test'))
        self.assertTrue(is_sidebar_link('https://copilot.com/chat/conversation/a'))
        self.assertTrue(is_sidebar_link('https://copilot.com/library/all'))
        self.assertTrue(is_sidebar_link('https://copilot.microsoft.com/projects'))
        self.assertFalse(is_sidebar_link('https://pubmed.ncbi.nlm.nih.gov/12345678/'))
        self.assertFalse(is_sidebar_link('https://doi.org/10.1000/example'))
        self.assertFalse(is_sidebar_link('https://copilot.com/medical-paper-unknown'))

    def test_visible_badges_preserved_literally_without_urls(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / 'Q01_Copilot.pdf'
            synthetic_copilot_viewport(p, [
                ('lww +1', 251), ('anesthesiaexperts', 380),
                ('lww +1', 500), ('bjaed', 640),
            ])
            with fitz.open(p) as doc:
                self.assertTrue(is_viewport_print(list(doc)))
                self.assertEqual(len(doc[0].get_links()), 6)
            rows, warnings = parse_pdf(p, 'COP', {'Q01':'PONV prevention'})
        self.assertEqual(len(rows), 4)
        self.assertEqual([r['citation'] for r in rows],
                         ['lww +1', 'anesthesiaexperts', 'lww +1', 'bjaed'])
        self.assertTrue(all(r['url'] == 'NR' for r in rows))
        self.assertTrue(all(r['title'] == 'NR' for r in rows))
        self.assertTrue(all(r['authors'] == 'NR' for r in rows))
        self.assertTrue(all(r['extraction_confidence'] == 'review' for r in rows))
        self.assertTrue(all(r['source_context'] == 'inline_badge_unlinked' for r in rows))
        self.assertTrue(any('excluded 6 sidebar' in warning for warning in warnings))
        self.assertTrue(any('Collapsed Copilot +N' in warning for warning in warnings))
        self.assertTrue(any('viewport' in warning for warning in warnings))

    def test_all_navigation_no_badges_means_zero_citations(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'Q02_Copilot.pdf'
            synthetic_copilot_viewport(p)
            rows,warnings=parse_pdf(p,'COP', {'Q02':'Hypotension'})
        self.assertEqual(rows,[])
        self.assertTrue(any('No explicit citations recoverable' in w for w in warnings))

    def test_real_citation_link_survives_without_creating_unlinked_duplicate(self):
        true_url='https://pubmed.ncbi.nlm.nih.gov/12345678/'
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'Q03_Copilot.pdf'
            synthetic_copilot_viewport(p,[('pubmed', 270),('asra +1', 390)],
                                       real_url=true_url)
            rows,warnings=parse_pdf(p,'COP',{'Q03':'Hemorrhage management'})
        self.assertEqual(len(rows),2)
        self.assertEqual(sorted(r['url'] for r in rows),['NR',true_url])
        self.assertEqual(
            next(r for r in rows if r['url'] == 'NR')['citation'],
            'asra +1',
        )

    def test_one_row_source_badge_never_invents_plus_one_hidden_citation(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'Q04_Copilot.pdf'
            synthetic_copilot_viewport(p,[('nih +1', 270)])
            rows,_=parse_pdf(p,'COP',{'Q04':'LAST management'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['citation'],'nih +1')
        self.assertEqual(rows[0]['doi'],'NR')
        self.assertEqual(rows[0]['pmid'],'NR')
        self.assertEqual(rows[0]['url'],'NR')


class StrictInputGuardTests(TestCase):
    def test_two_different_pdfs_for_same_question_are_rejected(self):
        docs=[
            {'tool':'COP','question':'Q06','file':'Managing hypoxemia.pdf'},
            {'tool':'COP','question':'Q06','file':'Preventing hypoxemia.pdf'},
        ]
        with self.assertRaisesRegex(ValueError,'exactly ONE answer'):
            require_single_pdf_per_question(docs)

    def test_same_question_different_models_are_valid(self):
        require_single_pdf_per_question([
            {'tool':'COP','question':'Q06','file':'copilot.pdf'},
            {'tool':'CLG','question':'Q06','file':'claude.pdf'},
        ])

    def test_bad_old_master_workbook_must_not_carry_sidebar_as_source(self):
        workbook=TemplateWorkbook(TEMPLATE)
        workbook.upsert_blue({
            'tool':'COP','question':'Q01','order':1,'citation':'An',
            'url':'https://copilot.com/chat/conversation/test-history',
            'title':'NR','authors':'NR','year':'NR','journal':'NR',
            'doi':'NR','pmid':'NR','repeat':'N',
        })
        with self.assertRaisesRegex(ValueError,'NOT publication citations'):
            reject_contaminated_copilot_workbook(workbook)

    def test_clean_master_workbook_accepted(self):
        wb=TemplateWorkbook(TEMPLATE)
        wb.upsert_blue({
            'tool':'COP','question':'Q01','order':1,'citation':'lww +1',
            'url':'NR', 'title':'NR', 'authors':'NR', 'year':'NR',
            'journal':'NR', 'doi':'NR', 'pmid':'NR', 'repeat':'N',
        })
        reject_contaminated_copilot_workbook(wb)
