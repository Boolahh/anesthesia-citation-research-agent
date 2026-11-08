"""Heterogeneous PDF formats, study safety, provenance and restart regressions.

Uses synthetic data; no unpublished PDF or real chat is checked into GitHub.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile
import json
import subprocess
import sys
import tempfile

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.pdf_extract import parse_pdf, ids_as_shown
from agent.research import Bibliography, parse_pubmed_xml, safe_url
from agent.workbook import TemplateWorkbook
from run_agent import file_tool, checksum, _review_rows, APP_VERSION

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx'
Q04 = 'How can local anesthetic systemic toxicity be prevented, recognized, and managed in adults receiving regional anesthesia?'
Q11 = 'Should volatile anesthesia or total intravenous anesthesia be used in an adult undergoing coronary artery bypass graft surgery?'


def synthetic_pdf(path, question, lines, links=()):
    with fitz.open() as doc:
        page = doc.new_page(width=930, height=930)
        page.insert_text((50, 45), question, fontsize=9)
        for i, line in enumerate(lines):
            page.insert_text((65, 90 + 27*i), line, fontsize=10)
        for i, url in links:
            y = 90 + 27*i
            page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(60, y-13, 740, y+4), 'uri': url})
        doc.save(path)


PMXML = '''<?xml version="1.0" encoding="utf-8"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID>
<Article><ArticleTitle>Safe anesthesiology source title</ArticleTitle>
<Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue>
<Title>Clinical Safety Journal</Title></Journal>
<ArticleDate><Year>2023</Year></ArticleDate>
<AuthorList>
<Author><LastName>North</LastName><ForeName>Jane</ForeName>
<AffiliationInfo><Affiliation>Queen's University, Kingston, Canada</Affiliation></AffiliationInfo></Author>
<Author><LastName>Middle</LastName><ForeName>Sam</ForeName>
<AffiliationInfo><Affiliation>Department A, United States</Affiliation></AffiliationInfo>
<AffiliationInfo><Affiliation>Department B, United Kingdom</Affiliation></AffiliationInfo></Author>
<Author><LastName>South</LastName><ForeName>Alex</ForeName>
<AffiliationInfo><Affiliation>University of Toronto, Canada</Affiliation></AffiliationInfo></Author>
</AuthorList><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.1234/safe.2023.1</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''


class MultiPlatformExtractionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = TemplateWorkbook(TEMPLATE)

    def test_all_sixteen_platform_codes_supported(self):
        tools = self.workbook.data.tool_names
        self.assertEqual(len(tools), 16)
        with tempfile.TemporaryDirectory() as d:
            for code in tools:
                path = Path(d)/code/'Q01.pdf'
                self.assertEqual(file_tool(path, tools, root=Path(d)), code)
            self.assertEqual(file_tool(Path(d)/'ChatGPT_for_Clinicians_Q05.pdf', tools), 'CGC')
            self.assertEqual(file_tool(Path(d)/'ChatGPT_Q05.pdf', tools), 'CGP')
            self.assertEqual(file_tool(Path(d)/'Gemini_Q05.pdf', tools), 'GEM')
            self.assertIsNone(file_tool(Path(d)/'Q05.pdf', tools))

    def test_numbered_references_without_links_and_original_visible_url(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'Q11_plain_sources.pdf'
            synthetic_pdf(path, Q11, [
                'References',
                '1. Example anesthetic trial. Clinical Study Journal. 2020. https://doi.org/10.1234/testA',
                '2. Another randomized CABG trial, Clinical Study Journal, 2021.',
                'Conclusions',
                'Sources searched',
                '3. Never cited paper 2024. https://doi.org/10.1234/unused',
            ])
            rows, warn = parse_pdf(path, 'CGP', self.workbook.data.questions)
            self.assertEqual(len(rows), 2, rows)
            self.assertEqual(rows[0]['doi'].lower(), '10.1234/testa')
            self.assertEqual(rows[0]['url'], 'https://doi.org/10.1234/testA')
            self.assertEqual(rows[1]['url'], 'NR')
            self.assertFalse(any('unused' in r['citation'].lower() for r in rows))

    def test_cross_platform_numeric_pdf_citations(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'Q04_numbered.pdf'
            synthetic_pdf(path, Q04, ['References', '[1] Example safety checklist, 2021',
                                      '[2] Example management summary, 2022'],
                          links=[(1, 'https://pubmed.ncbi.nlm.nih.gov/12345678/')])
            rows, warnings = parse_pdf(path, 'OEV', self.workbook.data.questions)
            self.assertGreaterEqual(len(rows), 2, warnings)
            self.assertEqual(rows[0]['tool'], 'OEV')

    def test_scanned_pdf_requires_review_not_fabrication(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'Q11_scan.pdf'
            with fitz.open() as doc:
                doc.new_page().draw_rect(fitz.Rect(40, 50, 200, 250), fill=(0,0,0))
                doc.save(path)
            rows, warnings = parse_pdf(path, 'CGP', self.workbook.data.questions)
            self.assertEqual(rows, [])
            # No question evidence; do not guess from otherwise unlabelled pixels.
            self.assertTrue(any('OCR' in x for x in warnings))

    def test_untrusted_urls_and_source_ids(self):
        for x in ('http://127.1/', 'http://0x7f000001/', 'http://2130706433/',
                  'http://127.0.0.1/', 'file:///tmp/a', 'http://test.internal/test',
                  'https://example.com@localhost/'): self.assertFalse(safe_url(x), x)
        self.assertTrue(safe_url('https://pubmed.ncbi.nlm.nih.gov/12345678/'))
        self.assertEqual(ids_as_shown('Example citation', 'https://pubmed.ncbi.nlm.nih.gov/12345678/')[1], '12345678')

    def test_sha256_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'sample.pdf'
            p.write_bytes(b'private-study-sample')
            self.assertEqual(checksum(p), checksum(p))


class AuthorSpecificEvidenceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = TemplateWorkbook(TEMPLATE)

    def test_pubmed_author_affiliations_never_cross_assigned(self):
        paper = parse_pubmed_xml(PMXML)
        self.assertEqual(paper['year'], '2024')
        self.assertEqual(paper['year_basis'], 'PubMed journal issue date')
        self.assertEqual(paper['online_year'], '2023')
        self.assertEqual(paper['authors'][0]['affiliations'], ["Queen's University, Kingston, Canada"])
        self.assertEqual(paper['authors'][-1]['affiliations'], ['University of Toronto, Canada'])
        with tempfile.TemporaryDirectory() as d:
            engine = Bibliography(self.book.data.countries, d, offline=True)
            evidence = {'doi': paper['doi'], 'pmid': paper['pmid'], 'pubmed': paper,
                        'openalex': {'id':'https://openalex.org/W1','cited_by_count': 21,
                             'authorships': [
                                 {'author': {'display_name':'Jane North'},
                                  'institutions':[{'display_name':'Incorrect University'}]},
                                 {'author': {'display_name':'Alex South'},
                                  'institutions':[{'display_name':'Incorrect University'}]},
                             ]},
                        'crossref': None, 'europepmc': None, 'public_page': None, 'source_url': ''}
            green = engine.baseline_green(evidence)
            self.assertEqual(green['AL'], 'Jane North')
            self.assertEqual(green['AM'], "Queen's University, Kingston, Canada")
            self.assertEqual(green['AQ'], 'Alex South')
            self.assertEqual(green['AR'], 'University of Toronto, Canada')
            self.assertEqual(green['AN'], 'Canada')
            self.assertEqual(green['AS'], 'Canada')
            self.assertEqual(green['AV'], 'NR')  # Corresponding author unknown.
            self.assertEqual(green['BE'], '')   # Licensed JCR metric not guessed.
            self.assertEqual(green['AA'], '2024')
            self.assertEqual(evidence['field_provenance']['AM']['source'], 'PubMed author-specific AffiliationInfo')
            self.assertNotIn('Incorrect University', json.dumps(green))

    def test_multiple_affiliations_are_ambiguous(self):
        paper = parse_pubmed_xml(PMXML)
        paper['authors'] = [paper['authors'][1]]
        with tempfile.TemporaryDirectory() as d:
            eng = Bibliography(self.book.data.countries, d, offline=True)
            evidence = {'pubmed': paper, 'openalex': {}, 'crossref': {},
                        'europepmc': {}, 'public_page': {}, 'doi': paper['doi'], 'pmid': paper['pmid'], 'source_url': ''}
            green = eng.baseline_green(evidence)
            self.assertEqual(green['AM'], 'NR')
            self.assertEqual(green['AN'], 'NR')
            self.assertTrue(any('multiple' in w for w in evidence['review_flags']))

    def test_crossref_only_does_not_assign_openalex_institutions(self):
        with tempfile.TemporaryDirectory() as d:
            eng = Bibliography(self.book.data.countries, d, offline=True)
            oa = {'id': 'W3', 'authorships': [{'author': {'display_name': 'First'},
                      'institutions': [{'display_name': 'Unverified College'}]},
                     {'author': {'display_name': 'Last'}, 'institutions': [{'display_name': 'Unverified College'}]}]}
            ev = {'pubmed': None, 'openalex': oa, 'crossref': None,
                  'europepmc': None, 'public_page': None, 'doi': '', 'pmid': '', 'source_url': ''}
            fields = eng.baseline_green(ev)
            self.assertEqual(fields['AL'], 'First')
            self.assertEqual(fields['AQ'], 'Last')
            self.assertEqual(fields['AM'], 'NR')
            self.assertEqual(fields['AR'], 'NR')

    def test_review_queue_preserves_uncertain_sources(self):
        citation = {'tool':'CGP', 'question':'Q11', 'order':1, 'url':'NR',
                    'citation':'Example 2024 guideline', 'source_file':'Q11.pdf',
                    'source_page':2, 'extraction_confidence':'low'}
        queue = _review_rows([citation], [], [{'file':'Q11.pdf','warning':'Collapsed +N labels'}])
        self.assertEqual(len(queue), 2)
        self.assertEqual(queue[0]['priority'], 'High')
        self.assertIn('No original source URL', queue[0]['reason'])


class WorkflowTests(TestCase):
    def test_research_only_requires_no_pdf_and_preserves_reviewer_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            from agent.workbook import set_value
            wb = TemplateWorkbook(TEMPLATE)
            rn = wb.upsert_blue({'tool':'CGP','question':'Q11','order':1,
                                 'citation':'Example DOI trial, 2024','url':'https://doi.org/10.1234/abc',
                                 'title':'Example DOI trial','authors':'NR','year':'2024','journal':'NR',
                                 'doi':'10.1234/abc','pmid':'NR','repeat':'N'})
            set_value(wb.data_rows[rn], 'U', 'Real - correct')
            reviewed = root/'reviewed.xlsx'
            wb.save(reviewed)
            out = root/'enriched.xlsx'
            cp = subprocess.run([sys.executable, str(ROOT/'run_agent.py'), 'run',
                '--stage','research','--no-ai','--offline','--template',str(reviewed),
                '--output',str(out),'--input',str(root/'nonexistent'),
                '--report-dir',str(root/'reports'),'--max-sources','1'],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            result = TemplateWorkbook(out)
            self.assertEqual(result.get_row(rn)['U'], 'Real - correct')
            summary = json.loads((root/'reports/run_report.json').read_text())
            self.assertEqual(summary['citations_extracted'], 1)
            self.assertEqual(summary['sources_researched'], 1)
            self.assertEqual(summary['rows_written_green'], 0)
            self.assertTrue((root/'reports/review_queue.csv').exists())
            self.assertEqual(summary['version'], APP_VERSION)


class HumanReviewTests(TestCase):
    def test_review_decisions_only_change_explicit_human_fields(self):
        from agent.reviewer import apply_decisions, decision_template
        from agent.workbook import set_value
        wb=TemplateWorkbook(TEMPLATE)
        row=wb.upsert_blue({'tool':'CGP','question':'Q11','order':1,
            'citation':'Synthetic medical review, 2023','url':'NR','title':'Synthetic review',
            'authors':'NR','year':'2023','journal':'NR','doi':'NR','pmid':'NR','repeat':'N'})
        original=wb.get_row(row)['D']
        decision={'tool':'CGP','question':'Q11','order':'1','verifier_initials':'AZ',
            'verdict':'Real - correct','link_status':'No link given', 'notes':'Checked source manually'}
        audit=apply_decisions(wb,[decision])
        self.assertEqual(len(audit),1)
        self.assertEqual(wb.get_row(row)['U'],'Real - correct')
        self.assertEqual(wb.get_row(row)['T'],'AZ')
        self.assertEqual(wb.get_row(row)['D'],original)
        self.assertEqual(wb.get_row(row)['BG'],'')
        self.assertTrue(any(d['tool']=='CGP' for d in decision_template(wb)))
        with self.assertRaises(ValueError):
            apply_decisions(wb,[{**decision,'verdict':'Hallucinated - does not exist'}])

    def test_invalid_decision_batch_is_atomic(self):
        from agent.reviewer import apply_decisions
        wb=TemplateWorkbook(TEMPLATE)
        row=wb.upsert_blue({'tool':'CGP','question':'Q11','order':1,
            'citation':'Synthetic study','url':'NR','title':'Synthetic','authors':'NR',
            'year':'NR','journal':'NR','doi':'NR','pmid':'NR','repeat':'N'})
        with self.assertRaises(ValueError):
            apply_decisions(wb,[{'tool':'CGP','question':'Q11','order':'1','verdict':'Real - correct'},
                                {'tool':'CGP','question':'Q11','order':'2','verdict':'Incorrect label'}])
        self.assertFalse(wb.get_row(row).get('U'))

    def test_review_only_script_generates_blank_form(self):
        from agent.reviewer import decision_template, write_review_csv, load_review_csv
        wb=TemplateWorkbook(TEMPLATE)
        wb.upsert_blue({'tool':'CGP','question':'Q11','order':1,'citation':'Citation A','url':'NR',
            'title':'NR','authors':'NR','year':'NR','journal':'NR','doi':'NR','pmid':'NR','repeat':'N'})
        with tempfile.TemporaryDirectory() as d:
            form=Path(d)/'form.csv'
            write_review_csv(form,decision_template(wb))
            rows=load_review_csv(form)
            self.assertEqual(rows[0]['verdict'],'')
            self.assertEqual(rows[0]['citation_as_shown'],'Citation A')


class VerifiedSourcePriorityTests(TestCase):
    def test_human_verified_source_url_overrides_wrong_cited_identifier(self):
        from run_agent import _original_rows
        from agent.workbook import set_value
        wb = TemplateWorkbook(TEMPLATE)
        row = wb.upsert_blue({'tool':'CGP','question':'Q11','order':1,
            'citation':'Original wrong cited DOI','url':'https://doi.org/10.1234/wrong',
            'title':'Source title','authors':'NR','year':'2023','journal':'NR',
            'doi':'10.1234/wrong','pmid':'NR','repeat':'N'})
        set_value(wb.data_rows[row], 'X', 'https://doi.org/10.5678/correct')
        result = _original_rows(wb)[0]
        self.assertTrue(result['source_url_verified'])
        self.assertEqual(result['doi'], '10.1234/wrong')  # Original remains as-cited.
        with tempfile.TemporaryDirectory() as d:
            engine = Bibliography(wb.data.countries, d, offline=True)
            with patch.object(engine, 'fetch_json', return_value=None), patch.object(engine, 'public_page', return_value=None):
                evidence = engine.metadata(result)
        self.assertEqual(evidence['doi'], '10.5678/correct')
        self.assertTrue(any('Original cited DOI differs' in msg for msg in evidence['match']['warnings']))


class LicensedJournalEvidenceTests(TestCase):
    def test_verified_scimago_country_and_licensed_jcr_evidence(self):
        from agent.journal_evidence import load_journal_evidence, supplement_journal_fields
        wb=TemplateWorkbook(TEMPLATE)
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'journal.csv'
            file.write_text('journal_name,country,scimago_url,impact_factor_2026,jcr_evidence_id,date_checked\n'
                'Clinical Safety Journal,Canada,https://www.scimagojr.com/journalsearch.php?q=999,3.2,JCR-2026-licensed-export-row-42,2026-11-01\n')
            entries=load_journal_evidence(file,wb.data.countries)
            ev={}
            result=supplement_journal_fields({'AD':'Journal article','BA':'Clinical Safety Journal','BB':'NOT FOUND','BE':''},ev,entries,wb.data.countries)
            self.assertEqual(result['BB'],'Canada')
            self.assertEqual(result['BC'],'Region of the Americas')
            self.assertEqual(result['BE'],'3.2')
            self.assertIn('SCImago',ev['field_provenance']['BB']['source'])
            self.assertIn('2026 Journal Citation Reports',ev['field_provenance']['BE']['source'])

    def test_journal_evidence_missing_provenance_rejected(self):
        from agent.journal_evidence import load_journal_evidence
        wb=TemplateWorkbook(TEMPLATE)
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'journal.csv'
            file.write_text('journal_name,country,scimago_url,impact_factor_2026,jcr_evidence_id,date_checked\n'
                'Clinical Journal,Canada,,5.2,,2026-11-01\n')
            with self.assertRaises(ValueError):
                load_journal_evidence(file,wb.data.countries)


class CrossPlatformStudyIntegrityTests(TestCase):
    def test_identical_pdfs_from_two_platforms_both_count(self):
        # Study records cannot be globally deduplicated by PDF hash: two
        # independent tools may legitimately emit byte-identical responses.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with fitz.open() as doc:
                page=doc.new_page(width=900,height=800)
                page.insert_text((45,50),Q11,fontsize=9)
                page.insert_text((45,85),'References',fontsize=10)
                page.insert_text((45,115),'1. Example cardiac anesthesia paper, 2024 DOI 10.1234/example',fontsize=9)
                pdf=root/'source.pdf'
                doc.save(pdf)
            for code in ('CGP','CLG'):
                folder=root/'inputs'/code
                folder.mkdir(parents=True)
                (folder/'Q11.pdf').write_bytes(pdf.read_bytes())
            cp=subprocess.run([sys.executable,str(ROOT/'run_agent.py'),'scan','--no-ai','--offline',
                               '--input',str(root/'inputs'),'--report-dir',str(root/'reports')],
                              cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(cp.returncode,0,cp.stderr)
            records=json.loads((root/'reports'/'citations_extracted.json').read_text())
            self.assertEqual({x['tool'] for x in records},{'CGP','CLG'})
            self.assertEqual(len(records),2)
