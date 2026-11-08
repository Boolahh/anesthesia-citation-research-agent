"""Regression: all three downloads remain available after a Streamlit rerun."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
import json
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]


class TestDownloadPersistence(TestCase):
    def test_downloads_survive_a_rerun_without_reprocessing_pdfs(self):
        st = MagicMock()
        st.session_state = {}
        st.columns.side_effect = lambda spec: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
        st.file_uploader.side_effect = [[SimpleNamespace(name='Q01_sample.pdf', getvalue=lambda: b'%PDF-example')], None, None] * 2
        st.selectbox.side_effect = ['CGP', 'blue', 'verified-only'] * 2
        st.checkbox.return_value = True
        st.number_input.return_value = 10
        st.text_input.return_value = ''
        st.form_submit_button.side_effect = [True, False]

        class FakeTemplate:
            def __init__(self, path):
                self.data = SimpleNamespace(tool_names={'CGP': 'ChatGPT'})

        ran = []

        def fake_process(command, **kwargs):
            ran.append(command)
            output = Path(command[command.index('--output') + 1])
            reports = Path(command[command.index('--report-dir') + 1])
            reports.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b'filled-xlsx-for-testing')
            (reports / 'citation_preview.csv').write_text('question,source\nQ01,test\n')
            (reports / 'review_queue.csv').write_text('tool,question,reason\nCGP,Q01,example\n')
            (reports / 'research_audit.csv').write_text('tool,question,research_status\nCGP,Q01,not_researched\n')
            (reports / 'geography_review.csv').write_text('tool,question,review_priority\nCGP,Q01,High\n')
            (reports / 'source_quality_review.csv').write_text('tool,question,review_priority\nCGP,Q01,High\n')
            (reports / 'source_level_research.csv').write_text('tool,question,citation_occurrences\nCGP,Q01,1\n')
            (reports / 'run_report.json').write_text(json.dumps({
                'citations_extracted': 1,
                'sources_researched': 0,
                'warning_count': 1,
                'warnings': [{'warning': 'example'}],
            }))
            return SimpleNamespace(returncode=0, stdout='[SUMMARY] complete')

        real_read_bytes = Path.read_bytes

        def read_bytes(self):
            if self.name == 'AI_Citation_Bias_Extraction_Workbook.xlsx':
                return b'blank-template-for-testing'
            return real_read_bytes(self)

        sys.path.insert(0, str(ROOT))
        try:
            with patch.dict(sys.modules, {'streamlit': st}), \
                 patch('agent.workbook.TemplateWorkbook', FakeTemplate), \
                 patch('subprocess.run', side_effect=fake_process), \
                 patch.object(Path, 'read_bytes', read_bytes):
                runpy.run_path(str(ROOT / 'app.py'), run_name='__main__')
                self.assertEqual(st.download_button.call_count, 9)
                self.assertEqual(len(ran), 1)
                self.assertEqual(st.session_state['latest_result']['workbook'], b'filled-xlsx-for-testing')
                # A click on a download button reruns the Streamlit app,
                # but does not resubmit the form or delete its saved output.
                runpy.run_path(str(ROOT / 'app.py'), run_name='__main__')
                self.assertEqual(st.download_button.call_count, 18)
                self.assertEqual(len(ran), 1)
                names = [c.kwargs['file_name'] for c in st.download_button.call_args_list[-9:]]
                self.assertEqual(names, ['anesthesia_citation_research_package.zip', 'citation_extraction_filled.xlsx', 'run_report.json', 'citation_preview.csv', 'review_queue.csv', 'research_audit.csv', 'geography_review.csv', 'source_quality_review.csv', 'source_level_research.csv'])
        finally:
            sys.path.remove(str(ROOT))
