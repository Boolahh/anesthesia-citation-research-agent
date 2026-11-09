"""Strict indexed-record recovery from known alternate PubMed locator URLs."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent.research import Bibliography, pubmed_id_from_source_link


class AlternatePubMedSourceLinkTests(TestCase):
    def test_known_record_hosts_and_paths(self):
        sources = [
            ('https://pubmed.ncbi.nlm.nih.gov/38870081/#1',
             '38870081', 'official PubMed record link'),
            ('https://dev.europepmc.org/article/MED/38987101',
             '38987101', 'Europe PMC MED record locator'),
            ('https://pesquisa.bvsalud.org/odontologia/resource/pt/mdl-33191042',
             '33191042', 'BVS MEDLINE index locator'),
            ('https://pesquisa.bvsalud.org/portal/resource/p1/mdl-38839472',
             '38839472', 'BVS MEDLINE index locator'),
            ('https://https-pubmed-ncbi-nlm-nih-gov-443.webvpn.ynu.edu.cn/38870081/#1',
             '38870081', 'institutional PubMed proxy link'),
        ]
        for url, expected_id, basis in sources:
            with self.subTest(url=url):
                self.assertEqual(pubmed_id_from_source_link(url), (expected_id, basis))

    def test_unrecognized_mirrors_and_search_pages_are_not_source_ids(self):
        for url in (
            'https://example.org/portal/resource/p1/mdl-38839472',
            'https://evil.example.org/38870081',
            'https://pubmed.ncbi.nlm.nih.gov/?term=38870081',
            'https://pesquisa.bvsalud.org/portal/search?term=38839472',
            'https://https-pubmed-ncbi-nlm-nih-gov-443.webvpn.example.cn/38870081',
            'https://dev.europepmc.org/search?query=38987101',
        ):
            with self.subTest(url=url):
                self.assertEqual(pubmed_id_from_source_link(url), ('', ''))

    def test_alternate_identifiers_get_independent_pubmed_record_and_warning(self):
        url = 'https://pesquisa.bvsalud.org/odontologia/resource/pt/mdl-33191042'
        with TemporaryDirectory() as tmp:
            engine = Bibliography({}, Path(tmp), offline=True)
            with patch.object(engine, '_europe', return_value=None), \
                 patch.object(engine, '_pubmed', return_value={
                     'pmid': '33191042',
                     'title': 'A Comparison of Volatile Anesthesia and TIVA'
                 }) as lookup, \
                 patch.object(engine, 'fetch_json', return_value=None), \
                 patch.object(engine, 'public_page') as page:
                evidence = engine.metadata({
                    'citation': '7', 'title': 'NR', 'url': url,
                    'pmid': 'NR', 'doi': 'NR'
                })
            lookup.assert_called_once_with('33191042')
            page.assert_not_called()
            self.assertEqual(evidence['pmid'], '33191042')
            self.assertIn('Candidate PMID 33191042 derived from BVS',
                          ' '.join(evidence['match']['warnings']))
            self.assertEqual(evidence['match']['status'], 'review_required')
            self.assertEqual(evidence['source_url'], url)
