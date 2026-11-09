"""One geography-review record per source, with primary-outcome evidence."""
from unittest import TestCase
from run_agent import _geography_review, GEOGRAPHY_REVIEW_FIELDS


class FakeWorkbook:
    existing = {('CGP','Q01',1): 4, ('CGP','Q02',1): 5, ('CGP','Q03',1): 6}

    def get_row(self, row):
        if row == 4:
            return {
                'Z':'Synthetic clinical publication', 'AD':'Journal article',
                'AL':'Ada Author', 'AM':'NR', 'AN':'Canada', 'AO':'Region of the Americas',
                'AP':'High income', 'AQ':'Eli Author', 'AS':'United States',
            }
        if row == 5:
            return {
                'Z':'NR', 'AL':'Ada Author', 'AM':'NR', 'AN':'NR', 'AO':'NR', 'AP':'NR',
                'AD':'NR',
            }
        return {
            'Z':'NOT FOUND', 'AL':'NR', 'AN':'NR', 'AD':'Professional society or organization webpage'
        }


class GeographicReviewTests(TestCase):
    def test_unique_records_and_inferred_country_provenance(self):
        original = [
            {'tool':'CGP','question':'Q01','order':1,'citation':'Original 1','url':'https://doi.org/10.1234/a'},
            {'tool':'CGP','question':'Q02','order':1,'citation':'Original 2','url':'NR'},
            {'tool':'CGP','question':'Q03','order':1,'citation':'Original 3','url':'https://example.org'},
        ]
        proposal = [{
            'tool':'CGP','question':'Q01','order':1, 'written_to_workbook':True,
            'field_provenance': {'AN': {'source':'OpenAlex matched author-country',
                                       'url':'https://openalex.org/W123', 'reason':'one country'}},
            'review_flags': ['verify country']
        }]
        output = _geography_review(original, proposal, FakeWorkbook())
        self.assertEqual(len(output), 3)
        self.assertTrue(set(GEOGRAPHY_REVIEW_FIELDS).issubset(set(output[0])))
        self.assertEqual(output[0]['first_author_country'], 'Canada')
        self.assertEqual(output[0]['first_country_evidence_url'], 'https://openalex.org/W123')
        self.assertEqual(output[0]['review_priority'], 'High - verify OpenAlex inference')
        self.assertEqual(output[1]['review_priority'], 'High - primary outcome missing')
        self.assertEqual(output[2]['review_priority'], 'Applicability review')
        self.assertEqual(output[1]['first_author_country'], 'NR')


    def test_edited_book_without_individual_first_author_requires_applicability_review(self):
        class EditedVolume:
            existing = {('DSK', 'Q03', 1): 14}
            def get_row(self, rownum):
                return {
                    'Z':'Australasian Anaesthesia 2025',
                    'AD':'Textbook or book chapter',
                    'AL':'NR', 'AN':'NR',
                }
        row = [{
            'tool':'DSK','question':'Q03','order':1,
            'citation':'7','url':'https://www.anzca.edu.au/2025_blue_book_pdf.pdf',
        }]
        proposal = [{
            'tool':'DSK','question':'Q03','order':1,'written_to_workbook':True,
            'source_document':{'status':'read','document_kind':'edited_book_compilation'},
        }]
        result = _geography_review(row, proposal, EditedVolume())
        self.assertEqual(result[0]['review_priority'], 'Applicability review')
        self.assertIn('whether an individual first author', result[0]['review_action'])
