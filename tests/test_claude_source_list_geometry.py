"""Synthetic Claude source-list geometry and repeated clickable badge regressions."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import fitz
from agent.pdf_extract import extract_links, _plain_references, parse_pdf
from agent.workbook import TemplateWorkbook

ROOT = Path(__file__).resolve().parents[1]
CABG_QUESTION = ('Should volatile anesthesia or total intravenous anesthesia be used '
                 'in an adult undergoing coronary artery bypass graft surgery?')
PONV_QUESTION = ('What strategies reduce the risk of postoperative nausea and vomiting '
                 'in adults undergoing general anesthesia?')


class ClaudeReferenceBoundaryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = TemplateWorkbook(ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx')

    def test_unnumbered_sources_section_keeps_unlinked_third_article(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q11.pdf'
            with fitz.open() as doc:
                page=doc.new_page(width=660,height=800)
                page.insert_text((45,52),CABG_QUESTION,fontsize=8)
                page.insert_text((45,100),'Sources:',fontsize=11)
                entries=[
                    ('Jiao et al., PLoS ONE 2019 - meta-analysis and trial sequential analysis',
                     'https://pmc.ncbi.nlm.nih.gov/articles/PMC6818786/'),
                    ('Cochrane Colloquium abstract of the same analysis',
                     'https://abstracts.cochrane.org/synthetic'),
                    ('Landoni G, et al. Volatile Anesthetics versus Total Intravenous Anesthesia for Cardiac',None),
                    ('Surgery (MYRIAD). N Engl J Med 2019;380:1214-1225.',None),
                ]
                for index, (title, url) in enumerate(entries):
                    y=[125,144,162,176][index]
                    page.insert_text((71,y),title,fontsize=9)
                    if url:
                        page.insert_link({
                            'kind':fitz.LINK_URI,
                            'from':fitz.Rect(70,y-11,610,y+3),
                            'uri':url,
                        })
                doc.save(path)
            with fitz.open(path) as doc:
                names=_plain_references(list(doc))
                self.assertEqual(len(names),3, names)
                self.assertIn('Surgery (MYRIAD)',names[2]['citation'])
            rows,warnings=parse_pdf(path,'CLG',self.book.data.questions)
            self.assertEqual(len(rows),3, (rows,warnings))
            self.assertTrue(any('Landoni' in r['citation']
                                and r['url']=='NR' for r in rows))

    def test_two_same_line_nysora_badges_are_two_link_occurrences(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q01.pdf'
            url='https://nysora.com/?p=68145'
            with fitz.open() as doc:
                page=doc.new_page(width=660,height=800)
                page.insert_text((40,45),PONV_QUESTION,fontsize=8)
                page.insert_text((120,150),'nysora   nysora',fontsize=10)
                page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(120,138,157,153),'uri':url})
                page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(164,138,204,153),'uri':url})
                doc.save(path)
            with fitz.open(path) as doc:
                annotations=extract_links(list(doc))
                self.assertEqual(len(annotations),2,annotations)
                self.assertEqual([x['url'] for x in annotations],[url,url])
            rows,warnings=parse_pdf(path,'CLG',self.book.data.questions)
            self.assertEqual(len(rows),2, (rows,warnings))
            self.assertEqual(rows[1]['repeat'],'Y')

    def test_neighboring_unnumbered_sources_with_distinct_links_not_merged(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q05.pdf'
            question=('How should an anticipated difficult airway be managed '
                      'in an adult undergoing general anesthesia?')
            links=[
                ('DAS 2025 guidelines (PubMed, Br J Anaesth 2026;136:283-307)',
                 'https://pubmed.ncbi.nlm.nih.gov/41203471/'),
                ('DAS intubation guidelines page',
                 'https://das.uk.com/guidelines/das_intubation_guidelines'),
                ('NYSORA - DAS 2025 update summary',
                 'https://nysora.com/das-2025'),
            ]
            with fitz.open() as doc:
                page=doc.new_page(width=720,height=500)
                page.insert_text((45,50),question,fontsize=8)
                page.insert_text((45,100),'Sources:',fontsize=11)
                for (name,url),y in zip(links,(125,145,162)):
                    page.insert_text((72,y),name,fontsize=9)
                    page.insert_link({'kind':fitz.LINK_URI,
                                     'from':fitz.Rect(72,y-11,600,y+3),'uri':url})
                doc.save(path)
            with fitz.open(path) as doc:
                entries=_plain_references(list(doc))
                self.assertEqual(len(entries),3,entries)
            results,warnings=parse_pdf(path,'CLG',self.book.data.questions)
            self.assertEqual(len(results),3,(results,warnings))

    def test_multiline_reference_one_url_is_one_source_occurrence(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'Q11.pdf'
            url='https://pubmed.ncbi.nlm.nih.gov/38839472/'
            with fitz.open() as doc:
                page=doc.new_page(width=800,height=600)
                page.insert_text((40,45),CABG_QUESTION,fontsize=8)
                page.insert_text((46,100),'Sources:',fontsize=11)
                page.insert_text((72,125),'International Consensus Statement on Perioperative Arterial Pressure',fontsize=10)
                page.insert_text((72,140),'Management, British Journal of Anaesthesia 2024',fontsize=10)
                for y in (125,140):
                    page.insert_link({'kind':fitz.LINK_URI,
                        'from':fitz.Rect(72,y-11,570,y+3), 'uri':url})
                doc.save(path)
            with fitz.open(path) as doc:
                links=extract_links(list(doc))
                self.assertEqual(len(links),1,links)
            rows,warnings=parse_pdf(path,'CLG',self.book.data.questions)
            self.assertEqual(len(rows),1,(rows,warnings))
