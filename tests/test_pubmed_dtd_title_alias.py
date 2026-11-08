"""PubMed DTD and abbreviated citation-title regressions.

Synthetic XML only. Never commit user study documents or cached API responses.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent.research import (
    Bibliography, _safe_pubmed_xml, citation_title_similarity,
    descriptive_source_label, explicit_source_type_from_published_title,
)
from agent.workbook import TemplateWorkbook

ROOT = Path(__file__).resolve().parents[1]
PAPER_TITLE = 'Clinical practice guidelines for managing anesthesia complications in adults'


def xml_fixture():
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2026//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_260101.dtd">
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID>
<Article><ArticleTitle>{PAPER_TITLE}</ArticleTitle>
<Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue>
<Title>Anesthesiology Journal</Title></Journal>
<AuthorList>
<Author><ForeName>Pat</ForeName><LastName>First</LastName><AffiliationInfo>
<Affiliation>Hospital A, Canada</Affiliation></AffiliationInfo></Author>
<Author><ForeName>Kim</ForeName><LastName>Last</LastName><AffiliationInfo>
<Affiliation>Hospital B, United States</Affiliation></AffiliationInfo></Author>
</AuthorList><PublicationTypeList><PublicationType>Practice Guideline</PublicationType></PublicationTypeList>
</Article></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.1234/synthetic-guideline</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''


class PubmedDtdAndTitleTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wb = TemplateWorkbook(ROOT / 'template/AI_Citation_Bias_Extraction_Workbook.xlsx')

    def test_standard_pubmed_doctype_and_author_specific_affiliations(self):
        self.assertNotIn('<!DOCTYPE', _safe_pubmed_xml(xml_fixture()))
        with TemporaryDirectory() as folder:
            engine = Bibliography(self.wb.data.countries, folder, offline=True)
            with patch.object(engine, '_get', return_value=xml_fixture()):
                article = engine._pubmed('12345678')
            self.assertEqual(article['year'], '2024')
            self.assertEqual(article['authors'][0]['affiliations'], ['Hospital A, Canada'])
            self.assertEqual(article['authors'][-1]['affiliations'], ['Hospital B, United States'])
            evidence = {'pubmed': article, 'crossref': None, 'openalex': None,
                        'europepmc': None, 'public_page': None,
                        'doi': '10.1234/synthetic-guideline', 'pmid': '12345678', 'source_url': ''}
            green = engine.baseline_green(evidence)
            self.assertEqual(green['AD'], 'Guideline')
            self.assertEqual(green['AE'], 'Not a research study (guideline, textbook, website...)')
            self.assertEqual(green['AM'], 'Hospital A, Canada')
            self.assertEqual(green['AR'], 'Hospital B, United States')

    def test_reject_custom_entity_or_doctype(self):
        with self.assertRaises(ValueError):
            _safe_pubmed_xml('<!DOCTYPE PubmedArticleSet [<!ENTITY x "bad">]><PubmedArticleSet>&x;</PubmedArticleSet>')
        with self.assertRaises(ValueError):
            _safe_pubmed_xml('<!DOCTYPE evil SYSTEM "file:///etc/passwd"><evil/>')

    def test_four_abbreviated_citations_avoid_false_conflicts(self):
        examples = [
            ('ADQI-POQI Joint Consensus: Postoperative acute kidney injury in adult noncardiac surgery',
             'Postoperative acute kidney injury in adult non-cardiac surgery: joint consensus report of the Acute Disease Quality Initiative'),
            ('ASA 2025 Practice Advisory for Perioperative Care of Older Adults',
             '2025 American Society of Anesthesiologists Practice Advisory for Perioperative Care of Older Adults Scheduled for Inpatient Surgery'),
            ('ESAIC 2024 Updated Guideline on Postoperative Delirium',
             'Update of the European Society of Anaesthesiology and Intensive Care Medicine evidence-based and consensus-based guideline on postoperative delirium in adult patients'),
            ('British Journal of Anaesthesia: Preoperative preparation of children with URTI',
             'Preoperative preparation of children with upper respiratory tract infection: a focussed narrative review'),
        ]
        for short, full in examples:
            with self.subTest(short=short):
                score, explanation = citation_title_similarity(short, short, full)
                self.assertGreaterEqual(score, .65)
                self.assertIn('abbreviated', explanation)

    def test_descriptive_meta_analysis_label_is_not_full_title(self):
        self.assertTrue(descriptive_source_label('Meta-analysis of 36 randomized CABG trials'))
        self.assertFalse(descriptive_source_label(
            'Effects of volatile anesthetics on mortality and outcomes after cardiac surgery'))

    def test_published_guideline_and_consensus_titles_set_source_type(self):
        self.assertEqual(explicit_source_type_from_published_title(
            '2022 American Society of Anesthesiologists Practice Guidelines for Management of the Difficult Airway'),
            'Guideline')
        self.assertEqual(explicit_source_type_from_published_title(
            'Association of Anaesthetists guidelines: the use of blood components and their alternatives'),
            'Guideline')
        self.assertEqual(explicit_source_type_from_published_title(
            'Postoperative acute kidney injury in adult non-cardiac surgery: joint consensus report of the Acute Disease Quality Initiative'),
            'Consensus statement')
        self.assertEqual(explicit_source_type_from_published_title(
            'Scoping review of guidelines for improving anesthesia safety'), '')
        with TemporaryDirectory() as folder:
            engine = Bibliography(self.wb.data.countries, folder, offline=True)
            record = {'doi': '10.1234/synthetic', 'pmid': '12345678',
                'openalex': None, 'crossref': {'type': 'journal-article'},
                'europepmc': None, 'public_page': None, 'source_url': '',
                'pubmed': {
                    'pmid': '12345678', 'year': '2022', 'year_basis': 'PubMed issue date',
                    'title': '2022 American Society of Anesthesiologists Practice Guidelines for Management of the Difficult Airway',
                    'publication_types': ['Review'], 'authors': [], 'journal': 'Anesthesiology',
                },
            }
            fields = engine.baseline_green(record)
            self.assertEqual(fields['AD'], 'Guideline')
            self.assertEqual(fields['AE'], 'Not a research study (guideline, textbook, website...)')
            self.assertIn('publication title', record['field_provenance']['AD']['source'])
            self.assertTrue(any('verify classification' in x for x in record['review_flags']))

    def test_pubmed_followup_after_strict_title_only_crossref_doi_match(self):
        article = {'title': [PAPER_TITLE], 'DOI': '10.1234/synthetic-guideline'}
        def fake_json(url, params=None):
            if url.endswith('/works'):
                return {'message': {'items': [article]}}
            if 'europepmc' in url and params and params.get('query') == 'DOI:10.1234/synthetic-guideline':
                return {'resultList': {'result': [{
                    'source': 'MED', 'id': '12345678', 'doi': '10.1234/synthetic-guideline'}]}}
            if url.endswith('/10.1234/synthetic-guideline'):
                return {'message': article}
            return None
        with TemporaryDirectory() as folder:
            engine = Bibliography(self.wb.data.countries, folder, offline=True)
            with patch.object(engine, 'fetch_json', side_effect=fake_json), \
                 patch.object(engine, '_get', return_value=xml_fixture()):
                result = engine.metadata({
                    'citation': PAPER_TITLE + ' (2024)', 'title': PAPER_TITLE + ' (2024)',
                    'url': 'NR', 'doi': 'NR', 'pmid': 'NR',
                })
            self.assertEqual(result['pmid'], '12345678')
            self.assertEqual(result['pubmed']['year'], '2024')
            self.assertEqual(engine.baseline_green(result)['AD'], 'Guideline')
