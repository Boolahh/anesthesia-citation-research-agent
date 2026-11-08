"""Offline regression tests using synthetic citations, never private research conversations."""
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.workbook import TemplateWorkbook, set_value
from agent.pdf_extract import parse_pdf
from agent.research import safe_url, iso2_country

BASE = Path(__file__).resolve().parents[1]
TEMPLATE = BASE / 'template/AI_Citation_Bias_Extraction_Workbook.xlsx'

Q11 = 'Should volatile anesthesia or total intravenous anesthesia be used in an adult undergoing coronary artery bypass graft surgery?'
Q04 = 'How can local anesthetic systemic toxicity be prevented, recognized, and managed in adults receiving regional anesthesia?'


def make_chat_pdf(path, question, entries, heading='Selected references:'):
    """Create a tiny text+real URI annotation PDF for deterministic regression tests."""
    with fitz.open() as doc:
        page = doc.new_page(width=800, height=850)
        page.insert_text((52, 52), question, fontsize=9)
        page.insert_text((52, 98), heading, fontsize=11)
        for index, (citation, url) in enumerate(entries):
            baseline = 130 + 34 * index
            page.insert_text((60, baseline), citation, fontsize=10)
            if url:
                page.insert_link({
                    'kind': fitz.LINK_URI,
                    'from': fitz.Rect(58, baseline - 12, 620, baseline + 4),
                    'uri': url,
                })
        doc.save(path)


class AgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = TemplateWorkbook(TEMPLATE)

    def test_linked_citations_preserve_order_and_identifiers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Q11_examples.pdf'
            make_chat_pdf(path, Q11, [
                ('Landoni et al. MYRIAD trial, NEJM 2019', 'https://doi.org/10.1056/NEJMoa1816476'),
                ('Second research paper, 2020', 'https://pubmed.ncbi.nlm.nih.gov/32162897/'),
            ])
            rows, warnings = parse_pdf(path, 'CGP', self.workbook.data.questions)
            self.assertEqual(len(rows), 2, warnings)
            self.assertEqual([r['order'] for r in rows], [1, 2])
            self.assertEqual(rows[0]['question'], 'Q11')
            self.assertEqual(rows[0]['doi'].lower(), '10.1056/nejmoa1816476')
            self.assertEqual(rows[1]['pmid'], '32162897')
            self.assertTrue(all(r['url'].startswith('https://') for r in rows))

    def test_duplicate_citation_occurrences_not_silently_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Q11_duplicates.pdf'
            uri = 'https://doi.org/10.1056/NEJMoa1816476'
            make_chat_pdf(path, Q11, [('First mention', uri), ('Second mention', uri)])
            rows, warnings = parse_pdf(path, 'CGP', self.workbook.data.questions)
            self.assertEqual(len(rows), 2, warnings)
            self.assertEqual([r['repeat'] for r in rows], ['N', 'Y'])

    def test_combined_pdf_detects_both_questions(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            a = folder / 'Q11_a.pdf'
            b = folder / 'Q04_b.pdf'
            make_chat_pdf(a, Q11, [('MYRIAD trial, 2019', 'https://doi.org/10.1056/NEJMoa1816476')])
            make_chat_pdf(b, Q04, [('LAST clinical guideline', 'https://pubmed.ncbi.nlm.nih.gov/32162897/')])
            combined = folder / 'combined.pdf'
            with fitz.open() as doc:
                for file in (a, b):
                    with fitz.open(file) as source:
                        doc.insert_pdf(source, links=True)
                doc.save(combined)
            rows, warnings = parse_pdf(combined, 'CGP', self.workbook.data.questions)
            self.assertEqual(len(rows), 2, warnings)
            self.assertEqual({r['question'] for r in rows}, {'Q11', 'Q04'})

    def test_unlinked_named_citation_kept_for_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Q01_unlinked.pdf'
            make_chat_pdf(path, 'What strategies reduce the risk of postoperative nausea and vomiting in adults undergoing general anesthesia?',
                          [('Fourth Consensus Guidelines for the Management of Postoperative Nausea and Vomiting (Gan et al., 2020)', '')])
            rows, warnings = parse_pdf(path, 'CGP', self.workbook.data.questions)
            self.assertEqual(len(rows), 1, warnings)
            self.assertEqual(rows[0]['url'], 'NR')
            self.assertTrue(any('No clickable URLs' in warning for warning in warnings))

    def test_preserves_other_workbook_parts_and_reviewer_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            pdf = folder / 'Q11_test.pdf'
            make_chat_pdf(pdf, Q11, [('MYRIAD trial, 2019', 'https://doi.org/10.1056/NEJMoa1816476')])
            result = folder / 'filled.xlsx'
            workbook = TemplateWorkbook(TEMPLATE)
            rows, warnings = parse_pdf(pdf, 'CGP', workbook.data.questions)
            for citation in rows:
                workbook.upsert_blue(citation)
            number = workbook.existing[('CGP', 'Q11', 1)]
            green = ['NR'] * 33
            green[0] = 'Verified title placeholder'
            self.assertFalse(workbook.upsert_green(number, green, 'verified-only'))
            set_value(workbook.data_rows[number], 'U', 'Real - correct')  # Simulated human verification
            self.assertTrue(workbook.upsert_green(number, green, 'verified-only'))
            self.assertEqual(workbook.get_row(number)['Z'], 'Verified title placeholder')
            self.assertFalse(workbook.get_row(number)['BG'])
            workbook.save(result)
            with ZipFile(TEMPLATE) as original, ZipFile(result) as changed:
                self.assertIsNone(changed.testzip())
                self.assertEqual(changed.namelist(), original.namelist())
                self.assertEqual(changed.read('xl/worksheets/sheet6.xml'), original.read('xl/worksheets/sheet6.xml'))
                self.assertEqual(changed.read('xl/worksheets/sheet11.xml'), original.read('xl/worksheets/sheet11.xml'))
            again = TemplateWorkbook(result)
            again.upsert_blue(rows[0])
            self.assertEqual(len(again.existing), 1)
            self.assertEqual(again.get_row(number)['U'], 'Real - correct')

    def test_private_and_local_urls_rejected(self):
        for url in ('file:///etc/passwd', 'http://localhost:8080/', 'http://127.0.0.1/',
                    'http://169.254.169.254/latest/meta-data/', 'https://service.internal/'):
            self.assertFalse(safe_url(url))
        self.assertTrue(safe_url('https://pubmed.ncbi.nlm.nih.gov/32162897/'))

    def test_country_mapping(self):
        name, region, income = iso2_country('CA', self.workbook.data.countries)
        self.assertEqual(name, 'Canada')
        self.assertEqual(region, 'Region of the Americas')


if __name__ == '__main__':
    unittest.main()
