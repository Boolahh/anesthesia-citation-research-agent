# Anesthesia Citation Research Agent

**Research-grade, reviewer-supervised extraction pipeline for the original AI-mediated anesthesia evidence study.** Ingest exported AI conversations as PDFs (or ZIPs of PDFs), preserve *as-cited* references and hyperlinks, research actual source records, write the exact original 70+ column study workbook, and generate evidence and manual-review artifacts. Runs locally on Windows, macOS or Linux.

**Important:** This is a scientific data-extraction assistant—not a clinical decision tool, plagiarism verifier, or proof that an AI citation exists. A human reviewer must verify every claim used in study analysis. No agent can recover a reference hidden by the AI provider's interface or missing from the PDF with certainty.

## Supported AI platforms (the exact 16 study tool codes)

| Study code | Platform | Study code | Platform |
|---|---|---|---|
| CGP | ChatGPT | CGC | ChatGPT for Clinicians |
| CLG | Claude | CKA | ClinicalKey AI |
| CON | Consensus | DSK | DeepSeek |
| DOX | Doximity Ask | DRI | DR. INFO |
| DYN | Dyna AI (DynaMed) | GLA | Glass Health |
| GEM | Google Gemini | HEI | Heidi Evidence |
| COP | Microsoft Copilot | OEV | OpenEvidence |
| UTD | UpToDate Expert AI | VER | Vera Health |

The 12 standardized questions and 16 platform definitions are read *directly* from the original study workbook, not duplicated in code. The extraction engine supports original PDF hyperlinks, printed URLs/DOIs/PMIDs, numbered and bulleted references, multi-page responses, and optional evidence-constrained AI transcription. Unknown layouts or hidden sources are flagged for a human rather than silently guessed. **Only the ChatGPT sample export format supplied to this project has been tested end-to-end; each other platform needs a pilot QA check before research-scale use.**

## Windows quick start (VS Code or Git Bash)

1. Clone the private repository and install **Python 3.11+**.
2. Run `run_windows.bat` from File Explorer or `./run_windows.bat` from Git Bash. It creates `.venv`, installs packages and starts Streamlit, usually at `http://localhost:8501`.
3. Upload PDFs for one platform; choose its tool code. For **multiple platforms in one batch**, choose **Auto-detect** and upload a ZIP containing folders named `CGP/`, `OEV/`, `GEM/`, etc. (or name each PDF with its platform).
4. Select **Copy original citations (blue)** for the first quality-control pass, turn **Offline** on, and keep **No paid AI** selected. Use the review queue and citation preview to check every original source occurrence.
5. Select **Copy + research (green)** to independently look up bibliographic sources. By default **verified-only** does *not* fill green columns without an actual reviewer verdict in U. To test candidate green metadata before verification, select **provisional** and later verify every populated field.
6. Download the **Complete evidence package ZIP** for the XLSX, CSV citation preview, review queue, reports and field-level metadata provenance. Each individual download also stays available within the same browser session.
7. A collaborator can review the original reference and fill T–Y, BG–BR in Excel, or use the optional validated reviewer CSV workflow below. Then run research-only with the reviewed workbook, without needing the original PDFs again.

### macOS and Linux

Run `./run_unix.sh` in a terminal. Both launchers use a local virtual environment.

## What exactly gets written

- **A–L (blue):** the citation as displayed, original link as displayed, original title/author/year/journal/DOI/PMID and whether the reference was repeated. Links in this area are never replaced by a publisher URL found later.
- **M–Y (human only):** tool metadata, human source-verdict in U, reference error category, independently verified URL in X and audit status; never inferred by the agent.
- **Z–BF (green):** *proposed* real-source bibliographic fields, using DOI/PMID, PubMed EFetch, Europe PMC, Crossref, OpenAlex and public publisher metadata. Includes field-level source URLs in `research_proposals.json`. The agent does not accept a database lookup as proof that a citation is correct.
- **BG–BR (human only):** gender, race/ethnicity, checking the proposed green fields, and reviewer notes; never inferred or overwritten by the agent.
- Other workbook sheets/formulas/styles/dropdowns are maintained by narrowly editing only the `Data_Extraction` and `Query_Log` worksheet XML.

### Affiliation safeguards

The system reads PubMed XML **author by author** and rejects repeated composite paragraphs that actually list multiple authors' institutions. It refuses to assign an institution to an author just because another author lists it, and refuses to pick the "most recent" institution from several affiliations when chronology is unknown. OpenAlex affiliations are retained as possible research clues but **are not automatically used** for the first, last or corresponding author's recorded institution or country. Journal country is not substituted with publisher headquarters. Explicit countries must appear at the end of an affiliation, not only inside a university name; ambiguous country names are withheld. The official issue year is preferred over online-first year when PubMed supplies both, with this choice documented in provenance.

### Unavailable or licensed research fields

Without verified SCImago data, journal origin is `NOT FOUND`; 2026 Journal Citation Reports impact factor (BE) is blank without a licensed verified value. Missing/restricted publications, ambiguous author roles, explicit funding statements and corresponding authors often require a reviewer or full-text access. An AI API is not a substitute for those records. Publication counts reflect time-of-lookup OpenAlex data and may change; metadata is provisional.

## CLI reference (one-line commands from the project root)

```powershell
python -m pip install -r requirements-ui.txt
python -m unittest discover -s tests -v
python run_agent.py scan --input inputs --no-ai --offline
python run_agent.py run --stage blue --input inputs --output outputs/blue.xlsx --no-ai --offline
python run_agent.py run --stage all --input inputs --output outputs/provisional.xlsx --max-sources 10 --green-policy provisional --no-ai
python run_agent.py run --stage research --template outputs/reviewed.xlsx --output outputs/researched.xlsx --green-policy verified-only --max-sources 30 --no-ai
```

