"""Regression: adjacent linked references must remain separate, even if
fallback reference-list extraction accidentally joins their visible text.

The fixture is fully synthetic. Unpublished research conversation PDFs stay local.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import sys
import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.pdf_extract import parse_pdf
from agent.workbook import TemplateWorkbook


class LinkBoundaryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.questions = TemplateWorkbook(ROOT / 'template/AI_Citation_Bias_Extraction_Workbook.xlsx').data.questions

    def test_consecutive_linked_sources_do_not_become_one_composite_title(self):
        entries = [
            ('Society A - Guidelines for Blood Components (2025)', 'https://doi.org/10.1000/society-a'),
            ('Journal B - Medical Review of Major Bleeding (2023)', 'https://doi.org/10.1000/journal-b'),
            ('Society C - Practice Guidelines for Blood Management', 'https://doi.org/10.1000/society-c'),
        ]
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'Q03_sources.pdf'
            with fitz.open() as pdf:
                page = pdf.new_page(width=820, height=660)
                page.insert_text((52, 55), 'Selected references:', fontsize=11)
                for i, (title, link) in enumerate(entries):
                    y = 90 + 19.5 * i
                    page.insert_text((68, y), title, fontsize=10)
                    page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(68, y-11, 620, y+3), 'uri': link})
                pdf.save(path)
            found, warnings = parse_pdf(path, 'CGP', self.questions)
            self.assertEqual(len(found), 3, warnings)
            self.assertEqual([r['citation'] for r in found], [x[0] for x in entries])
            self.assertEqual([r['url'] for r in found], [x[1] for x in entries])

    def test_generic_link_label_does_not_merge_previous_numbered_reference(self):
        previous = '2. OpenAnesthesia. Hypoxia During One-Lung Ventilation. Clinical review'
        expected = '3. StatPearls. Lung Isolation and One-Lung Ventilation. NCBI Bookshelf'
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'Q06_sources.pdf'
            with fitz.open() as pdf:
                page = pdf.new_page(width=820, height=660)
                page.insert_text((50, 55), 'References', fontsize=11)
                page.insert_text((56, 98), previous, fontsize=10)
                page.insert_text((56, 117.5), expected, fontsize=10)
                # The PDF anchor only covers the generic suffix NCBI Bookshelf.
                width = fitz.get_text_length('3. StatPearls. Lung Isolation and One-Lung Ventilation. ', fontsize=10)
                x = 56 + width
                page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(x, 106, x+110, 120),
                                  'uri': 'https://www.ncbi.nlm.nih.gov/books/NBK555933/'})
                pdf.save(path)
            found, warnings = parse_pdf(path, 'CGP', self.questions)
            matched = [r for r in found if 'NBK555933' in r['url']]
            self.assertEqual(len(matched), 1, warnings)
            self.assertEqual(matched[0]['citation'], expected)
            self.assertNotIn('OpenAnesthesia', matched[0]['citation'])


class RepeatedSameUrlTests(TestCase):
    def test_identical_url_on_adjacent_numbered_entries_remains_two_citations(self):
        """Repeated source occurrences are data, not annotation duplicates."""
        with TemporaryDirectory() as folder:
            path = Path(folder)/'Q06_repeated_link.pdf'
            url = 'https://pubmed.ncbi.nlm.nih.gov/12345678/'
            with fitz.open() as pdf:
                page = pdf.new_page(width=820, height=550)
                page.insert_text((52, 55), 'References', fontsize=11)
                for idx, name in enumerate(['1. Same systematic review, 2024',
                                            '2. Same systematic review, 2024']):
                    ypos = 90 + idx * 20
                    page.insert_text((65, ypos), name, fontsize=10)
                    page.insert_link({'kind':fitz.LINK_URI,
                        'from':fitz.Rect(65,ypos-12,420,ypos+3),'uri':url})
                pdf.save(path)
            book=TemplateWorkbook(ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx')
            extracted,warnings=parse_pdf(path,'CGP',book.data.questions)
            self.assertEqual(len(extracted),2, warnings)
            self.assertEqual([r['repeat'] for r in extracted],['N','Y'])
            self.assertEqual([r['order'] for r in extracted],[1,2])
            self.assertTrue(all(r['url']==url for r in extracted))
