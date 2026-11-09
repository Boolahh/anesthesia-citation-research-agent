"""DeepSeek numbered-marker semantics and PDF-source follow-up validation."""
from unittest import TestCase

from run_agent import _source_quality_review
from agent.source_coverage import source_access_review


def dsk_citation(order, marker='8', confidence='high', url='https://example.org/record.pdf'):
    return {
        'tool':'DSK','question':'Q03','order':order,
        'citation':marker,'url':url,'source_file':'Q03_deepseek.pdf',
        'source_page':1,'extraction_method':'deepseek_numbered_link',
        'extraction_confidence':confidence,
        'source_context':'inline_link','repeat':'Y' if order > 1 else 'N',
    }


class NumberedLinkQualityTests(TestCase):
    def test_expected_deepseek_markers_are_not_malformed_bibliography(self):
        rows=[dsk_citation(i) for i in range(1,8)]
        report=_source_quality_review(rows)
        self.assertEqual(len(report),7)
        self.assertTrue(all(v['expected_numbered_citation_marker']=='Y' for v in report))
        self.assertTrue(all(v['short_or_generic_label']=='N' for v in report))
        self.assertTrue(all(v['review_priority']!='High' for v in report))
        self.assertIn('numbered link marker', report[0]['review_reason'])

    def test_displaced_link_marker_remains_high_priority(self):
        report=_source_quality_review([dsk_citation(1, confidence='review')])
        self.assertEqual(report[0]['review_priority'],'High')
        self.assertEqual(report[0]['short_or_generic_label'],'N')

    def test_other_providers_keep_short_label_alert(self):
        row=dsk_citation(1)
        row['tool']='CLG'
        row['extraction_method']='generic_pdf_link'
        report=_source_quality_review([row])
        self.assertEqual(report[0]['expected_numbered_citation_marker'],'N')
        self.assertEqual(report[0]['short_or_generic_label'],'Y')

    def test_linkless_numeric_marker_is_still_high_priority(self):
        row=dsk_citation(1,url='NR')
        report=_source_quality_review([row])
        self.assertEqual(report[0]['review_priority'],'High')


class PDFSourceReviewActionsTests(TestCase):
    def run_review(self,status,title_hint=''):
        row=dsk_citation(1)
        proposal={
            'tool':'DSK','question':'Q03','order':1,
            'written_to_workbook':False,
            'match':{'status':'review_required'},
            'source_document':{'status':status,'title_hint':title_hint},
        }
        result=source_access_review([row],[proposal])
        self.assertEqual(len(result),1)
        return result[0]['review_action']

    def test_already_read_pdf_does_not_suggest_repeating_the_same_download(self):
        action=self.run_review('read', 'Massiv blödning - Anestesirutin')
        self.assertIn('successfully read',action)
        self.assertIn('first-page heading', action)
        self.assertIn('do not re-download', action)

    def test_book_pdf_read_without_identified_title_requests_publisher_metadata(self):
        action=self.run_review('read')
        self.assertIn('already read',action)
        self.assertIn('publisher record',action)

    def test_timeout_does_not_trigger_retry_loop(self):
        action=self.run_review('time_budget_exceeded')
        self.assertIn('exceeded',action)
        self.assertIn('do not loop automatic retries',action)

    def test_uninspected_pdf_can_suggest_targeted_inspection(self):
        action=self.run_review('')
        self.assertIn('Inspect linked source PDFs',action)