To process a single model whose filenames have no platform identifier, pass `--tool OEV` (or another exact tool code). For mixed models, use subfolders, e.g. `inputs/CGP/Q01.pdf`, `inputs/GEM/Q01.pdf`. For one question per file, include its question code (`Q01_...pdf`) if the prompt text is missing. A *combined* PDF can be detected when each full new question begins on a new page. If several questions share one page, split the PDF first rather than allowing the agent to guess.

The `scan` command creates a preview and scan report without an XLSX. All `run` commands preserve an existing reviewer workbook; **never** use the same `--template` and `--output` path. The `--offline` flag disables all network research (even if an API key is set). `--no-ai` disables the paid language model but allows Crossref, Europe PMC, PubMed and OpenAlex unless `--offline` is also set. `--max-sources 0` means all eligible sources. A failed online lookup is recorded as missing, not coded as a hallucination. Network/cache data and study output remain local.

### Human review CSV (optional)

```powershell
python review_workbook.py --workbook outputs/blue.xlsx --export-review-template outputs/review_template.csv
python review_workbook.py --workbook outputs/blue.xlsx --decisions outputs/review_template.csv --output outputs/reviewed.xlsx
```

A human edits the exported CSV, selecting exact workbook dropdown values such as `Real - correct` or `Cannot verify - not enough detail`. Empty cells leave existing values untouched. The script validates all decisions **before** changing any row, refuses to overwrite previously entered reviewer fields unless `--allow-review-overwrite` is expressly provided, and writes a `.review_audit.json` file with input hashes and changed columns. This is not an automated citation-verification step.

## APIs (optional; no API key required for blue extraction)

Copy `.env.example` to `.env` **on your computer only**. `OPENAI_API_KEY` enables the optional paid structured model extraction; select `OPENAI_MODEL` for your account. `OPENALEX_API_KEY` is a separate OpenAlex credential that may improve rate limits. `RESEARCH_CONTACT_EMAIL` provides an appropriate public research contact for NCBI and other APIs. Do **not** post credentials in chat or commit `.env`.

The OpenAI model must transcribe only citations present in the original PDF text or its URI annotations. It cannot add invented source URLs or declare a citation real. If it fails, the deterministic parser remains available. Public APIs can have access controls and quota changes; failures are reported in source lookup events.

## Output files and research traceability

The main Streamlit download is `anesthesia_citation_research_package.zip`, containing:

- `citation_extraction_filled.xlsx` — original template filled only in permitted columns
- `citation_preview.csv` — source-by-source transcription and PDF page
- `review_queue.csv` — missing links, uncertain metadata, hidden references and other actions
- `research_audit.csv` — one row per original citation showing whether source research was skipped, unavailable, disputed, proposed, or written; counts *informative* fields and lists supporting databases
- `run_report.json` — question/platform coverage, warnings, source counts and pipeline version
- `research_proposals.json` — 33 proposed values per eligible source, field-level provenance, source lookup statuses and review flags
- `citations_extracted.json` — original records, including PDF SHA-256, extraction method and confidence

No original model-response PDFs, published-study protocol or research participant data is committed to GitHub. `inputs/`, `outputs/`, `cache/` and `.env` are ignored. The **original blank workbook is stored losslessly** as `template/AI_Citation_Bias_Extraction_Workbook.xlsx.gz` and expanded automatically on first use. Keep the repository private until the investigators approve sharing.

## Validation & limitations

GitHub Actions runs the automated regression suite on Python 3.11/3.12/3.13. Tests include synthetic PDF URI annotations, visible URL-only lists, combined files, all 16 tool identifiers, missing links, PubMed author-specific affiliations, missing data, review-only resume, reviewer change protection, workbook OOXML preservation and persistent downloads. The historical 12-file ChatGPT pilot yields **33 candidate citations and 28 preserved original links**, with `+N` citation groups and missing hyperlinks requiring manual reconciliation. **This is not a verified citation census.**

Before analyzing outputs from any new AI platform, review a small set manually, especially tools that display **sources searched** separately from **sources cited**, platforms that collapse or hide links, and scanned PDFs. A screenshot-only PDF with no selectable text or links is flagged as needing OCR/re-export, not fabricated. See `docs/ARCHITECTURE.md`, `docs/VALIDATION.md` and `docs/PROTOCOL_MAPPING.md`.

### Bibliographic lookup and trust improvements (v2.1)

- PMC identifiers are resolved through the NIH PMC ID Converter when needed; DOI-only records are cross-checked with Europe PMC, PubMed EFetch, Crossref and OpenAlex when available. See [official PMC identifier documentation](https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api/).
- A DOI/PMID in the original *hyperlink* takes retrieval precedence over a contradictory identifier printed in the AI's reference. The disagreement is **flagged** and automatic green writes are withheld; the original blue citation remains unchanged.
- Unlinked full-title citations can be searched against Crossref and PubMed with conservative title-similarity and ambiguity thresholds. These remain provisional candidates; a vague label such as `2024 POQI consensus` is never treated as a verified paper identity.
- PubMed shared multi-author affiliation paragraphs, country names embedded in institutional names, and multiple equally plausible title matches are recorded for review rather than arbitrarily assigned.
- The run report distinguishes candidates evaluated, successful external lookup events, actual metadata records, green rows written, and identity conflicts. For debugging a specific row, consult `research_audit.csv` then `research_proposals.json`.
- The original 12-file pilot is checked in **optional local-only** tests (`ANESTHESIA_TEST_PRIVATE_CORPUS=1 python -m unittest discover -s tests -v`). The private PDF files are never added to GitHub.
