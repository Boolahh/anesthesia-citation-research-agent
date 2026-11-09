"""Search-result link guard: original citations remain evidence, not fake papers."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent.research import Bibliography, non_source_search_landing, valid_public_page_title
from run_agent import _research_audit, _geography_review


class SearchResultCitationTests(TestCase):
    def test_pubmed_search_page_is_not_a_specific_source(self):
        url = 'https://pubmed.ncbi.nlm.nih.gov/?term=neuraxial+anaesthesia#1'
        with TemporaryDirectory() as tmp:
            engine = Bibliography({}, Path(tmp), offline=False)
            with patch.object(engine, 'public_page') as pages, \
                 patch.object(engine, 'fetch_json') as external:
                original = {'tool': 'DSK', 'question': 'Q07', 'order': 2,
                            'url': url, 'citation': '15', 'title': 'NR',
                            'doi': 'NR', 'pmid': 'NR'}
                evidence = engine.metadata(original)
                second = engine.metadata(original)
            pages.assert_not_called()
            external.assert_not_called()
            self.assertEqual(evidence['match']['status'], 'non_source_search_results')
            self.assertFalse(evidence['lookup_performed'])
            self.assertEqual(second['lookup_events'][0]['status'], 'source_memo_hit')
            self.assertEqual(evidence['source_url'], url.split('#')[0])
            self.assertEqual(engine.baseline_green(evidence)['Z'], 'NOT FOUND')
            self.assertIsNone(evidence['public_page'])

    def test_reviewer_audit_shows_error_clearly(self):
        citation = {'tool': 'DSK', 'question': 'Q07', 'order': 2,
                    'citation': '15',
                    'url': 'https://pubmed.ncbi.nlm.nih.gov/?term=neuraxial+anaesthesia'}
        with TemporaryDirectory() as tmp:
            engine = Bibliography({}, Path(tmp), offline=True)
            evidence = engine.metadata(citation)
        proposal = {
            'tool': 'DSK', 'question': 'Q07', 'order': 2,
            'fields': {'Z': 'NOT FOUND'}, 'has_metadata': False,
            'match': evidence['match'],
            'review_flags': evidence['match']['warnings'],
            'identifiers': {}, 'field_provenance': {},
        }
        audit = _research_audit([citation], [proposal])
        self.assertEqual(audit[0]['research_status'], 'search_results_link_not_single_publication')
        self.assertIn('not a specific cited publication', audit[0]['review_reasons'])

    def test_pubmed_article_link_not_blocked(self):
        self.assertEqual(non_source_search_landing(
            'https://pubmed.ncbi.nlm.nih.gov/38839472/'), '')
        self.assertEqual(non_source_search_landing(
            'https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/'), '')
        self.assertEqual(non_source_search_landing(
            'https://nysora.com/education-news/intubation-techniques/'), '')

    def test_search_engine_and_openalex_query_are_not_publications(self):
        for url in (
            'https://www.google.com/search?q=anesthesia',
            'https://scholar.google.com/scholar?q=airway',
            'https://www.bing.com/search?q=airway',
            'https://api.openalex.org/works?search=airway'):
            with self.subTest(url=url):
                self.assertTrue(non_source_search_landing(url))

    def test_search_results_page_titles_are_not_independent_works(self):
        self.assertEqual(valid_public_page_title(
            'neuraxial anaesthesia - Search Results - PubMed'), '')
        self.assertEqual(valid_public_page_title(
            'Search Results for perioperative hypotension'), '')
        self.assertTrue(valid_public_page_title(
            'The Effect of Anesthesia on Search Results in a Randomized Study'))

    def test_organization_and_government_websites_get_applicability_review(self):
        class Workbook:
            existing = {('DSK', 'Q01', 1): 4}
            def get_row(self, num):
                return {'Z': 'Anesthesia safety guidance', 'AD':
                        'Government or public-health agency document',
                        'AN': 'NR', 'AL': 'NR'}
        rows = [{'tool': 'DSK', 'question': 'Q01', 'order': 1,
                 'citation': '8', 'url': 'https://agency.gov/guide'}]
        geo = _geography_review(rows, [], Workbook())
        self.assertEqual(geo[0]['review_priority'], 'Applicability review')
        self.assertIn('whether an individual first author', geo[0]['review_action'])


if __name__ == '__main__':
    import unittest
    unittest.main()
