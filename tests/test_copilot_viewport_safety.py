"""Copilot Edge browser-print regression: a source badge is not a sidebar URL.

No private study PDFs are committed. The synthetic PDF reproduces this export
layout: 18 clickable navigation controls, real 7.5pt *unlinked* source badges,
and a visible browser viewport disclaimer.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

import pymupdf as fitz

from agent.copilot_export import is_sidebar_link, is_viewport_print, visible_unlinked_badges
from agent.pdf_extract import parse_pdf
from agent.source_dedup import unique_question_sources
from agent.workbook import TemplateWorkbook
from run_agent import gather, reject_contaminated_copilot_workbook


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'template' / 'AI_Citation_Bias_Extraction_Workbook.xlsx'


def generate_copilot_viewport(path, *, badges=('lww +1', 'bmj', 'bmj'),
                              medical_url=None):
    with fitz.open() as document:
        page = document.new_page(width=612, height=792)
        page.insert_text((120,110),
                         'Question: What strategies reduce postoperative nausea?',
                         fontsize=13)
        page.insert_text((105,198),
                         'Prevention evidence is cited beside this statement.',
                         fontsize=12)
        for i, badge in enumerate(badges):
            ypos = 257 + i * 80
            page.insert_text((205,ypos),badge,fontsize=7.5)
            if medical_url and i == 0:
                page.insert_link({
                    'kind':fitz.LINK_URI,
                    'from':fitz.Rect(203,ypos-9,260,ypos+1),
                    'uri':medical_url,
                })
        page.insert_text((175,753),
                         'Copilot is an AI and may make mistakes.',fontsize=9)
        for index in range(18):
            y = 125 + index * 27
            page.insert_text((25,y),str(index),fontsize=11)
            url = ('https://copilot.com/projects?fromcode=abc' if index==0
                   else 'https://copilot.com/chat/conversation/'+str(index)
                   +'?fromcode=abc')
            page.insert_link({
                'kind':fitz.LINK_URI, 'from':fitz.Rect(20,y-10,56,y+3),
                'uri':url,
            })
        document.save(path)


class CopilotViewportSafetyTests(TestCase):
    def test_known_copilot_navigation_is_not_a_medical_citation(self):
        for suffix in ('/chat', '/search?query=anesthesia', '/chat/all',
                       '/library/all', '/projects?xyz=123',
                       '/chat/conversation/abcd-1234?session=1'):
            self.assertTrue(is_sidebar_link('https://copilot.com'+suffix))
        self.assertFalse(is_sidebar_link('https://pubmed.ncbi.nlm.nih.gov/12345678/'))
        self.assertFalse(is_sidebar_link('https://copilot.com/scholarly-paper.pdf'))
        self.assertFalse(is_sidebar_link('https://example.com/chat'))

    def test_18_nav_links_zero_medical_urls_three_visible_badges(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q01_Copilot.pdf'
            generate_copilot_viewport(path)
            with fitz.open(path) as pdf:
                self.assertTrue(is_viewport_print(list(pdf)))
                badges=visible_unlinked_badges(list(pdf))
            self.assertEqual([b['citation'] for b in badges],
                             ['lww +1','bmj','bmj'])
            result,warnings=parse_pdf(path,'COP',{'Q01':'Example source question'})
            self.assertEqual(len(result),3, [r['citation'] for r in result])
            self.assertEqual([r['citation'] for r in result],
                             ['lww +1','bmj','bmj'])
            self.assertTrue(all(r['url']=='NR' for r in result))
            self.assertTrue(all(r['title']=='NR' for r in result))
            self.assertTrue(all(r['doi']=='NR' and r['pmid']=='NR' for r in result))
            self.assertTrue(all(r['extraction_confidence']=='review' for r in result))
            self.assertTrue(any('excluded 18' in w for w in warnings))
            self.assertTrue(any('Collapsed Copilot' in w for w in warnings))
            self.assertTrue(any('NOT saved' in w for w in warnings))
            self.assertEqual(len(unique_question_sources(result)),3)
            # Same short badge cannot prove two distinct sources are identical.
            # Do not deduplicate two unrelated NIH papers merely by hostname.

    def test_actual_medical_link_is_not_lost_or_double_counted(self):
        url='https://pubmed.ncbi.nlm.nih.gov/12345678/'
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q01_Copilot.pdf'
            generate_copilot_viewport(path,badges=('nih','bmj'),
                                      medical_url=url)
            rows,warnings=parse_pdf(path,'COP',{'Q01':'Synthetic question'})
            linked=[r for r in rows if r['url']==url]
            self.assertEqual(len(linked),1)
            self.assertEqual(linked[0]['citation'],'nih')
            self.assertEqual(len([r for r in rows if r['url']=='NR']),1)
            self.assertFalse(any('copilot.com' in r['url'] for r in rows))

    def test_same_question_two_different_copilot_pdfs_are_refused(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)
            generate_copilot_viewport(path/'Q06_Response_A.pdf',badges=('bjaed',))
            generate_copilot_viewport(path/'Q06_Response_B.pdf',badges=('uptodate',))
            workbook=TemplateWorkbook(TEMPLATE)
            args=SimpleNamespace(input=str(path),max_docs=0,tool='COP')
            with self.assertRaisesRegex(ValueError,'Multiple DIFFERENT Copilot responses'):
                gather(args,workbook,None)

    def test_prior_contaminated_copilot_excel_cannot_be_reused(self):
        wb=TemplateWorkbook(TEMPLATE)
        c={'tool':'COP','question':'Q01','order':1,'citation':'Projects',
           'url':'https://copilot.com/projects?fromcode=abc',
           'title':'NR','authors':'NR','year':'NR','journal':'NR',
           'doi':'NR','pmid':'NR','repeat':'N'}
        wb.upsert_blue(c)
        with self.assertRaisesRegex(ValueError,'invalid Copilot UI/sidebar'):
            reject_contaminated_copilot_workbook(wb)

    def test_original_medical_source_in_copilot_excel_is_not_rejected(self):
        wb=TemplateWorkbook(TEMPLATE)
        c={'tool':'COP','question':'Q01','order':1,'citation':'nih',
           'url':'https://pubmed.ncbi.nlm.nih.gov/12345678/',
           'title':'NR','authors':'NR','year':'NR','journal':'NR',
           'doi':'NR','pmid':'NR','repeat':'N'}
        wb.upsert_blue(c)
        self.assertIsNone(reject_contaminated_copilot_workbook(wb))

    def test_copilot_nav_never_removed_from_non_viewport_official_source(self):
        self.assertFalse(is_sidebar_link('https://doi.org/10.1234/synthetic'))
