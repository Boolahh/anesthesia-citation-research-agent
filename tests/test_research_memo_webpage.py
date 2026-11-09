"""Evidence reuse and conservative webpage-metadata tests.

All records are synthetic; no live network access or unpublished PDFs.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from agent.research import Bibliography, valid_public_page_title


class EvidenceMemoizationTests(TestCase):
    def engine(self, root):
        return Bibliography({}, Path(root), offline=True)

    def test_same_numbered_source_reuses_evidence_across_pdf_fragments(self):
        with TemporaryDirectory() as tmp:
            client = self.engine(tmp)
            page = {
                'title': 'Tracheal Intubation Techniques in Head and Neck Surgery - NYSORA',
                'meta': {'og:title': ['Tracheal Intubation Techniques in Head and Neck Surgery']},
            }
            a = {'citation': '3', 'title': 'NR', 'doi': 'NR', 'pmid': 'NR',
                 'url': 'https://nysora.com/education-news/intubation/#1#1'}
            with patch.object(client, 'public_page', return_value=page) as mocked:
                first = client.metadata(a)
                second = client.metadata({**a, 'url': a['url'].split('#')[0] + '#5#5'})
            mocked.assert_called_once()
            self.assertEqual(second['lookup_events'][0]['status'], 'source_memo_hit')
            self.assertEqual(first['source_url'], 'https://nysora.com/education-news/intubation/')
            self.assertEqual(first['source_url'], second['source_url'])
            self.assertEqual(client.baseline_green(first)['Z'],
                             'Tracheal Intubation Techniques in Head and Neck Surgery')
            self.assertEqual(client.baseline_green(second)['Z'],
                             'Tracheal Intubation Techniques in Head and Neck Surgery')
            self.assertIn('unverified',
                          first['field_provenance']['Z']['source'].lower())

    def test_different_citation_labels_not_mistaken_for_same_verified_record(self):
        with TemporaryDirectory() as tmp:
            client = self.engine(tmp)
            url = 'https://example.org/path'
            with patch.object(client, 'public_page',
                              return_value={'title': 'Clinical Guidelines for Airway Management',
                                            'meta': {}}) as mocked:
                client.metadata({'citation': '3', 'title': 'NR', 'url': url})
                client.metadata({'citation': '14', 'title': 'NR', 'url': url})
            self.assertEqual(mocked.call_count, 2)

    def test_webpage_title_is_never_a_reality_verdict(self):
        with TemporaryDirectory() as tmp:
            client = self.engine(tmp)
            url = 'https://example.org/anesthesia-protocol'
            with patch.object(client, 'public_page',
                              return_value={'title': 'Clinical Guidance for Anesthesia Providers',
                                            'meta': {}}):
                evidence = client.metadata({'citation': '7', 'title': 'NR', 'url': url})
            row = client.baseline_green(evidence)
            self.assertEqual(row['Z'], 'Clinical Guidance for Anesthesia Providers')
            self.assertEqual(row['AN'], 'NR')
            self.assertEqual(row['BE'], '')
            self.assertTrue(any('manually' in s for s in evidence['review_flags']))

    def test_recognized_medical_education_site_is_proposed_not_assumed_study(self):
        with TemporaryDirectory() as tmp:
            client = self.engine(tmp)
            with patch.object(client, 'public_page', return_value={
                'title': 'Tracheal Intubation Techniques in Head and Neck Surgery',
                'meta': {},
            }):
                evidence = client.metadata({
                    'citation': '3', 'title': 'NR',
                    'url': 'https://nysora.com/education-news/tracheal-intubation-techniques/'})
            fields = client.baseline_green(evidence)
            self.assertEqual(fields['AD'], 'Professional society or organization webpage')
            self.assertEqual(fields['AE'], 'Not a research study (guideline, textbook, website...)')
            self.assertEqual(fields['BF'], 'Not applicable (not a scholarly publication)')
            self.assertEqual(fields['AN'], 'NR')
            self.assertTrue(any('reviewer must confirm' in text
                                for text in evidence['review_flags']))

    def test_point_of_care_manual_is_not_mislabeled_journal_article(self):
        with TemporaryDirectory() as tmp:
            client = self.engine(tmp)
            with patch.object(client, 'public_page', return_value={
                'title': 'How to Perform Tracheal Intubation - Professional Manual',
                'meta': {},
            }):
                evidence = client.metadata({
                    'citation': '4', 'title': 'NR',
                    'url': 'https://www.msdmanuals.com/professional/tracheal-intubation'})
            fields = client.baseline_green(evidence)
            self.assertEqual(
                fields['AD'], 'Point-of-care resource topic (e.g. UpToDate, DynaMed, StatPearls)')
            self.assertEqual(fields['AJ'], 'NR')

    def test_rejects_error_and_navigation_page_titles(self):
        for title in ('403 Access Denied', 'Just a moment - checking your browser',
                      'Sign In to Clinical Website', '404 page not found',
                      'Cookie Preferences Page'):
            with self.subTest(title=title):
                self.assertEqual(valid_public_page_title(title), '')
        self.assertEqual(valid_public_page_title(
            'Tracheal Intubation Techniques in Head and Neck Surgery'),
            'Tracheal Intubation Techniques in Head and Neck Surgery')

    def test_pubmed_html_skipped_when_xml_metadata_already_exists(self):
        with TemporaryDirectory() as tmp:
            client = self.engine(tmp)
            with patch.object(client, '_europe', return_value=None), \
                 patch.object(client, '_pubmed', return_value={
                     'pmid': '12345678', 'title': 'Synthetic trial about anesthetic approach'}), \
                 patch.object(client, 'fetch_json', return_value=None), \
                 patch.object(client, 'public_page') as webpage:
                evidence = client.metadata({
                    'citation': '8', 'title': 'NR', 'pmid': 'NR', 'doi': 'NR',
                    'url': 'https://pubmed.ncbi.nlm.nih.gov/12345678/#7#8'})
            webpage.assert_not_called()
            self.assertEqual(evidence['pubmed']['title'],
                             'Synthetic trial about anesthetic approach')
