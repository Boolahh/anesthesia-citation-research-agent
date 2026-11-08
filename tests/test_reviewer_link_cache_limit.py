"""Research access and cache-accounting regressions using synthetic records."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import hashlib
import json

from agent.research import Bibliography
from run_agent import research_candidate


class FakeWorkbook:
    existing = {('CGP', 'Q02', 1): 17}

    def __init__(self, verified=''):
        self.verified = verified

    def get_row(self, rownum):
        assert rownum == 17
        return {'X': self.verified}


class ResearchCandidateReviewTests(TestCase):
    def setUp(self):
        self.input = {
            'tool': 'CGP', 'question': 'Q02', 'order': 1,
            'citation': '2024 POQI consensus', 'title': '2024 POQI consensus',
            'url': 'NR', 'doi': 'NR', 'pmid': 'NR',
        }

    def test_short_original_citation_without_verified_link_is_ineligible(self):
        row, citation, eligible = research_candidate(self.input, FakeWorkbook())
        self.assertEqual(row, 17)
        self.assertFalse(eligible)
        self.assertIs(citation, self.input)

    def test_column_x_verified_link_overrides_missing_original_link(self):
        verified = 'https://pubmed.ncbi.nlm.nih.gov/12345678/'
        row, citation, eligible = research_candidate(self.input, FakeWorkbook(verified))
        self.assertEqual(row, 17)
        self.assertTrue(eligible)
        self.assertEqual(citation['url'], verified)
        self.assertTrue(citation['source_url_verified'])
        # The original blue citation remains unchanged.
        self.assertEqual(self.input['url'], 'NR')
        self.assertEqual(self.input['citation'], '2024 POQI consensus')

    def test_verified_doi_link_is_researchable_even_without_original_identifiers(self):
        row, citation, eligible = research_candidate(
            self.input, FakeWorkbook('https://doi.org/10.1234/example'))
        self.assertTrue(eligible)
        self.assertEqual(citation['doi'], 'NR')

    def test_blank_and_not_found_reviewer_links_are_not_accepted(self):
        for empty in ('', 'NR', 'NOT FOUND', None):
            with self.subTest(value=empty):
                self.assertFalse(research_candidate(self.input, FakeWorkbook(empty))[2])


class CacheAuditTests(TestCase):
    def test_cached_api_response_is_recorded_as_cache_hit_not_network_success(self):
        url = 'https://api.crossref.org/works/10.1234/synthetic'
        with TemporaryDirectory() as tmp:
            client = Bibliography({}, Path(tmp), offline=True)
            key = hashlib.sha256(json.dumps(
                [url, None, 'application/json'], sort_keys=True).encode()).hexdigest()
            (Path(tmp) / (key[:32] + '.json')).write_text(
                json.dumps({'message': {'title': ['Synthetic article']}}),
                encoding='utf-8',
            )
            with patch.object(client.s, 'get', side_effect=AssertionError('network accessed')):
                response = client.fetch_json(url)
            self.assertEqual(response['message']['title'], ['Synthetic article'])
            self.assertEqual(client.events, [{'url': url, 'status': 'cache_hit'}])

    def test_missing_cached_response_does_not_claim_cache_reuse(self):
        with TemporaryDirectory() as tmp:
            client = Bibliography({}, Path(tmp), offline=True)
            self.assertIsNone(client.fetch_json('https://api.crossref.org/works/10.1234/absent'))
            self.assertFalse(any(e['status'] in ('ok', 'cache_hit') for e in client.events))
