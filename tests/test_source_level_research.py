"""Source identity grouping preserves occurrence counts and review provenance."""
from unittest import TestCase
from run_agent import _source_research_summary, SOURCE_RESEARCH_FIELDS


class SourceLevelResearchTests(TestCase):
    def test_repeated_web_badges_retain_all_thirteen_occurrences(self):
        rows=[{'tool':'CLG','question':'Q01','order':i,'citation':'nysora',
               'url':'https://nysora.com/?p=68145','source_context':'inline_link'}
              for i in range(1,14)]
        proposals=[{'tool':'CLG','question':'Q01','order':i,
                    'has_metadata':True,'informative_fields':0,
                    'written_to_workbook':False,'identifiers':{},'review_flags':[]}
                   for i in range(1,14)]
        grouped=_source_research_summary(rows, proposals)
        self.assertEqual(len(grouped),1)
        self.assertEqual(grouped[0]['citation_occurrences'],13)
        self.assertEqual(grouped[0]['research_attempts'],13)
        self.assertEqual(grouped[0]['metadata_occurrences'],13)
        self.assertEqual(grouped[0]['green_written_occurrences'],0)
        self.assertEqual(grouped[0]['review_priority'],'High')
        self.assertTrue(set(SOURCE_RESEARCH_FIELDS).issubset(set(grouped[0])))

    def test_aliases_same_pmc_source_but_both_occurrences_remain(self):
        rows=[{'tool':'CLG','question':'Q11','order':1,'citation':'Jiao paper',
               'url':'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6818786/',
               'source_context':'inline_link'},
              {'tool':'CLG','question':'Q11','order':2,'citation':'Jiao 2019',
               'url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC6818786/',
               'source_context':'bibliography'}]
        proposals=[{'tool':'CLG','question':'Q11','order':i,
                    'has_metadata':True,'informative_fields':15,
                    'written_to_workbook':True,'review_flags':[],
                    'fields':{'Z':'Jiao 2019 meta-analysis'},
                    'identifiers':{'doi':'10.1371/journal.pone.0224562','pmid':'31661512'}}
                   for i in (1,2)]
        grouped=_source_research_summary(rows,proposals)
        self.assertEqual(len(grouped),1)
        self.assertEqual(grouped[0]['citation_occurrences'],2)
        self.assertEqual(grouped[0]['green_written_occurrences'],2)
        self.assertEqual(grouped[0]['contexts'],'inline_link | bibliography')

    def test_conflicting_resolved_dois_in_one_identity_flags_review(self):
        rows=[{'tool':'CLG','question':'Q01','order':i,'citation':'nysora',
               'url':'https://nysora.com/?p=68145'} for i in (1,2)]
        proposed=[{'tool':'CLG','question':'Q01','order':i,
                   'informative_fields':8,'written_to_workbook':True,
                   'has_metadata':True,'review_flags':[], 'fields':{'Z':'title'},
                   'identifiers':{'doi':doi}}
                  for i,doi in [(1,'10.1234/a'),(2,'10.1234/b')]]
        grouped=_source_research_summary(rows,proposed)
        self.assertEqual(grouped[0]['review_priority'],'High')
        self.assertIn('Conflicting',grouped[0]['review_notes'])
