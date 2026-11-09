"""Bounded public-source PDF inspection, with synthetic source documents only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import fitz

from agent.pdf_publication import inspect_public_pdf, plausible_document_title
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
