"""Distinct country-candidate and access-remediation reporting never modifies citations."""
from unittest import TestCase
from agent.source_coverage import (
    geography_candidate_sources, source_access_review,
    GEO_SOURCE_FIELDS, ACCESS_REVIEW_FIELDS,
)


class CoverageReportsTests(TestCase):
    def rows(self):
        return [
            {'tool': 'DSK','question':'Q02','order':1,'citation':'6',
             'url':'https://pubmed.ncbi.nlm.nih.gov/38839472/'},
            {'tool': 'DSK','question':'Q02','order':2,'citation':'6',
             'url':'https://pesquisa.bvsalud.org/portal/resource/p1/mdl-38839472'},
            {'tool': 'DSK','question':'Q03','order':1,'citation':'2',
             'url':'https://example.org/documents/bleeding-guideline.pdf'},
            {'tool': 'DSK','question':'Q03','order':2,'citation':'2',
             'url':'https://example.org/documents/bleeding-guideline.pdf'},
        ]

    def proposals(self):
        return [
            {'tool':'DSK','question':'Q02','order':num,
             'written_to_workbook': True,
             'fields':{'AN':'Canada','AL':'Clinician Example','Z':'Synthetic article',
                       'AB':'10.9876/clinical','AC':'38839472'},
             'identifiers':{'doi':'10.9876/clinical','pmid':'38839472'},
             'field_provenance':{'AN':{'source':'PubMed author-specific AffiliationInfo',
                                    'url':'https://pubmed.ncbi.nlm.nih.gov/38839472/'}}}
            for num in (1,2)
        ]+[
            {'tool':'DSK','question':'Q03','order':num,
             'written_to_workbook':False, 'has_metadata':False,
             'fields':{'Z':'NOT FOUND'},'identifiers':{},
             'match':{'status':'review_required'},
             'source_document':{'status':'read',
                                'title_hint':'Massiv blödning - Anestesirutin'}}
            for num in (1,2)
        ]

    def test_two_source_links_same_doi_count_once_without_deleting_occurrences(self):
        rows = self.rows()
        result = geography_candidate_sources(rows, self.proposals())
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['citation_occurrences'],2)
        self.assertEqual(result[0]['candidate_identity'],'doi:10.9876/clinical')
        self.assertEqual(result[0]['first_author_countries'],'Canada')
        self.assertEqual(result[0]['country_evidence_class'],
                         'PubMed author-specific affiliation')
        self.assertEqual(len(rows),4)
        self.assertTrue(set(GEO_SOURCE_FIELDS).issubset(result[0].keys()))

    def test_conflicting_country_evidence_is_flagged_not_overwritten(self):
        p = self.proposals()
        p[1]['fields']['AN']='United States'
        result=geography_candidate_sources(self.rows(), p)
        self.assertEqual(result[0]['country_evidence_class'],'conflicting')
        self.assertEqual(result[0]['review_priority'],'High')
        self.assertIn('Canada',result[0]['first_author_countries'])
        self.assertIn('United States',result[0]['first_author_countries'])

    def test_distinct_unresolved_pdf_grouped_as_one_action(self):
        result=source_access_review(self.rows(), self.proposals())
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['source_access_category'],
                         'downloadable_document_or_pdf')
        self.assertEqual(result[0]['citation_occurrences'],2)
        self.assertEqual(result[0]['source_document_title_hint'],
                         'Massiv blödning - Anestesirutin')
        self.assertTrue(set(ACCESS_REVIEW_FIELDS).issubset(result[0].keys()))

    def test_do_not_classify_unresearched_blue_only_sources_as_research_failure(self):
        self.assertEqual(source_access_review(self.rows(), []),[])
        self.assertEqual(geography_candidate_sources(self.rows(),[]),[])

    def test_non_source_search_results_get_review_only(self):
        rows=[{'tool':'DSK','question':'Q06','order':1,'citation':'12',
               'url':'https://pubmed.ncbi.nlm.nih.gov/?term=anesthesia'}]
        p=[{'tool':'DSK','question':'Q06','order':1,
            'written_to_workbook':False,'fields':{},
            'match':{'status':'non_source_search_results'}}]
        result=source_access_review(rows,p)
        self.assertEqual(result[0]['source_access_category'],
                         'search_results_not_single_publication')
        self.assertEqual(result[0]['priority'],'High')
