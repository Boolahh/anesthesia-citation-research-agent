"""Regression: adjacent linked sources must stay separate in PDF exports.

Fixtures are synthetic, never unpublished source conversations.
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
        cls.questions = TemplateWorkbook(
            ROOT / 'template/AI_Citation_Bias_Extraction_Workbook.xlsx'
        ).data.questions

    def test_consecutive_linked_sources_do_not_merge_titles(self):
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
                    page.insert_link({
                        'kind': fitz.LINK_URI,
                        'from': fitz.Rect(68, y-11, 620, y+3),
                        'uri': link,
                    })
                pdf.save(path)
            found, warnings = parse_pdf(path, 'CGP', self.questions)
            self.assertEqual(len(found), 3, warnings)
            self.assertEqual([r['citation'] for r in found], [x[0] for x in entries])
            self.assertEqual([r['url'] for r in found], [x[1] for x in entries])

    def test_generic_link_does_not_borrow_previous_numbered_reference(self):
        previous = '2. OpenAnesthesia. Hypoxia During One-Lung Ventilation. Clinical review'
        expected = '3. StatPearls. Lung Isolation and One-Lung Ventilation. NCBI Bookshelf'
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'Q06_sources.pdf'
            with fitz.open() as pdf:
                page = pdf.new_page(width=820, height=660)
                page.insert_text((50, 55), 'References', fontsize=11)
                page.insert_text((56, 98), previous, fontsize=10)
                page.insert_text((56, 117.5), expected, fontsize=10)
                width = fitz.get_text_length(
                    '3. StatPearls. Lung Isolation and One-Lung Ventilation. ',
                    fontsize=10,
                )
                x = 56 + width
                page.insert_link({
                    'kind': fitz.LINK_URI,
                    'from': fitz.Rect(x, 106, x+110, 120),
                    'uri': 'https://www.ncbi.nlm.nih.gov/books/NBK555933/',
                })
                pdf.save(path)
            found, warnings = parse_pdf(path, 'CGP', self.questions)
            matched = [r for r in found if 'NBK555933' in r['url']]
            self.assertEqual(len(matched), 1, warnings)
            self.assertEqual(matched[0]['citation'], expected)
            self.assertNotIn('OpenAnesthesia', matched[0]['citation'])
