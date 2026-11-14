"""A visible source badge is not the same as an independent paper.

These synthetic records mirror the previously observed Claude PONV PDF:
22 linked NYSORA badges and two explicit bibliography entries.
"""
from unittest import TestCase

from agent.citation_census import citation_census_by_question, CITATION_CENSUS_FIELDS


class CitationCountReconciliationTests(TestCase):
    def test_claude_persistent_source_badges_versus_reference_list(self):
        rows = [
            {'tool':'CLG','question':'Q01','order':i,
             'source_context':'inline_link','citation':'nysora',
             'url':'https://nysora.com/?p=68145',
             'source_file':'Postoperative nausea prevention strategies - Claude.pdf'}
            for i in range(1, 23)
        ]
        rows.extend([
            {'tool':'CLG','question':'Q01','order':23,
             'citation':'Fifth consensus guideline - NYSORA summary',
             'url':'https://nysora.com/education-news/fifth-consensus-guidelines-reshape-prevention-and-treatment-of-postoperative-nausea-and-vomiting/',
             'source_context':'bibliography','source_file':rows[0]['source_file']},
            {'tool':'CLG','question':'Q01','order':24,
             'citation':'Fourth consensus guideline - ESAIC',
             'url':'https://esaic.org/?p=3530',
             'source_context':'bibliography','source_file':rows[0]['source_file']},
        ])
        counts=citation_census_by_question(rows)
        self.assertEqual(len(counts),1)
        row=counts[0]
        self.assertEqual(row['citation_occurrences'],24)
        self.assertEqual(row['distinct_citation_identities'],3)
        self.assertEqual(row['distinct_linked_source_identities'],3)
        self.assertEqual(row['repeat_occurrences'],21)
        self.assertEqual(row['inline_link_occurrences'],22)
        self.assertEqual(row['bibliography_entries'],2)
        self.assertEqual(row['bibliography_distinct_sources'],2)
        self.assertIn('repeatedly',row['review_note'])
        self.assertTrue(set(CITATION_CENSUS_FIELDS).issubset(row.keys()))

    def test_same_link_in_two_questions_is_counted_separately(self):
        source='https://pubmed.ncbi.nlm.nih.gov/38839472/'
        rows=[
            {'tool':'CLG','question':'Q01','order':1,
             'citation':'reference','url':source,'source_context':'bibliography'},
            {'tool':'CLG','question':'Q02','order':1,
             'citation':'reference','url':source,'source_context':'bibliography'},
        ]
        census=citation_census_by_question(rows)
        self.assertEqual(len(census),2)
        self.assertEqual([x['distinct_linked_source_identities'] for x in census],[1,1])

    def test_chatgpt_pdf_with_no_clickable_source_urls_is_not_silent_success(self):
        record={'tool':'CGP','question':'Q01','order':1,
                'citation':'Fourth Consensus Guidelines for PONV',
                'url':'NR','source_context':'named_source_mention'}
        rows=citation_census_by_question([record])
        self.assertEqual(rows[0]['citation_occurrences'],1)
        self.assertEqual(rows[0]['distinct_linked_source_identities'],0)
        self.assertEqual(rows[0]['unlinked_occurrences'],1)
        self.assertIn('lacks linked source URLs',rows[0]['review_note'])

    def test_zero_citation_pdf_requires_review_not_assumed_zero(self):
        rows=citation_census_by_question([],[
            {'tool':'CGP','question':'Q09','file':'GPT_export.pdf','citations':0}
        ])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['citation_occurrences'],0)
        self.assertIn('before treating this as zero',rows[0]['review_note'])
        self.assertEqual(rows[0]['pdf_files'],'GPT_export.pdf')

    def test_no_false_cross_provider_merging(self):
        same_url='https://example.org/source'
        items=[
            {'tool':'CLG','question':'Q01','order':1,'url':same_url},
            {'tool':'CGP','question':'Q01','order':1,'url':same_url},
        ]
        result=citation_census_by_question(items)
        self.assertEqual([x['tool'] for x in result],['CGP','CLG'])
        self.assertEqual(sum(x['citation_occurrences'] for x in result),2)
