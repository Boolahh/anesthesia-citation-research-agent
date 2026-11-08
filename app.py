"""Local upload UI for the existing reproducible CLI pipeline.

Launch: streamlit run app.py
"""
from __future__ import annotations
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import streamlit as st
from agent.workbook import TemplateWorkbook

ROOT=Path(__file__).resolve().parent
DEFAULT_TEMPLATE=ROOT/'template/AI_Citation_Bias_Extraction_Workbook.xlsx'

st.set_page_config(page_title='Anesthesia Citation Extraction',page_icon='📚',layout='wide')
st.title('Anesthesia Citation Extraction Agent')
st.caption('Local workflow • existing AI conversations → PDF hyperlinks → research metadata → original Excel template')
st.info('Use one PDF per question, or one combined PDF per AI tool (with each new question starting on a new page). Nothing is logged into automatically.')

try:
    sample=TemplateWorkbook(DEFAULT_TEMPLATE)
    tool_options=sample.data.tool_names
except Exception as exc:
    st.error('Template configuration could not be loaded: '+str(exc));st.stop()

with st.form('agent_form'):
    col1,col2=st.columns([2,1])
    with col1:
        uploads=st.file_uploader('Upload one or more original AI conversation PDFs',type=['pdf'],accept_multiple_files=True)
        wb_upload=st.file_uploader('Excel workbook (optional: use to continue previous runs)',type=['xlsx'])
        tool=st.selectbox('Which AI produced these responses?',list(tool_options),
                format_func=lambda key:f'{tool_options[key]} ({key})')
    with col2:
        stage=st.selectbox('Processing', ['blue','all','research'],index=0,
                   format_func=lambda x:'Citation copying only (blue)' if x=='blue' else 'Source research only (reviewed workbook)' if x=='research' else 'Copying + source research (green)')
        green_policy=st.selectbox('Research column policy',['verified-only','provisional'],index=0,
           format_func=lambda x:'Verified citations only (recommended)' if x=='verified-only' else 'Provisional: fill for review, not verified')
        offline=st.checkbox('Offline mode: no web/API calls',value=False)
        no_ai=st.checkbox('Do not use a paid AI API',value=False)
        max_sources=st.number_input('Limit source research to first N (0 = all)',min_value=0,max_value=3500,value=10)
        api_key=st.text_input('Optional OpenAI API key (local session only)',type='password',help='Never send a key via a chat message. It is passed only to the local process.')
    submit=st.form_submit_button('Run extraction',type='primary',use_container_width=True)

if submit:
    if not uploads:
        st.error('Upload at least one PDF first.')
    else:
        with st.spinner('Reading citations and producing the workbook...'):
            try:
                with tempfile.TemporaryDirectory(prefix='citation_agent_') as temp:
                    home=Path(temp);inputs=home/'inputs'/tool;inputs.mkdir(parents=True)
                    for upload in uploads:
                        # Ignore path separators / questionable filenames.
                        name=Path(upload.name).name
                        (inputs/name).write_bytes(upload.getvalue())
                    template=home/'template.xlsx'
                    template.write_bytes(wb_upload.getvalue() if wb_upload else DEFAULT_TEMPLATE.read_bytes())
                    output=home/'finished.xlsx'; reports=home/'reports'
                    cmd=[sys.executable,str(ROOT/'run_agent.py'),'run',
                         '--input',str(home/'inputs'),'--tool',tool,
                         '--template',str(template),'--output',str(output),
                         '--report-dir',str(reports),'--stage',stage,
                         '--green-policy',green_policy,'--max-sources',str(max_sources)]
                    if offline:cmd.append('--offline')
                    if no_ai:cmd.append('--no-ai')
                    env=os.environ.copy()
                    if api_key:env['OPENAI_API_KEY']=api_key
                    proc=subprocess.run(cmd,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                        timeout=3600,cwd=str(ROOT))
                    if proc.returncode!=0:
                        st.error('Processing failed. See diagnostic output below.')
                        st.code(proc.stdout[-8000:])
                    else:
                        report=json.loads((reports/'run_report.json').read_text(encoding='utf-8'))
                        st.success('Workbook created. Source facts still require human review.')
                        st.metric('Citations extracted',report['citations_extracted'])
                        st.metric('Sources researched',report['sources_researched'])
                        st.metric('Review warnings',report['warning_count'])
                        st.download_button('Download filled Excel workbook',output.read_bytes(),
                                file_name='citation_extraction_filled.xlsx',
                                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                use_container_width=True)
                        st.download_button('Download run report (JSON)',(reports/'run_report.json').read_bytes(),
                                file_name='run_report.json',mime='application/json',use_container_width=True)
                        st.download_button('Download citation preview (CSV)',(reports/'citation_preview.csv').read_bytes(),
                                file_name='citation_preview.csv',mime='text/csv',use_container_width=True)
                        with st.expander('Processing log'):
                            st.code(proc.stdout[-12000:])
                        if report['warning_count']:
                            with st.expander('Warnings requiring manual review'):
                                st.json(report['warnings'][:100])
            except subprocess.TimeoutExpired:
                st.error('The process exceeded the local UI timeout. Run the CLI to resume research in batches.')
            except Exception as exc:
                st.error(type(exc).__name__+': '+str(exc))

st.divider()
st.caption('Human reviewers own the verdict columns, gender/race fields, and final validation. No system can safely infer a citation is real merely because a link opens.')
