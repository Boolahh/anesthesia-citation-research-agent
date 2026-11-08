"""Local-only study assistant for up to 16 AI-model PDFs and reviewer workbooks.

The UI never uploads conversation PDFs or API keys to GitHub. All downloads
survive Streamlit reruns; a full page reload can clear the current session.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZIP_DEFLATED
import csv
import json
import os
import subprocess
import sys
import tempfile

import streamlit as st
from agent.workbook import TemplateWorkbook

ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx'
MAX_FILES = 240
MAX_FILE_SIZE = 50_000_000
MAX_TOTAL_SIZE = 300_000_000


def store_pdfs(uploads, destination):
    """Handle single PDFs and nested tool-code ZIPs with zip-slip/size protection."""
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    seen = set()
    total = 0

    def add(relative, data):
        nonlocal total
        if len(data) > MAX_FILE_SIZE:
            raise ValueError(f'PDF exceeds 50 MB limit: {relative}')
        total += len(data)
        if total > MAX_TOTAL_SIZE or len(saved) >= MAX_FILES:
            raise ValueError('Input batch exceeds the safe size/count limits (300 MB or 240 PDFs)')
        parts = PurePosixPath(str(relative).replace('\\', '/'))
        if parts.is_absolute() or '..' in parts.parts or not parts.parts or any(x.startswith('.') for x in parts.parts):
            raise ValueError(f'Unsafe input filename: {relative}')
        if parts.suffix.lower() != '.pdf':
            raise ValueError('Only PDF files may be extracted into the input folder')
        target = dest.joinpath(*parts.parts)
        try:
            target.resolve().relative_to(dest.resolve())
        except ValueError as exc:
            raise ValueError('Unsafe archive path') from exc
        if str(target).lower() in seen:
            raise ValueError(f'Duplicate PDF filename in upload: {relative}')
        seen.add(str(target).lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        saved.append(target)

    for upload in uploads:
        data = upload.getvalue()
        original = Path(upload.name).name
        if original.lower().endswith('.pdf'):
            add(original, data)
        elif original.lower().endswith('.zip'):
            with ZipFile(BytesIO(data)) as z:
                entries = [e for e in z.infolist() if not e.is_dir() and e.filename.lower().endswith('.pdf')]
                if len(entries) > MAX_FILES or sum(e.file_size for e in entries) > MAX_TOTAL_SIZE:
                    raise ValueError('ZIP contains too many PDFs or too much uncompressed data')
                for entry in entries:
                    if entry.file_size > MAX_FILE_SIZE:
                        raise ValueError('ZIP contains an oversized PDF')
                    # Do not allow Unix symlinks or any archive traversal.
                    if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('ZIP symlink entries are not allowed')
                    with z.open(entry) as stream:
                        add(entry.filename, stream.read(MAX_FILE_SIZE+1))
        else:
            raise ValueError('Only .pdf and .zip uploads are supported')
    return saved


def result_zip(report_dir, workbook):
    """Package reviewer-ready artifacts, never raw PDFs or API keys."""
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as z:
        z.writestr('citation_extraction_filled.xlsx', Path(workbook).read_bytes())
        for name in ('run_report.json', 'citation_preview.csv', 'review_queue.csv',
                     'research_proposals.json', 'citations_extracted.json', 'research_audit.csv',
                     'geography_review.csv', 'source_quality_review.csv', 'source_level_research.csv'):
            candidate = Path(report_dir)/name
            if candidate.exists():
                z.write(candidate, name)
    return output.getvalue()


def run_locally(command, environment):
    """Run in a subprocess and retain logs for diagnosis; no secrets in stdout."""
    return subprocess.run(command, env=environment, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=3600, cwd=str(ROOT))


st.set_page_config(page_title='Anesthesia Citation Research Agent', page_icon='📚', layout='wide')
st.title('Anesthesia Citation Research Agent')
st.caption('PDF citation capture → bibliographic evidence → original research workbook → human review')
st.info('Local processing. Works with PDF exports from all 16 platforms in the study. Citations hidden by an AI interface or missing from a PDF cannot be reconstructed reliably without additional evidence.')

try:
    blank = TemplateWorkbook(DEFAULT_TEMPLATE)
    model_options = blank.data.tool_names
except Exception as exc:
    st.error('Cannot load original study template: '+str(exc))
    st.stop()

with st.form('agent_form'):
    left, right = st.columns([2, 1])
    with left:
        uploads = st.file_uploader('Original AI conversations — multiple PDFs or a ZIP of model-code folders',
                                   type=['pdf', 'zip'], accept_multiple_files=True,
                                   help='For mixed models, upload a ZIP with folders named CGP, CLG, GEM, OEV, etc. or use descriptive filenames.')
        wb_upload = st.file_uploader('Reviewed Excel workbook (optional for copying, required for research-only)', type=['xlsx'])
        journal_upload = st.file_uploader('Optional verified SCImago / licensed 2026 JCR journal evidence CSV', type=['csv'])
        choices = list(model_options)+['AUTO']
        tool = st.selectbox('Which AI produced the responses?', choices,
            format_func=lambda c: 'Auto-detect model from PDF filename / ZIP folder' if c == 'AUTO' else f'{model_options[c]} ({c})')
    with right:
        stage = st.selectbox('Processing stage', ['blue', 'all', 'research'],
            format_func=lambda v: {'blue': 'Copy original citations (blue)',
               'all': 'Copy + research publications (green)',
               'research': 'Research an existing reviewed workbook (no PDFs needed)'}[v])
        policy = st.selectbox('Green-column policy', ['verified-only', 'provisional'],
            format_func=lambda v: 'Only human-verified real sources (recommended)' if v == 'verified-only' else 'Provisional source proposals (requires review)')
        offline = st.checkbox('Offline: no web / API requests', value=False)
        no_ai = st.checkbox('Do not use paid AI API', value=True)
        max_sources = st.number_input('Maximum publication research lookups (0 = all)',
                                      min_value=0, max_value=3500, value=10,
                                      help='10 (default) attempts only the first 10 eligible citations. '
                                           'Set 0 to research every eligible citation in the uploaded documents.')
        st.caption('Research limit defaults to 10 for a small pilot. **Set it to 0 for all citations.**')
        api_key = st.text_input('OpenAI API key (optional, local session)', type='password',
             help='Never paste your API key into chat; the local process reads it only in memory.')
    submit = st.form_submit_button('Run study extraction', type='primary', use_container_width=True)

if submit:
    st.session_state.pop('latest_result', None)
    if stage in ('blue', 'all') and not uploads:
        st.error('Upload at least one PDF or ZIP for citation copying.')
    elif stage == 'research' and wb_upload is None:
        st.error('Select the previously reviewed workbook for research-only processing.')
    else:
        with st.spinner('Processing documents and preparing research files...'):
            try:
                with tempfile.TemporaryDirectory(prefix='anesthesia_citations_') as tmp:
                    home = Path(tmp)
                    input_dir = home/'inputs'
                    if uploads:
                        stored = store_pdfs(uploads, input_dir)
                        if stage != 'research' and not stored:
                            raise ValueError('The selected archive contained no PDF files')
                    else:
                        input_dir.mkdir(parents=True)
                    template = home/'template.xlsx'
                    template.write_bytes(wb_upload.getvalue() if wb_upload else DEFAULT_TEMPLATE.read_bytes())
                    output, reports = home/'filled.xlsx', home/'reports'
                    if journal_upload is not None:
                        journal_path = home/'journal_evidence.csv'
                        journal_path.write_bytes(journal_upload.getvalue())
                    command = [sys.executable, str(ROOT/'run_agent.py'), 'run',
                               '--input', str(input_dir), '--template', str(template),
                               '--output', str(output), '--report-dir', str(reports),
                               '--stage', stage, '--green-policy', policy,
                               '--max-sources', str(max_sources)]
                    if tool != 'AUTO':
                        command.extend(['--tool', tool])
                    if journal_upload is not None:
                        command.extend(['--journal-evidence', str(journal_path)])
                    if offline:
                        command.append('--offline')
                    if no_ai:
                        command.append('--no-ai')
                    env = os.environ.copy()
                    if api_key:
                        env['OPENAI_API_KEY'] = api_key
                    proc = run_locally(command, env)
                    if proc.returncode:
                        st.error('The run failed; processing log below.')
                        st.code(proc.stdout[-12000:])
                    else:
                        report = json.loads((reports/'run_report.json').read_text(encoding='utf-8'))
                        preview = (reports/'citation_preview.csv').read_bytes()
                        review = (reports/'review_queue.csv').read_bytes()
                        result = {
                            'report': report, 'workbook': output.read_bytes(),
                            'run_report': (reports/'run_report.json').read_bytes(),
                            'citation_preview': preview, 'review_queue': review,
                            'research_audit': (reports/'research_audit.csv').read_bytes(),
                            'geography_review': (reports/'geography_review.csv').read_bytes(),
                            'source_quality': (reports/'source_quality_review.csv').read_bytes(),
                            'source_level': (reports/'source_level_research.csv').read_bytes(),
                            'package': result_zip(reports, output),
                            'log': proc.stdout[-14000:],
                        }
                        st.session_state['latest_result'] = result
            except subprocess.TimeoutExpired:
                st.error('The run exceeded one hour; use the CLI with a smaller source batch to resume.')
            except Exception as exc:
                st.error(f'{type(exc).__name__}: {exc}')

result = st.session_state.get('latest_result')
if result:
    report = result['report']
    st.subheader('Latest run — results and review')
    st.success('The output is ready. Green fields are provisional until independently checked by a human reviewer.')
    st.caption('All downloads stay available after each click. Closing/reloading the browser tab can clear this temporary session.')
    cols = st.columns(5)
    for i, (title, value) in enumerate((
        ('Citation candidates', report['citations_extracted']),
        ('Research candidates', report['sources_researched']),
        ('Metadata found', report.get('sources_with_metadata', 0)),
        ('Green values in workbook', report.get('informative_green_cells_in_output_workbook', 0)),
        ('Review items', report.get('review_queue_items', report['warning_count'])),
    )):
        cols[i].metric(title, value)
    st.caption('Green values counts substantive cell contents, not NR / NOT FOUND placeholders. All research values remain provisional until reviewed.')
    if 'distinct_sources_researched' in report:
        st.caption(
            f"Unique-source analysis: {report['distinct_sources_researched']} source identities researched "
            f"across {report['sources_researched']} citation occurrences; "
            f"{report['distinct_sources_with_green']} distinct sources have substantive green data."
        )
    if 'first_author_country_rows' in report:
        st.caption(
            f"Geographic outcome coverage: first-author country for "
            f"{report['first_author_country_rows']}/{report['citations_extracted']} citations; "
            f"last-author country for {report.get('last_author_country_rows', 0)}/"
            f"{report['citations_extracted']}. Provisional country matches require human verification."
        )
    if report.get('short_or_generic_source_labels'):
        st.warning(
            f"Citation evidence needs review: {report['short_or_generic_source_labels']} "
            f"short/domain-only link labels among {report['citations_extracted']} citation occurrences. "
            f"The report identifies {report.get('distinct_sources_within_questions', '?')} "
            f"distinct source identities within questions. Review source_quality_review.csv "
            f"before treating occurrence counts as unique scholarly references."
        )
    if report.get('research_truncated_by_limit'):
        st.warning(
            f"Research stopped at your limit of {report.get('publication_lookup_limit')}. "
            f"Only {report['sources_researched']} of {report['eligible_sources_for_research']} "
            f"eligible citations were attempted. Set Maximum publication research lookups to **0** "
            f"and rerun to research all eligible citations."
        )
    if report.get('sources_researched'):
        st.caption(
            f"Bibliographic lookup results: {report.get('external_lookup_successes', 0)} "
            f"fresh network successes, {report.get('cached_lookup_reuses', 0)} "
            f"local-cache reuses. Reused metadata is not freshly verified."
        )
    st.download_button('Download full evidence package (ZIP)', result['package'],
        file_name='anesthesia_citation_research_package.zip', mime='application/zip',
        use_container_width=True)
    a, b = st.columns(2)
    with a:
        st.download_button('Download filled Excel workbook', result['workbook'],
            file_name='citation_extraction_filled.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', use_container_width=True)
        st.download_button('Download run report (JSON)', result['run_report'],
            file_name='run_report.json', mime='application/json', use_container_width=True)
    with b:
        st.download_button('Download citation preview (CSV)', result['citation_preview'],
            file_name='citation_preview.csv', mime='text/csv', use_container_width=True)
        st.download_button('Download manual review queue (CSV)', result['review_queue'],
            file_name='review_queue.csv', mime='text/csv', use_container_width=True)
        st.download_button('Download per-citation research audit (CSV)', result['research_audit'],
            file_name='research_audit.csv', mime='text/csv', use_container_width=True)
        st.download_button('Download first-author geography review (CSV)', result['geography_review'],
            file_name='geography_review.csv', mime='text/csv', use_container_width=True)
        st.download_button('Download citation source-quality review (CSV)', result['source_quality'],
            file_name='source_quality_review.csv', mime='text/csv', use_container_width=True)
        st.download_button('Download unique-source research summary (CSV)', result['source_level'],
            file_name='source_level_research.csv', mime='text/csv', use_container_width=True)
    if report.get('tools_detected'):
        with st.expander('Model and question coverage'):
            st.json(report['tools_detected'])
    with st.expander('Processing log'):
        st.code(result['log'])
    if report.get('warning_count'):
        with st.expander('Warnings requiring review'):
            st.json(report['warnings'][:200])

st.divider()
st.caption('Human reviewers control the citation verdict, link validity, demographics, and final study coding. DOI/title metadata is not proof that a cited source was correct.')
