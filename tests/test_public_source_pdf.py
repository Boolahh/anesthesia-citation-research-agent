"""Bounded public-source PDF inspection, with synthetic source documents only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import fitz

from agent.pdf_publication import (inspect_public_pdf, plausible_document_title,
                                   visible_first_page_title_hint, filename_corroborated_title,
                                   anzca_blue_book_frontmatter, MAX_PDF_BYTES)
from agent.research import Bibliography


class Response:
    status_code = 200
    is_redirect = False
    headers = {'Content-Type': 'application/pdf'}

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        yield self.body


def make_document(visible, metadata_title):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 90), visible, fontsize=12)
        doc.set_metadata({'title': metadata_title})
        return doc.tobytes()


class PublicSourcePDFTests(TestCase):
    def test_matching_embedded_visible_title_is_reviewable(self):
        title = 'Guidelines for the Safe Management of Anesthetic Emergencies'
        document = make_document(title, title)
        session = Mock()
        session.get.return_value = Response(document)
        result = inspect_public_pdf(
            'https://example.org/clinical-guidelines.pdf',
            session, lambda _: True)
        self.assertEqual(result['status'], 'read')
        self.assertEqual(result['title'], title)
        self.assertEqual(result['pages'], 1)

    def test_pdf_metadata_not_visible_in_document_cannot_be_claimed(self):
        document = make_document(
            'An unrelated operational document on the first page',
            'Guidelines for the Safe Management of Anesthetic Emergencies')
        session = Mock()
        session.get.return_value = Response(document)
        result = inspect_public_pdf(
            'https://example.org/file.pdf', session, lambda _: True)
        self.assertEqual(result['status'], 'read')
        self.assertEqual(result['title'], '')

    def test_first_page_heading_is_a_review_hint_not_an_authenticated_title(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((40, 90),
                             'Massiv blodning - Anestesirutin',
                             fontsize=21)
            page.insert_text((40, 145),
                             'A hospital document about massive haemorrhage',
                             fontsize=10)
            body = doc.tobytes()
        session=Mock()
        session.get.return_value=Response(body)
        result=inspect_public_pdf('https://example.org/local.pdf',
                                  session, lambda _: True)
        self.assertEqual(result['status'],'read')
        self.assertEqual(result['title'],'')
        self.assertEqual(result['title_hint'],'Massiv blodning - Anestesirutin')
        self.assertIn('reviewer only',result['title_basis'])

    def test_optional_blue_book_size_cap_supports_2025_anesthesiology_compilation(self):
        # The officially linked 2025 ANZCA Blue Book is ~16.8MB.
        # This asserts only the opt-in transfer budget, not publication validity.
        self.assertGreater(MAX_PDF_BYTES, 16_820_000)

    def test_swedish_public_document_title_matches_first_page_and_original_filename(self):
        swedish = 'Massiv blödning - Anestesirutin'
        self.assertEqual(
            filename_corroborated_title(
                'https://mellanarkiv-offentlig.vgregion.se/alfresco/SURROGATE/'
                'Massiv%20bl%C3%B6dning%20-%20Anestesirutin.pdf#1#1', swedish),
            swedish)
        self.assertEqual(filename_corroborated_title(
            'https://example.org/download.pdf', swedish), '')
        self.assertEqual(plausible_document_title(swedish), swedish)

    def test_matched_original_pdf_first_page_yields_provisional_title_only(self):
        title = 'Massive bleeding - Anesthesia protocol'
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((40, 80), title, fontsize=21)
            doc.set_metadata({'title': ''})
            binary = doc.tobytes()
        session = Mock()
        session.get.return_value = Response(binary)
        url = 'https://example.org/Massive%20bleeding%20-%20Anesthesia%20protocol.pdf'
        result = inspect_public_pdf(url, session, lambda _: True)
        self.assertEqual(result['title'], title)
        self.assertIn('matches source filename', result['title_basis'])

    def test_anzca_blue_book_frontmatter_requires_official_link_and_printed_title(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((40, 90), 'Preface', fontsize=15)
            page.insert_text((40, 120),
                             'The 2025 edition of Australasian Anaesthesia',
                             fontsize=12)
            doc.set_metadata({'title': ''})
            url = ('https://www.anzca.edu.au/getcontentasset/path/'
                   '2025_blue_book_pdf.pdf?download=1')
            candidate = anzca_blue_book_frontmatter(doc, url)
            self.assertEqual(candidate['title'], 'Australasian Anaesthesia 2025')
            self.assertEqual(candidate['publication_year'], '2025')
            self.assertEqual(candidate['document_kind'], 'edited_book_compilation')
            self.assertIsNone(anzca_blue_book_frontmatter(
                doc, 'https://fake-anzca.example.org/2025_blue_book_pdf.pdf'))
            self.assertIsNone(anzca_blue_book_frontmatter(
                doc, 'https://www.anzca.edu.au/2024_blue_book_pdf.pdf'))
            body = doc.tobytes()
        session = Mock()
        session.get.return_value = Response(body)
        result = inspect_public_pdf(url, session, lambda _: True)
        self.assertEqual(result['title'], 'Australasian Anaesthesia 2025')
        self.assertEqual(result['document_kind'], 'edited_book_compilation')

    def test_edited_volume_never_implies_first_author_or_author_country(self):
        with TemporaryDirectory() as tmp:
            engine = Bibliography({}, Path(tmp), offline=False,
                                  inspect_linked_pdfs=True)
            info = {
                'status': 'read', 'title': 'Australasian Anaesthesia 2025',
                'title_basis': 'publisher opening-page title and edition year',
                'document_kind': 'edited_book_compilation',
                'publication_year': '2025',
            }
            with patch('agent.research.inspect_public_pdf', return_value=info), \
                 patch.object(engine, 'fetch_json', return_value=None):
                evidence = engine.metadata({
                    'citation':'7', 'title':'NR', 'doi':'NR', 'pmid':'NR',
                    'url':'https://www.anzca.edu.au/assets/2025_blue_book_pdf.pdf',
                })
            fields = engine.baseline_green(evidence)
            self.assertEqual(fields['Z'], 'Australasian Anaesthesia 2025')
            self.assertEqual(fields['AA'], '2025')
            self.assertEqual(fields['AD'], 'Textbook or book chapter')
            self.assertEqual(fields['AN'], 'NR')
            self.assertEqual(fields['AL'], 'NR')
            self.assertIn('unverified', evidence['field_provenance']['Z']['source'].lower())
            self.assertTrue(any('edited book' in flag for flag in evidence['review_flags']))

    def test_draft_guideline_title_requires_version_review(self):
        with TemporaryDirectory() as tmp:
            engine = Bibliography({}, Path(tmp), offline=False, inspect_linked_pdfs=True)
            with patch('agent.research.inspect_public_pdf', return_value={
                'status':'read','title':'Practice Guidelines for Management of the Difficult Airway',
                'title_basis':'embedded title confirmed on first page',
            }), patch.object(engine,'fetch_json',return_value=None):
                evidence=engine.metadata({
                    'citation':'3','title':'NR',
                    'url':'https://www.asahq.org/-/media/sites/asahq/files/public/resources/'
                          'draft-guidelines/difficult-airway-guidelines-2022-06-2021.pdf',
                })
            engine.baseline_green(evidence)
            self.assertTrue(any('draft guideline PDF' in flag for flag in evidence['review_flags']))

    def test_publication_pdf_download_is_size_capped(self):
        document = make_document(
            'Guidelines for the Safe Management of Anesthetic Emergencies',
            'Guidelines for the Safe Management of Anesthetic Emergencies')
        session = Mock()
        session.get.return_value = Response(document)
        result = inspect_public_pdf(
            'https://example.org/file.pdf', session, lambda _: True,
            max_bytes=128)
        self.assertEqual(result['status'], 'too_large')

    def test_private_destination_blocked_before_network(self):
        session = Mock()
        result = inspect_public_pdf(
            'http://127.0.0.1/private.pdf', session, lambda _: False)
        self.assertEqual(result['status'], 'blocked_url')
        session.get.assert_not_called()

    def test_metadata_pipeline_never_promotes_pdf_guess_to_verified_identity(self):
        title = 'Guidelines for the Safe Management of Anesthetic Emergencies'
        with TemporaryDirectory() as tmp:
            engine = Bibliography({}, Path(tmp), offline=False,
                                  inspect_linked_pdfs=True)
            with patch('agent.research.inspect_public_pdf',
                       return_value={'status': 'read', 'title': title}) as parser, \
                 patch.object(engine, 'fetch_json', return_value=None), \
                 patch.object(engine, 'public_page') as page:
                result = engine.metadata({
                    'citation': '5', 'title': 'NR', 'doi': 'NR', 'pmid': 'NR',
                    'url': 'https://example.org/clinical-guidelines.pdf'})
            parser.assert_called_once()
            page.assert_not_called()
            row = engine.baseline_green(result)
            self.assertEqual(row['Z'], title)
            self.assertEqual(row['AN'], 'NR')
            self.assertEqual(row['BE'], '')
            self.assertTrue(any('verify full source' in text
                                for text in result['review_flags']))
            self.assertEqual(
                result['field_provenance']['Z']['source'],
                'Original linked PDF metadata title (unverified)')

    def test_pdf_inspection_off_by_default(self):
        with TemporaryDirectory() as tmp:
            engine = Bibliography({}, Path(tmp), offline=True)
            with patch('agent.research.inspect_public_pdf') as parser, \
                 patch.object(engine, 'fetch_json', return_value=None), \
                 patch.object(engine, 'public_page') as page:
                result = engine.metadata({
                    'citation': '5', 'title': 'NR', 'doi': 'NR', 'pmid': 'NR',
                    'url': 'https://example.org/clinical-guidelines.pdf'})
            parser.assert_not_called()
            page.assert_not_called()
            self.assertIsNone(result['public_pdf'])


if __name__ == '__main__':
    import unittest
    unittest.main()
