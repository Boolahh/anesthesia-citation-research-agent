# Anesthesia Citation Bias Extraction Agent

A working, local Python research automation package for the supplied **AI Citation Bias in Anesthesia** extraction template. It accepts exported AI-chat PDFs with their original hyperlinks, extracts citations into columns **A–L**, looks up bibliographic records from public databases, optionally uses an LLM to code research metadata into columns **Z–BF**, and leaves reviewer-only columns alone.

**This is a research data-entry agent, not a clinical decision tool. Every AI-coded fact requires human review, as specified in the study protocol.** It deliberately does **not** mark any citation as real, hallucinated, or accurate automatically.

## Contents

- `run_agent.py` — batch processing CLI (no browser accounts required)
- `app.py` — optional local web interface to upload one or more PDFs, choose an AI tool, and download Excel
- `agent/pdf_extract.py` — PDF hyperlink/citation extraction and original-reference handling
- `agent/research.py` — public Crossref, OpenAlex, Europe PMC, and accessible webpage metadata extraction
- `agent/llm.py` — optional OpenAI structured-JSON citation extraction / research coding
- `agent/workbook.py` — surgical edits to the original template, preserving all other sheets and formulas
- `inputs/<TOOL_CODE>/` — **local-only** original AI conversation exports (not included in the GitHub repository)
- `template/` — the original blank workbook stored losslessly as `.xlsx.gz`, expanded automatically on first use
- `outputs/` — generated workbooks, CSV previews, and audit JSON reports (**local-only**, ignored by Git)
- `tests/` — automated validation tests

## Windows quick start (local upload interface)

1. Clone or download this GitHub repository. Install Python 3.11+ from python.org, enabling **Add Python to PATH**. The exact blank workbook is included in `.xlsx.gz` form and expands automatically on first use.
2. Double-click `run_windows.bat`. It creates a virtual environment, installs the requirements, and starts the local Streamlit interface in a browser.
3. Choose the model that produced the answers (e.g. ChatGPT / `CGP`). Upload one or more original chat PDFs; you may upload **one combined PDF containing Q1–Q12** if each question starts on a new page, or 12 separate PDFs.
4. Choose **Citation copying only** to create the blue data first. After a human reviewer checks the original citations, marks column **U** with an actual real-source verdict, and provides **X** where appropriate, upload that reviewed workbook and use **Source research only**. No login details are needed.
5. Download the generated `.xlsx` and inspect the warning report before using it for analysis.

For a small accelerated demonstration, select **Copying + source research** and **Provisional** to populate unverified green proposals in addition to the blue cells. The human reviewer must still verify them; proposals are **not** classified as real by the agent.

### Optional AI API key

Copy `.env.example` to `.env` and set `OPENAI_API_KEY=...` locally, or enter a key in the local upload interface. **Never paste keys or account passwords into a chat.** The key is optional for the PDF/citation-copying phase. Without a key, research coding still attempts public structured metadata from the cited sources, but many complex green fields remain `NR` or `NOT FOUND`.

