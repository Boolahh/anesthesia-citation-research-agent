"""No guessed citation rows or green source metadata in strict mode.

All tests use synthetic citations and fake publication records; they do not
authenticate any clinical source or substitute for investigator review.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from agent.strict_sources import (
    reliable_original_identity, strict_green_values, MISSING,
)
from agent.workbook import TemplateWorkbook, GREEN_COLS
from run_agent import enrich, research_candidate

TEMPLATE = (Path(__file__).resolve().parents[1] / 'template' /
            'AI_Citation_Bias_Extraction_Workbook.xlsx')


def source(tool='DSK', question='Q03', url='https://nysora.com/unverified-page'):
    return {
        'tool': tool, 'question': question, 'order': 1, 'citation': '7',
        'url': url, 'title': 'NR', 'doi': 'NR', 'pmid': 'NR',
        'authors': 'NR', 'journal': 'NR', 'year': 'NR', 'repeat': 'N',
    }


def evidence(**overrides):
    baseline = {
        'match': {'method':'none', 'status':'review_required', 'warnings':[]},
        'doi':'', 'pmid':'', 'pubmed':None, 'crossref':None,
        'europepmc':None, 'openalex':None, 'public_page':None,
        'public_pdf':None, 'source_url':'',
    }
    baseline.update(overrides)
    return baseline


class StrictBibliographyIdentityTests(TestCase):
    def test_nysora_webpage_title_is_not_a_confirmed_publication(self):
        e = evidence(public_page={
            'title': 'Interesting article about anesthesia',
            'meta': {'og:title':['Interesting article about anesthesia']},
        })
        ok, reason = reliable_original_identity(source(), e)
        self.assertFalse(ok)
        self.assertIn('not independently confirmed',reason)

    def test_pubmed_record_link_matches_pubmed_record_id(self):
        c = source(url='https://pubmed.ncbi.nlm.nih.gov/12345678/#7')
        e = evidence(pmid='12345678',pubmed={
            'pmid':'12345678', 'title':'A synthetic anesthetic controlled trial'})
        ok, basis = reliable_original_identity(c, e)
        self.assertTrue(ok)
        self.assertIn('PubMed', basis)

    def test_nonrecord_pubmed_search_page_is_never_a_paper(self):
        c = source(url='https://pubmed.ncbi.nlm.nih.gov/?term=anesthesia')
        e = evidence(pmid='12345678',pubmed={
            'pmid':'12345678','title':'An unrelated study'},
            match={'method':'none', 'status':'non_source_search_results','warnings':[]})
        self.assertFalse(reliable_original_identity(c,e)[0])

    def test_doi_link_requires_exact_authoritative_doi_match(self):
        c = source(url='https://doi.org/10.1234/synthetic')
        e = evidence(doi='10.1234/synthetic',crossref={
            'DOI':'10.1234/synthetic',
            'title':['An original clinical methods article']})
        self.assertTrue(reliable_original_identity(c,e)[0])
        e['crossref']['DOI']='10.1234/different'
        self.assertFalse(reliable_original_identity(c,e)[0])

    def test_original_printed_doi_with_no_link_can_match_specific_article(self):
        c = source(url='NR')
        c['doi'] = '10.1234/synthetic'
        e = evidence(doi='10.1234/synthetic',crossref={
            'DOI':'10.1234/synthetic', 'title':['A synthetic case report']})
        self.assertTrue(reliable_original_identity(c,e)[0])
        c['doi'] = 'NR'
        self.assertFalse(reliable_original_identity(c,e)[0])

    def test_title_search_alone_can_never_autofill(self):
        c = source(url='NR')
        c['citation']='An extensive exact clinical trial title in the bibliography'
        e = evidence(doi='10.1234/synthetic',crossref={
            'DOI':'10.1234/synthetic','title':[c['citation']]},
            match={'method':'high_similarity_title_candidate',
                   'status':'title_candidate_unverified','warnings':[]})
        self.assertFalse(reliable_original_identity(c,e)[0])

    def test_authoritative_publisher_doi_and_title_must_both_agree(self):
        c = source(url='https://publisher.example.org/articles/123456')
        e = evidence(doi='10.1234/article',crossref={
            'DOI':'10.1234/article','title':['Valid Synthetic Clinical Article']},
            public_page={'meta':{
                'citation_doi':['10.1234/article'],
                'citation_title':['Valid Synthetic Clinical Article']}})
        self.assertTrue(reliable_original_identity(c,e)[0])
        e['public_page']['meta']['citation_title']=['Totally Different Publication']
        self.assertFalse(reliable_original_identity(c,e)[0])

    def test_retrieved_record_identifier_conflict_stops_all_fields(self):
        c=source(url='https://doi.org/10.1234/a')
        e=evidence(doi='10.1234/a',crossref={'DOI':'10.1234/a','title':['Study']},
                   match={'method':'identifier','status':'identifier_conflict',
                          'warnings':['Original cited DOI conflicts with hyperlink DOI']})
        self.assertFalse(reliable_original_identity(c,e)[0])


class StrictGreenFieldTests(TestCase):
    def test_no_verified_publication_all_fields_are_not_found_except_licensed_jcr(self):
        fields={k:'Guessed Value' for k in GREEN_COLS}
        result=strict_green_values(fields,{},eligible=False)
        self.assertEqual(result['Z'],MISSING)
        self.assertEqual(result['AN'],MISSING)
        self.assertEqual(result['AD'],MISSING)
        self.assertEqual(result['BE'],'')
        self.assertEqual(set(result),set(GREEN_COLS))

    def test_confirmed_record_still_filters_openalex_country_and_website_guess(self):
        fields={
            'Z':'Real title from PubMed', 'AN':'Canada', 'AO':'Americas',
            'AL':'Synthetic Author', 'AD':'Guideline',
            'BF':'Not applicable (not a scholarly publication)'
        }
        provenance={
            'Z':{'source':'PubMed / Crossref / Europe PMC / publisher'},
            'AN':{'source':'OpenAlex matched author-country'},
            'AO':{'source':'OpenAlex matched author-country'},
            'AL':{'source':'PubMed author-specific AffiliationInfo'},
            'AD':{'source':'independently retrieved publication title'},
            'BF':{'source':'source category'},
        }
        result=strict_green_values(fields,provenance,eligible=True)
        self.assertEqual(result['Z'],'Real title from PubMed')
        self.assertEqual(result['AL'],'Synthetic Author')
        self.assertEqual(result['AN'],'NOT FOUND')
        self.assertEqual(result['AO'],'NOT FOUND')
        self.assertEqual(result['AD'],'NOT FOUND')
        self.assertEqual(result['BF'],'NOT FOUND')

    def test_strict_enrichment_discards_lone_webpage_and_never_invokes_paid_ai(self):
        wb=TemplateWorkbook(TEMPLATE)
        e=evidence(public_page={'title':'Random medical education page','meta':{}},
                   source_url='https://nysora.com/unverified-page')
        bibliography=Mock()
        bibliography.metadata.return_value=e
        bibliography.baseline_green.return_value={
            col: ('Random medical education page' if col=='Z' else 'NR')
            for col in GREEN_COLS}
        ai=Mock()
        result=enrich(source(),wb,bibliography,ai)
        ai.code_source.assert_not_called()
        self.assertFalse(result['strict_source_identified'])
        self.assertFalse(result['can_autowrite'])
        self.assertEqual(result['fields']['Z'],'NOT FOUND')
        self.assertEqual(result['fields']['AN'],'NOT FOUND')
        self.assertIn('original citation and url',
                      ' '.join(result['review_flags']).lower())

    def test_unlinked_long_title_is_not_automatically_searched(self):
        wb=TemplateWorkbook(TEMPLATE)
        c=source(url='NR')
        c['citation']='Very long and impressive sounding paper about anesthesia practice'
        c['title']=c['citation']
        c['order']=1
        wb.upsert_blue(c)
        _,_,allowed=research_candidate(c,wb)
        self.assertFalse(allowed)


class StrictWorkbookRetentionTests(TestCase):
    def test_unretrievable_citation_stays_with_original_url_and_not_found(self):
        wb=TemplateWorkbook(TEMPLATE)
        citation=source(url='https://example.org/article-with-no-metadata')
        rn=wb.upsert_blue(citation)
        self.assertTrue(wb.mark_unretrievable(rn))
        row=wb.get_row(rn)
        self.assertEqual(row['D'],'7')
        self.assertEqual(row['E'],'https://example.org/article-with-no-metadata')
        self.assertEqual(row['Z'],'NOT FOUND')
        self.assertEqual(row['AN'],'NOT FOUND')
        self.assertEqual(row.get('BE',''),'')
        self.assertEqual(row.get('U',''),'')
        self.assertFalse(wb.mark_unretrievable(rn))

    def test_not_found_placeholders_can_be_replaced_by_authoritative_new_record(self):
        wb=TemplateWorkbook(TEMPLATE)
        rn=wb.upsert_blue(source())
        wb.mark_unretrievable(rn)
        values=['NOT FOUND']*len(GREEN_COLS)
        values[GREEN_COLS.index('Z')]='Verified-registry candidate title'
        values[GREEN_COLS.index('AN')]='Canada'
        self.assertTrue(wb.upsert_green(rn,values,'provisional'))
        self.assertEqual(wb.get_row(rn)['Z'],'Verified-registry candidate title')
        self.assertEqual(wb.get_row(rn)['AN'],'Canada')
        self.assertEqual(wb.get_row(rn)['U'] if 'U' in wb.get_row(rn) else '', '')

    def test_existing_human_research_values_are_not_erased_by_missing_metadata(self):
        wb=TemplateWorkbook(TEMPLATE)
        rn=wb.upsert_blue(source())
        row=wb.data_rows[rn]
        from agent.workbook import set_value
        set_value(row,'Z','Previously reviewed source title')
        set_value(row,'U','Real - correct')
        wb.mark_unretrievable(rn)
        self.assertEqual(wb.get_row(rn)['Z'],'Previously reviewed source title')
        self.assertEqual(wb.get_row(rn)['U'],'Real - correct')
