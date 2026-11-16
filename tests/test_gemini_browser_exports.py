"""Real-layout Gemini browser-print citation safety regressions.

The three investigator PDF exports were inspected locally (not committed):
all 1 page, two clickable Google UI links and zero scholarly URI annotations
each. Q10 and Q12 have no source badges; Q11 visibly shows 'PMC - NIH'
and 'ResearchGate + 2', with the '+2' underlying identities unavailable.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import pymupdf as fitz

from agent.gemini_export import (
    is_gemini_interface_url, is_gemini_browser_print,
    gemini_visible_source_badges,
)
from agent.pdf_extract import parse_pdf
from agent.workbook import TemplateWorkbook
from run_agent import reject_contaminated_gemini_workbook


TEMPLATE = (Path(__file__).resolve().parents[1] / 'template' /
            'AI_Citation_Bias_Extraction_Workbook.xlsx')


def make_gemini_print(path, badges=(), cite_url=None, prose=None):
    with fitz.open() as doc:
        page = doc.new_page(width=2384, height=3370)
        page.insert_text((1088, 112), 'What should anesthesia management use?',
                         fontsize=13)
        page.insert_text((922, 208),
                         prose or 'General anesthetic information without references.',
                         fontsize=13)
        page.insert_text((955, 484),
                         'The MYRIAD Trial is described in this narrative, '
                         'but that mention is not a linked bibliography.',
                         fontsize=13)
        for index, label in enumerate(badges):
            x,y=1025+index*25,283+index*290
            page.insert_text((x,y),label,fontsize=9.8)
            if index == 0:
                # Chromium browser print can duplicate identical text in PDF
                # draw order; that does not imply a second citation.
                page.insert_text((x,y),label,fontsize=9.8)
            if cite_url and index == 0:
                page.insert_link({
                    'kind':fitz.LINK_URI,
                    'from':fitz.Rect(x-2,y-12,x+160,y+1),
                    'uri':cite_url,
                })
        page.insert_link({
            'kind':fitz.LINK_URI,
            'from':fitz.Rect(2276,38,2306,68),
            'uri':'https://www.google.ca/intl/en/about/products',
        })
        page.insert_link({
            'kind':fitz.LINK_URI,
            'from':fitz.Rect(2308,34,2344,70),
            'uri':('https://accounts.google.com/SignOutOptions?hl=en&continue='
                   'https://gemini.google.com/u/1/%3FpageId%3Dnone'),
        })
        doc.save(path)


class GeminiPrintSafetyTests(TestCase):
    def test_browser_app_links_are_not_medical_sources(self):
        self.assertTrue(is_gemini_interface_url(
            'https://www.google.ca/intl/en/about/products'))
        self.assertTrue(is_gemini_interface_url(
            'https://accounts.google.com/SignOutOptions?continue='
            'https://gemini.google.com/u/1/'))
        self.assertFalse(is_gemini_interface_url(
            'https://pubmed.ncbi.nlm.nih.gov/12345678/'))
        self.assertFalse(is_gemini_interface_url(
            'https://doi.org/10.1234/synthetic'))

    def test_visible_gemini_badges_only_and_duplicated_pdf_text_not_recounted(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'Q11_Gemini.pdf'
            make_gemini_print(p,badges=('PMC - NIH','ResearchGate + 2'))
            with fitz.open(p) as d:
                self.assertTrue(is_gemini_browser_print(d))
                candidates=gemini_visible_source_badges(d)
            self.assertEqual([c['citation'] for c in candidates],
                             ['PMC - NIH','ResearchGate + 2'])
            rows,warnings=parse_pdf(p,'GEM',{'Q11':'Anesthesia CABG TIVA'})
            self.assertEqual(len(rows),2)
            self.assertEqual([x['citation'] for x in rows],
                             ['PMC - NIH','ResearchGate + 2'])
            self.assertEqual([x['url'] for x in rows],['NR','NR'])
            self.assertTrue(all(x['title']=='NR' for x in rows))
            self.assertTrue(all(x['doi']=='NR' and x['pmid']=='NR'
                                for x in rows))
            self.assertTrue(any('excluded 2 Google' in w for w in warnings))
            self.assertTrue(any('+N means hidden' in w for w in warnings))
            self.assertTrue(any('2 source badge(s)' in w for w in warnings))
            self.assertFalse(any('MYRIAD' in x['citation'] for x in rows))

    def test_gemini_untagged_clinical_answer_creates_no_invented_sources(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'Q10_Gemini.pdf'
            make_gemini_print(p,badges=())
            rows,warnings=parse_pdf(p,'GEM',{'Q10':'Pediatric URTI'})
            self.assertEqual(rows,[])
            self.assertTrue(any('no explicit source badges' in w for w in warnings))
            self.assertTrue(any('not proof' in w for w in warnings))
            self.assertTrue(any('excluded 2 Google' in w for w in warnings))

    def test_real_embedded_pubmed_link_kept_without_google_controls(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'Q11_Gemini.pdf'
            url='https://pubmed.ncbi.nlm.nih.gov/12345678/'
            make_gemini_print(p,badges=('PMC - NIH',),cite_url=url)
            rows,_=parse_pdf(p,'GEM',{'Q11':'CABG TIVA'})
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['url'],url)
            self.assertEqual(rows[0]['pmid'],'12345678')
            self.assertEqual(rows[0]['citation'],'PMC - NIH')

    def test_existing_workbook_with_google_account_link_is_rejected(self):
        wb=TemplateWorkbook(TEMPLATE)
        source={'tool':'GEM','question':'Q11','order':1,
                'citation':'Google apps','title':'NR','authors':'NR',
                'year':'NR','journal':'NR','doi':'NR','pmid':'NR',
                'repeat':'N',
                'url':'https://www.google.ca/intl/en/about/products'}
        wb.upsert_blue(source)
        with self.assertRaisesRegex(ValueError,'invalid Gemini'):
            reject_contaminated_gemini_workbook(wb)

    def test_valid_gemini_source_does_not_trigger_navigation_rejection(self):
        wb=TemplateWorkbook(TEMPLATE)
        wb.upsert_blue({'tool':'GEM','question':'Q11','order':1,
                        'citation':'PMC - NIH','title':'NR','authors':'NR',
                        'year':'NR','journal':'NR','doi':'NR','pmid':'NR',
                        'repeat':'N',
                        'url':'https://pubmed.ncbi.nlm.nih.gov/12345678/'})
        self.assertIsNone(reject_contaminated_gemini_workbook(wb))
