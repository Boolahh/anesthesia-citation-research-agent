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

The 12 standardized questions and 16 platform definitions are read *directly* from the original study workbook, not duplicated in code. The extraction engine supports original PDF hyperlinks, printed URLs/DOIs/PMIDs, numbered and bulleted references, multi-page responses, and optional evidence-constrained AI transcription. Unknown layouts or hidden sources are flagged for a human rather than silently guessed. **Pilot status:** ChatGPT has a historical extraction pilot; the 12-question Claude pilot has undergone multiple extraction QA cycles; and a new 12-question DeepSeek PDF geometry audit found 156 linked citation occurrences representing 73 within-question linked source identities. These are extraction baselines, not independently verified citation censuses. Every new platform and source-metadata enrichment run still requires real-PDF and human-review validation. See `docs/DEEPSEEK_VALIDATION.md`.

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

## Critical Copilot / Edge browser-print limitation (v2.4.2)

A real 13-PDF Copilot pilot exposed a severe print-export pitfall.
**Edge browser screen print can preserve 18 clickable Copilot sidebar/chat
navigation links while losing ALL medical source link destinations.** The old
v2.4.1 parser incorrectly counted these navigation links as 216 research
citations. Such a workbook must not be used for research or carried into a
cumulative master spreadsheet.

The corrected parser removes known Copilot UI links (`copilot.com/chat`,
`/search`, `/library`, `/projects`, and conversation-history routes).
If the PDF has an identifiable Copilot viewport format, it copies **only
visible small source-badge labels**, such as `bmj`, `lww +1` or `bjaed`,
into blue D. If the badge's actual original source URL was not embedded in
the PDF, blue E stays `NR` and missing green research values are
`NOT FOUND`. The `+1` indicates a collapsed group of unseen sources,
which the agent **does not invent, count or expand**. Repeated generic
labels without an original source URL cannot safely be assumed to be
the same article.

**For a usable full study export:**

1. Open the *entire* original Copilot answer in Edge. Scroll through to the
   end and explicitly expand all citation/source groups (`+1`, etc.).
2. Capture each original cited source's full **actual hyperlink** from
   Copilot's citation interface. Do not replace it with a paper you find
   separately; that would corrupt the as-cited evidence.
3. Create one complete text-selectable PDF per prompt containing the entire
   answer plus all actually cited references/URLs. Pasting into a document
   and saving as PDF is fine **only after confirming that the hyperlinks
   survive**. Printing the visible chat viewport directly is NOT enough.
4. Use exactly **one answer PDF per AI model/question**. If you upload two
   different Copilot answers for Q06, the app now stops rather than mixing
   them. Prefer files named `Q01_COP.pdf` through `Q12_COP.pdf`.
5. First run **Copy original citations (blue)** and compare extracted labels
   and URLs against the original. Only then run green research. The
   missing-source warnings are not evidence of zero citations.

The app rejects master workbooks containing these known fake Copilot
navigation rows, instead of silently contaminating later AI-platform runs.
Use a clean original template and re-import correct exports. See
`docs/COPILOT_VIEWPORT_VALIDATION.md` for the real-PDF evidence.

## One Excel row per source per question (v2.4.0)

The investigator has explicitly chosen **one source row per AI model + question**,
regardless of how many times the model references the same linked source in
that answer. The same source can appear in different questions (or for
different AI platforms), so each separate model/question gets its own row.

For example, a Claude PONV PDF contained **24 original citation appearances**
but only **3 distinct linked source identities**. The same NYSORA link appeared
22 times. Version 2.4.0 now creates three unique source rows, rather than 24
appearance rows, and separately saves every original appearance in
`citation_occurrences_raw.json`. The per-question CSV
`citation_counts_by_question.csv` shows original appearances, repeats,
distinct source links, and reference-list entries. Only original-source
identity evidence—not a similar article title—is used to merge automatically.

**Study protocol note:** An earlier preregistration section (page 15) counted
each appearance, while a different section (page 84) used distinct-source
counting. The investigator's explicit revised workbook rule is now distinct
linked sources per model/question. Review/update your study analysis plan and
report this change transparently; the raw appearance evidence is retained for
either analysis.

When adding a new model, upload the newest completed Excel workbook in the
**Reviewed Excel workbook** field. The agent first consolidates legacy
duplicate-source rows from older releases **only if** reviewer values and
research fields are consistent. If two duplicate rows conflict, the run
stops with their exact row numbers and columns rather than deleting human
decisions. The original input workbook is never overwritten.

