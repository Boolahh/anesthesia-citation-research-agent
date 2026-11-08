"""Bibliographic title and green-field quality checks using synthetic data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, Mock

from agent.research import Bibliography, citation_title_similarity
from agent.workbook import TemplateWorkbook, GREEN_COLS
from run_agent import enrich, _research_audit

ROOT = Path(__file__).resolve().parents[1]


class ResearchTitleQualityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = TemplateWorkbook(ROOT / 'template/AI_Citation_Bias_Extraction_Workbook.xlsx')

    def _citation_and_engine(self, folder, title):
        original = ('1. Rivers R, et al. Oxygenation during one lung ventilation. '
                    'Medical Education. 2023;23(9):328-336. Full article')
        citation = {'url': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/',
                    'citation': original,
                    'title': 'et al. Oxygenation during one lung ventilation. Medical Education. 2023',
                    'doi': 'NR', 'pmid': 'NR'}
        pubmed = {'pmid': '12345678', 'doi': '10.1111/correct',
                  'title': title, 'year': '2023',
                  'authors': [{'name': 'Test A', 'affiliations': []}]}
        return citation, Bibliography(self.workbook.data.countries, folder, offline=True), pubmed

    def test_exact_title_inside_formatted_reference_is_not_false_conflict(self):
        original = ('1. Rivers R, et al. Oxygenation during one lung ventilation. '
                    'Medical Education. 2023;23(9):328-336. Full article')
        score, basis = citation_title_similarity(
            'et al. Oxygenation during one lung ventilation. Medical Education. 2023',
            original, 'Oxygenation during one lung ventilation')
        self.assertEqual(score, 1.0)
        self.assertIn('verbatim', basis)

    def test_matching_publication_does_not_mislabel_reference_as_wrong(self):
        with TemporaryDirectory() as folder:
            c, engine, pubmed = self._citation_and_engine(
                folder, 'Oxygenation during one lung ventilation')
            with patch.object(engine, '_europe', return_value=None), \
                 patch.object(engine, '_convert_pmc',
                              return_value={'pmid': '12345678', 'doi': '10.1111/correct'}), \
                 patch.object(engine, '_pubmed', return_value=pubmed), \
                 patch.object(engine, 'fetch_json', return_value=None), \
                 patch.object(engine, 'public_page', return_value=None):
                result = engine.metadata(c)
            self.assertEqual(result['match']['title_similarity'], 1.0)
            self.assertFalse(any('differs materially' in x
                                 for x in result['match']['warnings']))
            self.assertIn('Medical Education', c['citation'])

    def test_actual_mismatched_title_is_still_flagged(self):
        with TemporaryDirectory() as folder:
            c, engine, pubmed = self._citation_and_engine(
                folder, 'Research methods for computational neurological imaging')
            with patch.object(engine, '_europe', return_value=None), \
                 patch.object(engine, '_convert_pmc',
                              return_value={'pmid': '12345678', 'doi': '10.1111/correct'}), \
                 patch.object(engine, '_pubmed', return_value=pubmed), \
                 patch.object(engine, 'fetch_json', return_value=None), \
                 patch.object(engine, 'public_page', return_value=None):
                result = engine.metadata(c)
            self.assertTrue(any('differs materially' in x
                                for x in result['match']['warnings']))

    def test_no_meaningful_metadata_does_not_write_placeholders(self):
        with TemporaryDirectory() as folder:
            engine = Bibliography(self.workbook.data.countries, folder, offline=True)
            evidence = {'doi': '', 'pmid': '', 'pubmed': None, 'crossref': None,
                        'openalex': None, 'europepmc': None,
                        'public_page': {'url': 'https://example.org/article',
                                        'title': 'Generic', 'meta': {}, 'excerpt': ''},
                        'source_url': 'https://example.org/article',
                        'match': {'warnings': []}, 'review_flags': [], 'lookup_events': []}
            with patch.object(engine, 'metadata', return_value=evidence):
                result = enrich({'title': 'Unknown', 'url': 'https://example.org/article'},
                                self.workbook, engine, None)
            self.assertEqual(result['informative_fields'], 0)
            self.assertFalse(result['can_autowrite'])
            report = _research_audit([
                {'tool': 'CGP', 'question': 'Q01', 'order': 1, 'citation': 'Example',
                 'url': 'https://example.org/article'}], [
                {'tool': 'CGP', 'question': 'Q01', 'order': 1,
                 **result, 'written_to_workbook': False}])
            self.assertEqual(report[0]['research_status'],
                             'metadata_without_informative_fields')

    def test_online_first_year_difference_flagged_without_invalidating_source(self):
        engine = Mock()
        engine.metadata.return_value = {
            'pubmed': {'online_year': '2025', 'pmid': '12345678'},
            'match': {'warnings': []},
            'review_flags': [],
            'lookup_events': [],
            'source_url': 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
            'doi': '10.1234/example', 'pmid': '12345678',
        }
        engine.baseline_green.return_value = {
            **{c: 'NR' for c in GREEN_COLS}, 'AA': '2026',
            'Z': 'Synthetic online-first study'
        }
        outcome = enrich({'year': '2025', 'title': 'Synthetic online-first study'},
                         self.workbook, engine, None)
        self.assertTrue(any('online-first publication year' in f
                            for f in outcome['review_flags']))
        self.assertTrue(outcome['can_autowrite'])
        self.assertFalse(any('Wrong year' in f
                             for f in outcome['review_flags']))

    def test_guideline_version_year_difference_requires_review_not_error(self):
        engine = Mock()
        engine.metadata.return_value = {
            'pubmed': {'online_year': '2025', 'pmid': '12345678'},
            'match': {'warnings': []},
            'review_flags': [],
            'lookup_events': [],
        }
        engine.baseline_green.return_value = {
            **{c: 'NR' for c in GREEN_COLS}, 'AA': '2025',
            'AD': 'Guideline', 'Z': '2024 Synthetic practice guidelines'
        }
        outcome = enrich({'year': '2024', 'title': '2024 Synthetic practice guidelines'},
                         self.workbook, engine, None)
        self.assertTrue(any('guideline-version' in f
                            for f in outcome['review_flags']))
        self.assertTrue(outcome['can_autowrite'])

    def test_html_entities_are_unescaped_in_publication_fields(self):
        with TemporaryDirectory() as folder:
            engine = Bibliography(self.workbook.data.countries, folder, offline=True)
            evidence = {
                'doi': '10.1234/example', 'pmid': '', 'pubmed': None,
                'crossref': None, 'europepmc': None, 'public_page': None,
                'source_url': 'https://doi.org/10.1234/example',
                'openalex': {'id': 'https://openalex.org/W123',
                             'display_name': 'A &amp; B Test Title',
                             'primary_location': {'source': {'display_name': 'Science &amp; Healthcare'}}}}
            fields = engine.baseline_green(evidence)
            self.assertEqual(fields['Z'], 'A & B Test Title')
            self.assertEqual(fields['BA'], 'Science & Healthcare')
