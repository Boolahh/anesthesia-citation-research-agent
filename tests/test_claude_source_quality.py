"""Source occurrence versus distinct-work identity regressions, Claude fixtures."""
from unittest import TestCase

from agent.pdf_extract import citation_identity, weak_visible_citation_label
from run_agent import _source_quality_review


class ClaudeSourceQualityTests(TestCase):
    def test_nih_pmc_url_aliases_identify_the_same_publication(self):
        first = {'url':'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6818786/',
                 'citation':'Original citation A'}
        second = {'url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC6818786',
                  'citation':'Jiao et al. 2019 - source B'}
        self.assertEqual(citation_identity(first), 'pmcid:PMC6818786')
        self.assertEqual(citation_identity(first), citation_identity(second))

    def test_wordpress_post_id_remains_significant(self):
        first={'url':'https://nysora.com/?p=68145','citation':'nysora'}
        second={'url':'https://nysora.com/?p=99999','citation':'nysora'}
        self.assertNotEqual(citation_identity(first), citation_identity(second))
        self.assertEqual(citation_identity(first), citation_identity({
            **first, 'url':'https://www.nysora.com/?utm_source=chatgpt.com&p=68145'
        }))

    def test_domain_badge_is_low_information_not_a_title(self):
        for name in ('nysora','nih','scribd','of toxicity','means:'):
            self.assertTrue(weak_visible_citation_label(name, 'https://example.org/paper'),name)
        self.assertFalse(weak_visible_citation_label(
            'Jiao et al., PLoS ONE 2019 - meta-analysis',
            'https://pmc.ncbi.nlm.nih.gov/articles/PMC6818786/'))
        self.assertFalse(weak_visible_citation_label(
            'DAS 2025 guidelines for management of the airway',
            'https://pubmed.ncbi.nlm.nih.gov/41203471/'))

    def test_many_repeated_domain_badges_need_review_not_deletion(self):
        data=[{
            'tool':'CLG','question':'Q01','order':n,'source_file':'Q01 Claude.pdf',
            'source_page':1 if n<=6 else 2, 'citation':'nysora',
            'url':'https://nysora.com/?p=68145','repeat':'Y' if n>1 else 'N',
            'extraction_confidence':'review',
        } for n in range(1,14)]
        out=_source_quality_review(data)
        self.assertEqual(len(out),13)
        self.assertEqual(sum(x['review_priority']=='High' for x in out),13)
        self.assertEqual(out[-1]['occurrences_of_source_in_question'],13)
        self.assertEqual(len({x['source_identity'] for x in out}),1)
        self.assertEqual(out[-1]['repeat_occurrence'],'Y')

    def test_two_pmc_aliases_show_two_occurrences_one_source(self):
        data=[{
            'tool':'CLG','question':'Q11','order':n,'source_file':'Q11.pdf',
            'source_page':n,'citation':'Jiao et al. 2019',
            'url':url,'repeat': 'N' if n==1 else 'Y',
            'extraction_confidence':'high'
        } for n,url in [
            (1,'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6818786/'),
            (2,'https://pmc.ncbi.nlm.nih.gov/articles/PMC6818786')]]
        items=_source_quality_review(data)
        self.assertEqual(items[0]['source_identity'],items[1]['source_identity'])
        self.assertEqual([x['occurrences_of_source_in_question'] for x in items],[2,2])