This tool uses the [OpenAI Responses API](https://developers.openai.com/api/docs/guides/structured-outputs) for optional structured JSON extraction. Model name can be changed using `OPENAI_MODEL`.

## Command-line use (PowerShell; every command is a single line)

Run from the unzipped project folder after starting the virtual environment (`.venv\Scripts\Activate.ps1`):

```powershell
python -m pip install -r requirements.txt
python run_agent.py scan --no-ai
python run_agent.py run --stage blue --no-ai --offline
python run_agent.py run --stage all --max-sources 10 --green-policy provisional
python run_agent.py run --stage research --template outputs/citation_extraction_filled.xlsx --output outputs/after_human_verification.xlsx --green-policy verified-only
python -m unittest discover -s tests -v
```

* `scan` creates `outputs/citation_preview.csv`, `outputs/citations_extracted.json`, and `outputs/scan_report.json`, but no workbook.
* `--stage blue` fills A–L and a limited amount of `Query_Log` metadata. It never changes user-entered query date, reviewer details, or other human fields.
* `--stage all` performs both stages. By default the green phase only writes rows with a reviewer-entered verdict of `Real - correct` or `Real - citation has errors`; without these, it still writes metadata research suggestions to `outputs/research_proposals.json`.
* `--green-policy provisional` permits preliminary, **unverified** green coding. This is for testing only; do not interpret as verification.
* `--stage research` uses all existing blue rows in the supplied workbook, favoring reviewer-verified link X over the model's link E.
* `--no-ai` disables the paid model but still allows public bibliographic lookups. `--offline` disables all network requests.
* `--max-sources 10` keeps the online prototype small. Omit (or use 0) to attempt all sources.
* `--tool CGP` sets the tool code if PDFs aren't in an `inputs/CGP/` folder. For other models, place PDFs under `inputs/CLG/` (Claude), `inputs/GEM/` etc.; check tool codes in the supplied `Tools` tab.
* **Never** use the same file path for `--template` and `--output`. The agent refuses to overwrite the original workbook.

## Best data-collection method

Export/print each original AI response to PDF **with clickable links intact**, keeping its original text and reference order. The agent reads the PDF's hyperlink annotations using PyMuPDF, so it doesn't need to log into AI websites. Place PDFs under `inputs/<tool-code>/`. The PDFs can be one-per-question or combined per tool. For a combined export, start each Q1–Q12 response on a **new page**. If question detection fails, name single-question exports `Q01_...pdf`, `Q02_...pdf`, etc.

**Do not correct citations before extraction.** The study measures wrong citations and hallucinations. When PDF export hides an additional citation under `+1`, loses a hyperlink, or gives only a generic label such as `PMC`, the agent records a warning. It does **not** fabricate a missing reference or mark it as hallucinated. Some named but unlinked publications can be captured as text-only rows with URL=`NR`.

In the initial offline pilot (12 separately exported ChatGPT responses), the parser recovered **33 candidate citation entries** and **28 clickable URLs**. These sample files and outputs are **not committed to GitHub**. The count is not a verified citation census: compressed `+N` labels and missing PDF annotations require manual inspection. Upload local PDF exports to reproduce and check the preview file for citation order, tool/question, and source links.

## Research / green-column coverage

Public Crossref, Europe PMC, and OpenAlex APIs can provide actual titles, DOIs, PMIDs, years, paper types, citation counts, author names, some institutional affiliations, and open-access metadata. Optional AI coding can infer appropriate allowed study-design and subspecialty labels **from retrieved evidence**, when possible. Unavailable information is marked `NOT FOUND` / `NR` according to the original worksheet rules.

Important gaps that the agent **does not guess**:

- The 2026 Journal Citation Reports impact factor is left blank without a licensed verified JCR value.
- Journal origin country requires an independently confirmed SCImago entry; it is never inferred from the publisher's headquarters.
- Corresponding author identity, most-recent institutional affiliation, author countries, funding, and open-access subtype may require review of full text.
- The agent does not fill human-only citation-verification statuses, link verdicts, gender, race/ethnicity, or reviewer accuracy flags.

Metadata returned by a DOI lookup or a working URL is **not proof** that the AI citation was accurate. Human confirmation of the citation-to-source match is mandatory. Duplicate source *occurrences* are preserved when visible in separate reference entries.

## Review the output before publication

`outputs/run_report.json` includes warnings and counts. `outputs/research_proposals.json` holds preliminary 33-field metadata suggestions even if the green sheet is gated pending a human verdict. `outputs/citation_preview.csv` helps review the original text. The original `Statistician_Dataset`, data validation, sheet styles, and formulas are preserved; Excel recalculates its own formulas when you open the saved workbook.

A full online run can take much longer than the MVP setup if hundreds of sites are inaccessible, paid subscriptions are needed, or many citations require manual verification. Be mindful of third-party AI and database usage terms, especially when processing licensed clinical-reference responses via external APIs.

## Current test coverage

The included unit tests check PDF hyperlink extraction, Q identification, combined PDFs, original workbook part preservation, idempotence, human-verdict gates, public-URL safety and geographic mapping. The **offline citation-copying phase was exercised against the initial 12 supplied PDFs**; these study inputs are intentionally excluded from the repository. The full source-research phase depends on internet access, external APIs, source availability and (optionally) your API key; it must be validated against a reviewed set of real publications in your environment before bulk use.

## Repository privacy and scope

This repository tracks only source code, tests, documentation, and the original blank workbook losslessly compressed as `.xlsx.gz`. The runtime-expanded `.xlsx` is ignored by Git. **Do not commit** passwords, session cookies, account exports, original AI answers, processed research datasets, or API keys. In research deployments, maintain the repository as private unless the study team approves publication. See `docs/ARCHITECTURE.md` and `docs/VALIDATION.md`.
