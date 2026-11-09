"""Synthetic DeepSeek numbered-export regression tests (no private PDFs in GitHub)."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import fitz

from agent.deepseek_numbered import extract_deepseek_numbered
from agent.pdf_extract import parse_pdf


class DeepSeekNumberedCitationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def sample(self, instances, heading='Found 15 web pages'):
        path = Path(self.tmp.name) / 'Q01_DeepSeek.pdf'
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((60, 50), 'What strategies reduce postoperative nausea?', fontsize=12)
        page.insert_text((60, 100), heading, fontsize=12)
        for number, y, url, shift in instances:
            page.insert_text((200, y), str(number), fontsize=7)
            for area in (
                fitz.Rect(192, y-11, 212, y+7),
                fitz.Rect(196, y-9, 208, y+2),
                fitz.Rect(200, y-7, 204, y),
            ):
                page.insert_link({'kind': fitz.LINK_URI, 'uri': url,
                                  'from': area + fitz.Rect(0, shift, 0, shift)})
        doc.save(path)
        doc.close()
        return path

    def test_nested_link_rectangles_count_one_occurrence(self):
        path = self.sample([
            (8, 150, 'https://pubmed.ncbi.nlm.nih.gov/12345678/', 0),
            (8, 190, 'https://pubmed.ncbi.nlm.nih.gov/12345678/', 0),
            (11, 230, 'https://doi.org/10.1234/example', 0),
        ])
        with fitz.open(path) as doc:
            rows, warnings = extract_deepseek_numbered(doc)
        self.assertEqual([row['citation'] for row in rows], ['8', '8', '11'])
        self.assertTrue(all(row['evidence']['link_rectangles_collapsed'] == 3
                            for row in rows))
        self.assertFalse(warnings)

    def test_web_pages_found_are_not_counted_as_citations(self):
        path = self.sample([])
        with fitz.open(path) as doc:
            rows, warnings = extract_deepseek_numbered(doc)
        self.assertEqual(rows, [])

    def test_identical_url_in_distinct_positions_remains_two_citations(self):
        path = self.sample([
            (4, 150, 'https://pubmed.ncbi.nlm.nih.gov/12345678/', 0),
            (4, 170, 'https://pubmed.ncbi.nlm.nih.gov/12345678/', 0),
        ])
        with fitz.open(path) as doc:
            rows, warnings = extract_deepseek_numbered(doc)
        self.assertEqual(len(rows), 2)

    def test_page_break_displacement_requires_review(self):
        path = self.sample([
            (7, 150, 'https://pubmed.ncbi.nlm.nih.gov/12345678/', 55),
        ])
        with fitz.open(path) as doc:
            rows, warnings = extract_deepseek_numbered(doc)
        self.assertEqual([row['citation'] for row in rows], ['7'])
        self.assertEqual(rows[0]['confidence'], 'review')
        self.assertTrue(any('displaced' in warning for warning in warnings))

    def test_parser_keeps_number_as_citation_and_not_article_title(self):
        path = self.sample([
            (8, 150, 'https://pubmed.ncbi.nlm.nih.gov/12345678/', 0),
            (8, 190, 'https://pubmed.ncbi.nlm.nih.gov/12345678/', 0),
        ])
        with fitz.open(path) as doc:
            spans, warnings = extract_deepseek_numbered(doc)
        self.assertEqual([row['citation'] for row in spans], ['8', '8'])
        self.assertFalse(warnings)
        rows, warnings = parse_pdf(path, 'DSK', {
            'Q01': 'What strategies reduce postoperative nausea?'
        })
        self.assertEqual(len(rows), 2)
        self.assertEqual([row['repeat'] for row in rows], ['N', 'Y'])
        self.assertEqual([row['title'] for row in rows], ['NR', 'NR'])
        self.assertEqual([row['citation'] for row in rows], ['8', '8'])
        self.assertTrue(all(row['extraction_method'] == 'deepseek_numbered_link'
                            for row in rows))

    def test_no_fake_citations_if_source_count_but_no_source_links(self):
        path = self.sample([])
        rows, warnings = parse_pdf(path, 'DSK', {
            'Q01': 'What strategies reduce postoperative nausea?'
        })
        self.assertEqual(rows, [])
        self.assertTrue(any('No explicit citations' in warning for warning in warnings))


if __name__ == '__main__':
    unittest.main()
