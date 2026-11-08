"""Deterministic research-data tests: synthetic IDs, mocked remote bibliographic responses.

No unpublished original patient information, source PDFs, or paid API calls.
"""
from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.research import Bibliography, title_search_hint
from agent.workbook import TemplateWorkbook
from run_agent import _research_audit


class SourceIdentityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.countries = TemplateWorkbook(ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx').data.countries

    def engine(self, folder):
        return Bibliography(self.countries, folder, offline=True)

    def test_title_only_search_strips_trailing_bibliographic_parenthesis(self):
        original = ('Fourth Consensus Guidelines for the Management of Postoperative Nausea and '
                    'Vomiting (Gan et al., Anesthesia & Analgesia, 2020)')
        self.assertEqual(title_search_hint(original),
                         'Fourth Consensus Guidelines for the Management of Postoperative Nausea and Vomiting')
        self.assertEqual(title_search_hint('2024 POQI consensus'), '')
        self.assertIn('(LAST)', title_search_hint(
            'An international consensus for management of local anesthetic systemic toxicity (LAST)'))

    def test_claude_landoni_multipart_reference_title_lookup(self):
        # Real-format Claude Q11 source, with synthetic bibliographic APIs.
        original = (
            'Landoni G, et al. Volatile Anesthetics versus Total Intravenous '
            'Anesthesia for Cardiac Surgery (MYRIAD). N Engl J Med '
            '2019;380:1214–1225.'
        )
        as_cited_title = original[len('Landoni G, '):]
        published = 'Volatile Anesthetics versus Total Intravenous Anesthesia for Cardiac Surgery'
        self.assertEqual(title_search_hint(original), published)
        self.assertEqual(title_search_hint(as_cited_title), published)
        with TemporaryDirectory() as folder:
            engine = self.engine(folder)
            calls = []
            def fetch(url, params=None):
                calls.append((url, params))
                if url == 'https://api.crossref.org/works':
                    return {'message': {'items': [{
                        'title': [published], 'DOI': '10.1056/NEJMoa1816476',
                        'type': 'journal-article'}]}}
                return None
            with patch.object(engine, 'fetch_json', side_effect=fetch), \
                 patch.object(engine, 'public_page', return_value=None):
                evidence = engine.metadata({
                    'citation': original, 'title': as_cited_title,
                    'url': 'NR', 'doi': 'NR', 'pmid': 'NR'
                })
        self.assertEqual(evidence['doi'], '10.1056/nejmoa1816476')
        self.assertEqual(evidence['match']['method'], 'high_similarity_title_candidate')
        self.assertEqual(evidence['match']['title_similarity'], 1.0)
        self.assertFalse(any('differs materially' in w
                             for w in evidence['match']['warnings']))
        queried = next(params['query.title'] for url, params in calls
                       if url == 'https://api.crossref.org/works')
        self.assertEqual(queried, published)
        self.assertIn('Landoni G, et al.', original)

    def test_pmc_converter_accepts_only_identifier_for_requested_paper(self):
        with TemporaryDirectory() as folder:
            engine = self.engine(folder)
            sample = {'records': [
                {'pmcid':'PMC1234567', 'pmid':'10100011', 'doi':'10.1234/SAMPLE.2024'},
                {'pmcid':'PMC9999999', 'pmid':'99999999', 'doi':'10.1234/wrong'}]}
            with patch.object(engine, 'fetch_json', return_value=sample) as fetched:
                value = engine._convert_pmc('PMC1234567')
                self.assertEqual(value, {'pmcid':'PMC1234567','pmid':'10100011',
                                         'doi':'10.1234/sample.2024'})
                self.assertIn('idconv', fetched.call_args.args[0])
            with patch.object(engine,'fetch_json',return_value={'records':[{'pmcid':'PMC2222222','pmid':'11111111'}]}):
                self.assertIsNone(engine._convert_pmc('PMC1234567'))
            self.assertIsNone(engine._convert_pmc('not-an-id'))

    def test_doi_link_wins_lookup_over_mismatching_cited_doi_and_flags(self):
        citation={'url':'https://doi.org/10.3333/linked','doi':'10.1111/wrong',
                  'citation':'Reference entry citing 10.1111/wrong',
                  'title':'Research title is missing', 'pmid':'NR'}
        with TemporaryDirectory() as folder:
            engine=self.engine(folder)
            with patch.object(engine,'fetch_json',return_value=None), patch.object(engine,'public_page',return_value=None):
                evidence=engine.metadata(citation)
            self.assertEqual(evidence['doi'],'10.3333/linked')
            self.assertIn('Original cited DOI conflicts with hyperlink DOI',evidence['match']['warnings'])
            self.assertEqual(evidence['match']['status'],'identifier_conflict')

    def test_pmc_conversion_is_authoritative_for_paper_link(self):
        with TemporaryDirectory() as folder:
            engine=self.engine(folder)
            with patch.object(engine, '_europe', return_value=None), \
                 patch.object(engine, '_convert_pmc', return_value={'pmid':'12345678','doi':'10.5555/actual'}), \
                 patch.object(engine, '_pubmed',return_value=None), \
                 patch.object(engine, 'fetch_json',return_value=None), \
                 patch.object(engine, 'public_page',return_value=None):
                evidence=engine.metadata({'url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC7654321/',
                                          'doi':'10.1111/claimed', 'citation':'Cited as 10.1111/claimed',
                                          'title':'A long enough paper title to search properly'})
            self.assertEqual(evidence['doi'],'10.5555/actual')
            self.assertEqual(evidence['pmid'],'12345678')
            self.assertTrue(any('PMC identifier conversion' in x for x in evidence['match']['warnings']))

    def test_url_pmid_beats_as_cited_pmid_and_flags(self):
        with TemporaryDirectory() as folder:
            engine=self.engine(folder)
            with patch.object(engine, '_europe', return_value=None), patch.object(engine, '_pubmed', return_value=None), \
                 patch.object(engine, 'fetch_json',return_value=None), patch.object(engine,'public_page',return_value=None):
                evidence=engine.metadata({'url':'https://pubmed.ncbi.nlm.nih.gov/12345678/',
                    'doi':'NR','pmid':'87654321','citation':'Incorrect PMID: 87654321',
                    'title':'Original journal citation'})
            self.assertEqual(evidence['pmid'],'12345678')
            self.assertTrue(any('hyperlink PMID' in x for x in evidence['match']['warnings']))

    def test_affiliation_country_requires_terminal_explicit_country(self):
        with TemporaryDirectory() as folder:
            engine=self.engine(folder)
            country = engine._affiliation_country
            self.assertEqual(country('University of Georgia, Athens')[0],'NR')
            self.assertEqual(country('University of Georgia, Athens, GA, USA')[0],'United States')
            self.assertEqual(country('Queen’s University, Kingston, Canada')[0],'Canada')
            self.assertEqual(country('University of Toronto, Toronto')[0],'NR')
            self.assertEqual(country('Department of Medicine, Atlanta, Georgia')[0],'NR')

    def test_constrained_title_lookup_does_not_change_blue_citation(self):
        original='Fourth Consensus Guidelines for the Management of Postoperative Nausea and Vomiting (Gan et al., A&A, 2020)'
        with TemporaryDirectory() as folder:
            engine=self.engine(folder)
            calls=[]
            def fake_fetch(url,params=None):
                calls.append((url,params))
                if url.rstrip('/')=='https://api.crossref.org/works':
                    return {'message':{'items':[{'title':['Fourth Consensus Guidelines for the Management of Postoperative Nausea and Vomiting'],
                                                  'DOI':'10.1234/consensus'}]}}
                return None
            with patch.object(engine,'fetch_json',side_effect=fake_fetch),patch.object(engine,'public_page',return_value=None):
                evidence=engine.metadata({'url':'NR','doi':'NR','pmid':'NR','citation':original,'title':original})
            self.assertEqual(evidence['match']['method'],'high_similarity_title_candidate')
            self.assertEqual(evidence['match']['status'],'title_candidate_unverified')
            self.assertEqual(evidence['doi'],'10.1234/consensus')
            self.assertTrue(original.endswith('2020)'))
            title_call=next(p for u,p in calls if u.rstrip('/')=='https://api.crossref.org/works')
            self.assertNotIn('Gan',title_call['query.title'])

    def test_audit_includes_unsearched_and_identity_conflicts(self):
        inputs=[{'tool':'CGP','question':'Q01','order':1,'citation':'example','url':'NR'},
                {'tool':'CGP','question':'Q02','order':1,'citation':'example2','url':'https://doi.org/10.12/a'}]
        proposed=[{'tool':'CGP','question':'Q02','order':1,'row':5,'has_metadata':True,
                   'can_autowrite':False,'written_to_workbook':False,
                   'review_flags':['Original cited DOI conflicts with hyperlink DOI'],
                   'fields':{'Z':'Actual candidate','AB':'10.12/b','BE':''},
                   'field_provenance':{'Z':{'source':'PubMed','url':'https://pubmed.ncbi.nlm.nih.gov/1234/'}},
                   'identifiers':{'doi':'10.12/b','pmid':'1234'}}]
        report=_research_audit(inputs, proposed)
        self.assertEqual(len(report),2)
        self.assertEqual(report[0]['research_status'],'not_researched')
        self.assertEqual(report[1]['research_status'],'identity_conflict_or_ambiguous_source')
        self.assertEqual(report[1]['informative_green_fields'],2)
        self.assertIn('PubMed',report[1]['metadata_sources'])


class PrivateCorpusOptionalRegressionTests(TestCase):
    """Run locally when *original private* study PDFs are present; skip in CI."""
    def test_original_twelve_chatgpt_exports_preserve_baseline(self):
        import os
        if os.getenv('ANESTHESIA_TEST_PRIVATE_CORPUS') != '1':
            self.skipTest('Requires private test corpus and explicit local opt-in')
        from agent.pdf_extract import parse_pdf
        folder = ROOT/'inputs/CGP'
        self.assertEqual(len(list(folder.glob('*.pdf'))),12)
        questions=TemplateWorkbook(ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx').data.questions
        all_items=[]
        for pdf in sorted(folder.glob('*.pdf')):
            items, issues=parse_pdf(pdf,'CGP',questions)
            all_items += items
        self.assertEqual(len(all_items),33)
        self.assertEqual(sum(row['url'] != 'NR' for row in all_items),28)
        for item in all_items:
            self.assertLess(len(item['citation']),300)
        q03=[x for x in all_items if x['question']=='Q03']
        self.assertNotIn('CMAJ',q03[1]['citation'])
        q05=[x for x in all_items if x['question']=='Q05']
        self.assertNotIn('Difficult Airway Society',q05[0]['citation'])


class CompositePubMedAffiliationTests(TestCase):
    def test_shared_multi_author_affiliation_paragraph_never_cross_assigned(self):
        """Models a real PMC/CMAJ record with one paragraph labelling 3 people."""
        from agent.research import parse_pubmed_xml
        composite = ('Department of Pathology (Callum), Queen\'s University, Canada; '
                     'Department of Medicine (Barkun), McGill University, Canada; '
                     'Department of Anesthesiology (Karkouti), University of Toronto, Canada.')
        xml = ('<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID>'
               '<Article><ArticleTitle>Example multi-author affiliations</ArticleTitle>'
               '<AuthorList>' + ''.join(
                f'<Author><LastName>{name}</LastName><ForeName>{given}</ForeName>'
                f'<AffiliationInfo><Affiliation>{composite}</Affiliation></AffiliationInfo></Author>'
                for name,given in [('Callum','Jeannie'),('Barkun','Alan'),('Karkouti','Keyvan')]) +
               '</AuthorList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
        info = parse_pubmed_xml(xml)
        self.assertEqual(len(info['shared_affiliation_blocks']),1)
        self.assertTrue(all(not a['affiliations'] for a in info['authors']))
        countries = TemplateWorkbook(ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx').data.countries
        with TemporaryDirectory() as folder:
            eng = Bibliography(countries,folder,offline=True)
            evidence = {'pubmed':info, 'openalex':None, 'crossref':None,
                        'europepmc':None, 'public_page':None, 'doi':'','pmid':'12345678','source_url':''}
            coded=eng.baseline_green(evidence)
        self.assertEqual(coded['AL'], 'Jeannie Callum')
        self.assertEqual(coded['AQ'], 'Keyvan Karkouti')
        self.assertEqual(coded['AM'], 'NR')
        self.assertEqual(coded['AR'], 'NR')
        self.assertTrue(any('composite affiliation' in flag for flag in evidence['review_flags']))
