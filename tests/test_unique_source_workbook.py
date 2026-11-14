"""Regression: one workbook row per linked source within each AI question.

Synthetic example reproduces many repeated Claude/ChatGPT badges. The original
occurrence counts remain available independently for study-methodology review.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile

from agent.source_dedup import source_key, unique_question_sources
from agent.citation_census import citation_census_by_question
from agent.workbook import TemplateWorkbook, row_dict, set_value

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'template' / 'AI_Citation_Bias_Extraction_Workbook.xlsx'


def citation(tool, question, order, url, text='nysora', context='inline_link'):
    return {
        'tool':tool, 'question':question, 'order':order, 'url':url,
        'citation':text, 'title': 'NR', 'authors':'NR', 'year':'NR',
        'journal':'NR', 'doi':'NR', 'pmid':'NR', 'repeat':'N',
        'source_context':context, 'source_file':f'{tool}_{question}.pdf',
        'source_page':1,
    }


class DistinctSourceRuleTests(TestCase):
    def test_claude_22_repeated_links_become_one_row_per_question(self):
        source='https://nysora.com/?p=68145'
        rows=[citation('CLG','Q01',i,source) for i in range(1,23)]
        rows += [
            citation('CLG','Q01',23,source,
                     'Important consensus guideline, complete original source reference',
                     'bibliography'),
            citation('CLG','Q01',24,'https://pubmed.ncbi.nlm.nih.gov/12345678/',
                     'Second independently linked publication','bibliography'),
            citation('CLG','Q02',1,source),
            citation('CGP','Q01',1,source),
        ]
        clean=unique_question_sources(rows)
        self.assertEqual(len(clean),4)
        self.assertEqual([(r['tool'],r['question'],r['order']) for r in clean],
                         [('CLG','Q01',1),('CLG','Q01',2),
                          ('CLG','Q02',1),('CGP','Q01',1)])
        self.assertEqual(clean[0]['occurrence_count'],23)
        self.assertEqual(clean[0]['citation'],
                         'Important consensus guideline, complete original source reference')
        self.assertEqual(clean[0]['repeat'],'Y')
        self.assertEqual(len(rows),26)  # raw source evidence remains unchanged
        counts=citation_census_by_question(rows)
        self.assertEqual(next(x for x in counts if (x['tool'],x['question'])==('CLG','Q01'))
                         ['repeat_occurrences'],22)

    def test_deepseek_numbered_same_url_is_one_source(self):
        url='https://pubmed.ncbi.nlm.nih.gov/12345678/'
        rows=[citation('DSK','Q01',n,url,str(n)) for n in range(1,30)]
        self.assertEqual(len(unique_question_sources(rows)),1)
        self.assertEqual(unique_question_sources(rows)[0]['occurrence_count'],29)
        self.assertEqual(unique_question_sources(rows)[0]['repeat'],'Y')

    def test_bibliography_doi_text_does_not_duplicate_original_same_url(self):
        url='https://medical.org/paper'
        a=citation('CLG','Q01',1,url,'medical.org')
        b=citation('CLG','Q01',2,url,'Example author. A full paper with doi:10.1234/test. 2026','bibliography')
        self.assertEqual(source_key(a),source_key(b))
        self.assertEqual(len(unique_question_sources([a,b])),1)

    def test_unlinked_generic_badges_are_never_assumed_same_publication(self):
        first=citation('CGP','Q01',1,'NR','source')
        second=citation('CGP','Q01',2,'NR','source')
        self.assertEqual(len(unique_question_sources([first,second])),2)

    def test_distinct_url_and_question_never_auto_merged_on_similar_title(self):
        rows=[citation('CLG','Q01',1,'https://site-a.org/1','A trial'),
              citation('CLG','Q01',2,'https://site-b.org/1','A trial'),
              citation('CLG','Q02',1,'https://site-a.org/1','A trial')]
        self.assertEqual(len(unique_question_sources(rows)),3)


class LegacyWorkbookMigrationTests(TestCase):
    def make_old_workbook(self, *, conflict=False):
        wb=TemplateWorkbook(TEMPLATE)
        rows=wb.free_rows[:3]
        base='https://nysora.com/?p=68145'
        entries=[('CLG','Q01',1,base),('CLG','Q01',2,base),
                 ('CLG','Q01',3,'https://pubmed.ncbi.nlm.nih.gov/12345678/')]
        for rn,(tool,question,order,url) in zip(rows,entries):
            row=wb.data_rows[rn]
            for col,val in [('A',tool),('B',question),('C',order),
                            ('D','nysora' if order<3 else 'Different trial'),
                            ('E',url),('L','Y' if order==2 else 'N')]:
                set_value(row,col,val)
        # Two copies of the same source can have identical green proposals.
        set_value(wb.data_rows[rows[0]],'Z','Stable candidate title')
        set_value(wb.data_rows[rows[1]],'Z',
                  'Conflicting candidate title' if conflict else 'Stable candidate title')
        # The human reviewer entered a verdict on a duplicate old occurrence:
        # it must be carried to the retained source row, never discarded.
        set_value(wb.data_rows[rows[1]],'U','Real - correct')
        wb.changed.add('Data_Extraction')
        return wb, rows

    def test_old_repeated_rows_migrate_without_losing_reviewed_fields(self):
        wb, old=self.make_old_workbook()
        with TemporaryDirectory() as tmp:
            first=Path(tmp)/'old.xlsx'
            wb.save(first)
            legacy=TemplateWorkbook(first)
            changed=legacy.compact_existing_sources()
            self.assertEqual(changed,1)
            self.assertEqual(len(legacy.existing),2)
            retained=legacy.get_row(old[0])
            self.assertEqual(retained['Z'],'Stable candidate title')
            self.assertEqual(retained['U'],'Real - correct')
            self.assertEqual(retained['C'],'1')
            self.assertEqual(retained['L'],'Y')
            self.assertEqual(legacy.get_row(old[1]).get('A',''),'')
            self.assertEqual(legacy.get_row(old[2])['C'],'2')
            new=Path(tmp)/'new.xlsx'
            legacy.save(new)
            new_wb=TemplateWorkbook(new)
            self.assertEqual(len(new_wb.existing),2)
            self.assertEqual(new_wb.get_row(old[0])['U'],'Real - correct')
            with ZipFile(first) as before, ZipFile(new) as after:
                changed_files={name for name in before.namelist()
                               if before.read(name)!=after.read(name)}
            self.assertTrue(changed_files.issubset({
                legacy.sheet_names['Data_Extraction'],
                legacy.sheet_names['Query_Log']}))

    def test_conflicting_existing_green_values_raise_without_modification(self):
        wb, rows=self.make_old_workbook(conflict=True)
        with TemporaryDirectory() as tmp:
            old=Path(tmp)/'old.xlsx'
            wb.save(old)
            before=old.read_bytes()
            loaded=TemplateWorkbook(old)
            with self.assertRaisesRegex(ValueError,'conflicting Z'):
                loaded.compact_existing_sources()
            self.assertEqual(old.read_bytes(),before)
            self.assertEqual(loaded.get_row(rows[1])['U'],'Real - correct')

    def test_incremental_new_platform_and_same_source_in_second_question(self):
        wb=TemplateWorkbook(TEMPLATE)
        claude=unique_question_sources([
            citation('CLG','Q01',1,'https://example.org/paper'),
            citation('CLG','Q01',2,'https://example.org/paper'),
            citation('CLG','Q02',1,'https://example.org/paper'),
        ])
        for item in claude: wb.upsert_blue(item)
        with TemporaryDirectory() as tmp:
            first=Path(tmp)/'filled1.xlsx'
            wb.save(first)
            second=TemplateWorkbook(first)
            self.assertEqual(second.compact_existing_sources(),0)
            # Same source in new platform is a new workbook row; same source
            # again in Claude Q01 is NOT appended.
            incoming=unique_question_sources([
                citation('CLG','Q01',1,'https://example.org/paper'),
                citation('CGP','Q01',1,'https://example.org/paper'),
            ])
            for item in incoming:second.upsert_blue(item)
            self.assertEqual(len(second.existing),3)
            self.assertEqual(len({(key[0],key[1],source_key(
                second._source_record(row_dict(second.data_rows[rn]),rn)))
                for key,rn in second.existing.items()}),3)

    def test_stable_identity_prevents_order_shift_from_overwriting_other_source(self):
        wb=TemplateWorkbook(TEMPLATE)
        original=unique_question_sources([
            citation('CLG','Q01',1,'https://example.org/a','Paper A'),
            citation('CLG','Q01',2,'https://example.org/b','Paper B'),
        ])
        for item in original:wb.upsert_blue(item)
        later=unique_question_sources([
            citation('CLG','Q01',1,'https://example.org/b','Paper B'),
            citation('CLG','Q01',2,'https://example.org/c','Paper C'),
            citation('CLG','Q01',3,'https://example.org/a','Paper A'),
        ])
        for item in later:wb.upsert_blue(item)
        self.assertEqual(len(wb.existing),3)
        self.assertEqual([r['order'] for r in later],[2,3,1])
