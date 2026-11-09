"""Potential source aliases must be reviewer-only, not silently deduplicated."""
from unittest import TestCase

from run_agent import _source_alias_review, SOURCE_ALIAS_FIELDS


class PossibleSourceAliasTests(TestCase):
    def test_language_variants_with_same_proposed_title_are_flagged(self):
        title = 'Tracheal intubation techniques in head and neck surgery: navigating challenges and enhancing airway safety'
        rows = [
            {'tool':'DSK','question':'Q05','order':1,'citation':'3',
             'url':'https://nysora.com/zh-CN/education-news/intubation/','title':'NR'},
            {'tool':'DSK','question':'Q05','order':2,'citation':'3',
             'url':'https://nysora.com/education-news/intubation/','title':'NR'},
            {'tool':'DSK','question':'Q05','order':3,'citation':'3',
             'url':'https://nysora.com/zh-CN/education-news/intubation/','title':'NR'},
        ]
        proposals = [
            {'tool':'DSK','question':'Q05','order':i,
             'fields':{'Z':title},'field_provenance':{'Z':{'source':'Original linked webpage title'}}}
            for i in (1,2,3)
        ]
        found = _source_alias_review(rows, proposals)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['citation_occurrences'], 3)
        self.assertEqual(found[0]['distinct_linked_source_identities'], 2)
        self.assertIn('Keep all as-cited occurrences unchanged', found[0]['review_action'])
        self.assertEqual([x['order'] for x in rows],[1,2,3])
        self.assertTrue(set(SOURCE_ALIAS_FIELDS).issubset(set(found[0])))

    def test_no_merging_across_questions_or_unknown_title(self):
        rows = [
            {'tool':'DSK','question':'Q05','order':1,'citation':'3','url':'https://one.org/a'},
            {'tool':'DSK','question':'Q12','order':1,'citation':'3','url':'https://two.org/a'},
        ]
        proposals=[
            {'tool':x['tool'],'question':x['question'],'order':1,
             'fields':{'Z':'Long identical title for two different clinical reports'}}
            for x in rows
        ]
        self.assertEqual(_source_alias_review(rows, proposals), [])
        for p in proposals:p['fields']['Z']='NOT FOUND'
        self.assertEqual(_source_alias_review(rows, proposals), [])