Some ChatGPT PDF exports contain no clickable sources even though the chat
interface displayed them. Without evidence, the agent cannot safely decide
whether two generic labels refer to the same publication. Export visible
sources with URLs or review the original chat in these cases.

## Strict original-source research policy (v2.4.1)

**Default behavior is now evidence-only, even when the Green-column policy
is set to Provisional.** A cited source is included in blue A–L when the
original PDF contains an actual linked citation or an explicit bibliography
entry. Its as-cited label remains in D and its original URL remains in E.
A short linked badge or source number is not silently expanded into a
guessed publication title.

Green Z–BF fields may be filled from independently sourced publication
metadata **only if the original citation identifies that same record**:
for example, an original PubMed article link with the same PMID as the
PubMed record; a displayed DOI that exactly matches an official Crossref
record; or an actual linked article page whose embedded citation DOI and
full title match the independent DOI registry. Even these remain provisional
until a human verifies the citation. Title similarity searches, general
webpage headlines, publisher-domain inference, AI-generated research
guesses and author-country estimates do **not** establish source identity.

If the agent cannot identify a source, it **keeps its original citation and
link row** and writes the workbook-supported **`NOT FOUND`** placeholder
in missing green research cells (leaving the licensed JCR impact-factor
field blank). The research audit explains why the source remains unresolved.
Neither `NOT FOUND` nor a successful PubMed lookup automatically labels
the original AI citation real or hallucinated.

Existing substantive green values in an uploaded older workbook are not
automatically deleted, because they may be human-reviewed. For a completely
clean strict audit, start from the original blank study template and add
the models in sequence. If a citation has no original URL and no explicit
DOI/PMID, the agent does not invent an identifying link or try to pick a
paper merely because the title looks similar.

## What exactly gets written

- **A–L (blue):** one representative original citation and original link per distinct source **within the model/question**; the same source can have another row for another question. Duplicate appearances are retained in the raw evidence ZIP, rather than being written as extra blue rows. Source URLs are never replaced by subsequently researched links.
- **M–Y (human only):** tool metadata, human source-verdict in U, reference error category, independently verified URL in X and audit status; never inferred by the agent.
- **Z–BF (green):** independently corroborated bibliographic proposals only when the original cited source and authoritative publication record match; otherwise the study's `NOT FOUND` placeholder. BE (licensed JCR) remains blank without licensed verified data. Every sourced field retains provenance in `research_proposals.json`.
- **BG–BR (human only):** gender, race/ethnicity, checking the proposed green fields, and reviewer notes; never inferred or overwritten by the agent.
- Other workbook sheets/formulas/styles/dropdowns are maintained by narrowly editing only the `Data_Extraction` and `Query_Log` worksheet XML.

### Affiliation safeguards

The system reads PubMed XML **author by author** and rejects repeated composite paragraphs that actually list multiple authors' institutions. It refuses to assign an institution to an author just because another author lists it, and refuses to pick the "most recent" institution from several affiliations when chronology is unknown. OpenAlex affiliations are retained as possible research clues but **are not automatically used** for the first, last or corresponding author's recorded institution or country. Journal country is not substituted with publisher headquarters. Explicit countries must appear at the end of an affiliation, not only inside a university name; ambiguous country names are withheld. The official issue year is preferred over online-first year when PubMed supplies both, with this choice documented in provenance.

### Source research performance and PDF coverage (v2.2)

The research engine now researches **one unique source row per model/question**,
rather than repeatedly researching its many appearances. Every original
appearance remains in the evidence ZIP. Other cache hits and cross-question
memo reuses are distinguished from actual verification; ambiguous linked
identities remain in the review queue.

Streamlit now shows live extraction/research progress rather than only an
unchanging spinner. Binary PDFs are not passed through the HTML scraper.
**Inspect linked source PDFs** is an optional, slower, bounded metadata-only
lookup for public PDF documents. Neither webpage titles nor PDF document
titles are verified bibliographic identities.

Some other platforms with strongly identifiable numbered-link PDF geometry
can use a conservative parser fallback; they are explicitly marked unvalidated.
ChatGPT and Claude use their existing extraction paths. For details and pilot
QA instructions, see [research performance and format guide](docs/RESEARCH_PERFORMANCE_AND_FORMATS.md).

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
