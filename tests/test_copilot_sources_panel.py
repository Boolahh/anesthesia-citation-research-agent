"""Copilot modern Edge right-side source-drawer correctness regressions.

The investigator's real November print PDFs were independently inspected:
13 single-page files, 20 clickable Copilot UI links *per file*, 55 visible
entries under the Citations headings, and no original scholarly URI links.
No private PDFs or chat text are committed to this public repository.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import pymupdf as fitz

from agent.copilot_export import cited_sources_panel
from agent.pdf_extract import parse_pdf
from agent.source_dedup import unique_question_sources
from agent.workbook import TemplateWorkbook
from run_agent import gather


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'template' / 'AI_Citation_Bias_Extraction_Workbook.xlsx'


def make_export(path, cited=None, more=None, actual_url=None):
    cited = cited or [
        ('Fifth Consensus Guidelines for the Management o...',
         'cdn-links.lww.com'),
        ('Perioperative medicine: evidence-based review',
         'bmj.com'),
        ('Fifth Consensus Guidelines for the Management o...',
         'cdn-links.lww.com'),
    ]
    more = more or [
        ('Related articles must not become citations', 'example.org'),
        ('Another recommendation excluded', 'example.edu'),
    ]
    with fitz.open() as doc:
        page = doc.new_page(width=2384, height=3370)
        page.insert_text((280, 130),
                         'What strategies reduce postoperative nausea?',
                         fontsize=13)
        page.insert_text((300, 190), 'Visible Copilot response body.',
                         fontsize=12)
        page.insert_text((410, 230), 'nih +1', fontsize=7.5)
        page.insert_text((2074, 54), 'Sources', fontsize=14)
        page.insert_text((2068, 135), 'Citations', fontsize=13)
        for i, (title, domain) in enumerate(cited):
            y=158+39*i
            page.insert_text((2092, y),title+'\n'+domain,fontsize=10)
            if actual_url and i == 1:
                page.insert_link({
                    'kind':fitz.LINK_URI,
                    'from':fitz.Rect(2091,y-12,2330,y+16),
                    'uri':actual_url,
                })
        more_y = 165 + 39*len(cited)
        page.insert_text((2068, more_y), 'More', fontsize=13)
        for i, (title, domain) in enumerate(more):
            page.insert_text((2092, more_y+28+39*i),
                             title+'\n'+domain,fontsize=10)
        page.insert_text((410, 650),
                         'Copilot is an AI and may make mistakes.',fontsize=11)
        for i in range(20):
            url=('https://copilot.com/cowork' if i==0
                 else 'https://copilot.com/chat/conversation/'+str(i))
            page.insert_link({
                'kind':fitz.LINK_URI,
                'from':fitz.Rect(34,68+25*i,206,91+25*i),
                'uri':url,
            })
        doc.save(path)


class ModernCopilotSourcesPanelTests(TestCase):
    def test_only_citations_panel_not_more_or_nav_or_inline_badge(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q01_Copilot.pdf'
            make_export(path)
            with fitz.open(path) as doc:
                panel=cited_sources_panel(list(doc))
                self.assertEqual(len(doc[0].get_links()),20)
            self.assertEqual(len(panel),3)
            self.assertTrue(all(row['url']=='' for row in panel))
            self.assertEqual(panel[0]['evidence']['visible_domain'],
                             'cdn-links.lww.com')
            rows,warnings=parse_pdf(path,'COP',{'Q01':'Synthetic PONV question'})
            self.assertEqual(len(rows),3,
                             [x['citation'] for x in rows])
            self.assertFalse(any('More' in x['citation'] for x in rows))
            self.assertFalse(any(x['url'].startswith('https://copilot.com')
                                 for x in rows))
            self.assertFalse(any(x['citation']=='nih +1' for x in rows))
            self.assertEqual(rows[0]['url'],'NR')
            self.assertEqual(rows[0]['title'],'NR')  # clipped title
            self.assertEqual(rows[1]['title'],
                             'Perioperative medicine: evidence-based review')
            self.assertEqual(rows[0]['authors'],'NR')
            self.assertEqual(rows[0]['pmid'],'NR')
            self.assertTrue(any('Citations panel: 3' in w for w in warnings))
            self.assertTrue(any('NO original publication URL' in w for w
                                in warnings))
            self.assertTrue(any('Sources > More' in w for w in warnings))
            self.assertEqual(len(unique_question_sources(rows)),3,
                             'Two clipped identical titles cannot prove same source')

    def test_one_real_source_link_survives_from_citations_drawer(self):
        target='https://pubmed.ncbi.nlm.nih.gov/12345678/'
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q01_COP.pdf'
            make_export(path,actual_url=target)
            rows,warnings=parse_pdf(path,'COP',{'Q01':'An example question'})
            self.assertEqual(len(rows),3)
            linked=[x for x in rows if x['url']==target]
            self.assertEqual(len(linked),1)
            self.assertEqual(linked[0]['title'],
                             'Perioperative medicine: evidence-based review')
            self.assertEqual(len([x for x in rows if x['url']=='NR']),2)

    def test_entire_sidebar_more_is_not_a_bibliography(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q01_Copilot.pdf'
            make_export(path,cited=[('Real source shown','nejm.org')],
                        more=[('Merely recommended but not cited',
                               'pubmed.ncbi.nlm.nih.gov')])
            rows,_=parse_pdf(path,'COP',{'Q01':'An example question'})
            self.assertEqual(len(rows),1)
            self.assertIn('Real source shown',rows[0]['citation'])

    def test_duplicate_q06_is_detected_before_pdf_extraction(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)
            make_export(path/'Managing Hypoxemia During One-Lung Ventilation.pdf')
            make_export(path/'Preventing Hypoxemia During One-Lung Ventilation.pdf')
            wb=TemplateWorkbook(TEMPLATE)
            args=SimpleNamespace(input=str(path),max_docs=0,tool='COP')
            with patch('run_agent.parse_pdf') as parser:
                with self.assertRaisesRegex(ValueError,
                                             'Multiple DIFFERENT Copilot responses'):
                    gather(args,wb,None)
                parser.assert_not_called()
