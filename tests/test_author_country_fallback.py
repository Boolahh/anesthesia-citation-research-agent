"""Strict author-country fallbacks for the study's geographic primary outcome."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from agent.research import Bibliography, _openalex_author_country
from agent.workbook import TemplateWorkbook

ROOT=Path(__file__).resolve().parents[1]


class OpenAlexCountryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wb=TemplateWorkbook(ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx')

    def paper(self, pm_authors=None, oa_authors=None):
        return {
            'doi': '10.1234/synthetic', 'pmid': '10000001',
            'source_url': 'https://pubmed.ncbi.nlm.nih.gov/10000001/',
            'pubmed': {
                'pmid': '10000001',
                'title': 'Synthetic randomized research study',
                'year': '2025',
                'authors': pm_authors or [],
                'publication_types': ['Journal Article'],
            } if pm_authors is not None else None,
            'openalex': {
                'id': 'https://openalex.org/W999',
                'authorships': oa_authors or [],
            },
            'crossref': None, 'europepmc': None, 'public_page': None,
        }

    @staticmethod
    def indexed(name, *countries):
        return {
            'author': {'display_name': name},
            'countries': list(countries),
            'institutions': [{'country_code': c, 'display_name': 'Ambiguous institution'} for c in countries],
        }

    def test_strict_name_matched_first_last_countries_only(self):
        with TemporaryDirectory() as folder:
            engine=Bibliography(self.wb.data.countries, folder, offline=True)
            evidence=self.paper(
                pm_authors=[
                    {'name':'Ada Researcher','affiliations':[]},
                    {'name':'Eli Last','affiliations':[]},
                ],
                oa_authors=[
                    self.indexed('Ada Researcher','CA'),
                    self.indexed('Eli Last','US'),
                ],
            )
            vals=engine.baseline_green(evidence)
            self.assertEqual(vals['AN'], 'Canada')
            self.assertEqual(vals['AS'], 'United States')
            self.assertNotEqual(vals['AO'], 'NR')
            self.assertNotEqual(vals['AT'], 'NR')
            self.assertEqual(vals['AM'], 'NR')  # Country != institution.
            self.assertEqual(vals['AR'], 'NR')
            self.assertIn('OpenAlex matched author-country',
                          evidence['field_provenance']['AN']['source'])
            self.assertTrue(any('verify before including' in f
                                for f in evidence['review_flags']))

    def test_name_mismatch_does_not_assign_country_by_author_order(self):
        with TemporaryDirectory() as folder:
            engine=Bibliography(self.wb.data.countries, folder, offline=True)
            evidence=self.paper(
                pm_authors=[{'name':'Ada Researcher','affiliations':[]},
                            {'name':'Eli Last','affiliations':[]}],
                oa_authors=[self.indexed('Different Person','CA'),
                            self.indexed('Eli Last','US')],
            )
            vals=engine.baseline_green(evidence)
            self.assertEqual(vals['AN'], 'NR')
            self.assertEqual(vals['AS'], 'United States')

    def test_ambiguous_multiple_countries_are_not_chosen(self):
        with TemporaryDirectory() as folder:
            engine=Bibliography(self.wb.data.countries, folder, offline=True)
            self.assertIsNone(_openalex_author_country(self.indexed('A','GB','CA'),engine.countries))
            evidence=self.paper(
                pm_authors=[{'name':'Ada Researcher','affiliations':[]},
                            {'name':'Eli Last','affiliations':[]}],
                oa_authors=[self.indexed('Ada Researcher','CA','GB'),
                            self.indexed('Eli Last','US')],
            )
            vals=engine.baseline_green(evidence)
            self.assertEqual(vals['AN'], 'NR')
            self.assertEqual(vals['AS'], 'United States')

    def test_author_country_from_pubmed_is_not_overwritten(self):
        with TemporaryDirectory() as folder:
            engine=Bibliography(self.wb.data.countries, folder, offline=True)
            evidence=self.paper(
                pm_authors=[{'name':'Ada Researcher','affiliations':['Department X, Canada']},
                            {'name':'Eli Last','affiliations':['Department Y, United States']}],
                oa_authors=[self.indexed('Ada Researcher','GB'),
                            self.indexed('Eli Last','US')],
            )
            vals=engine.baseline_green(evidence)
            self.assertEqual(vals['AN'], 'Canada')
            self.assertEqual(vals['AS'], 'United States')
            self.assertTrue(any('conflicting PubMed/OpenAlex' in f
                                for f in evidence['review_flags']))

    def test_oa_only_author_country_proposes_without_affiliation(self):
        with TemporaryDirectory() as folder:
            engine=Bibliography(self.wb.data.countries, folder, offline=True)
            evidence=self.paper(
                pm_authors=None,
                oa_authors=[self.indexed('Ada Researcher','CA'),
                            self.indexed('Eli Last','GB')],
            )
            vals=engine.baseline_green(evidence)
            self.assertEqual(vals['AN'], 'Canada')
            self.assertEqual(vals['AS'], 'United Kingdom')
            self.assertEqual(vals['AM'], 'NR')
            self.assertEqual(vals['AR'], 'NR')

    def test_group_author_is_not_assigned_human_country(self):
        with TemporaryDirectory() as folder:
            engine=Bibliography(self.wb.data.countries, folder, offline=True)
            evidence=self.paper(
                pm_authors=[{'name':'Ada Researcher','affiliations':[]},
                            {'name':'Committee','group':True,'affiliations':[]}],
                oa_authors=[self.indexed('Ada Researcher','CA'),
                            self.indexed('Committee','US')],
            )
            vals=engine.baseline_green(evidence)
            self.assertEqual(vals['AN'], 'Canada')
            self.assertEqual(vals['AS'], 'NR')
