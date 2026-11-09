# Evidence-first research performance and cross-platform rollout

## Why DeepSeek's full run was slow

The 2026-11-09 12-PDF DeepSeek research export had 156 linked citation occurrences but only 73 distinct exact bibliographic lookup keys when original URL fragments were stripped and the as-cited label/identifiers were retained. The earlier implementation repeated the same research function for each occurrence. The result log contained 136 fresh successful lookups, 159 disk cache hits, 43 PubMed landing-page HTTP 203 responses, 13 blocked LWW pages, and several oversized source PDFs.

The v2.2 research client now memoizes the independently retrieved source *evidence* within a run using source URL, as-cited label, as-cited title, DOI, PMID, and verified-link status. A different label/identifier gets independently checked rather than sharing a possibly wrong identity verdict. Blue rows and human reviewer fields remain independent. Report counts include source_memo_reuses; this is NOT equivalent to verified publications.

## Optional direct source-PDF inspection

Many public-agency and professional-body guidelines are PDFs, not HTML. Binary PDFs no longer get passed to the HTML metadata scraper. Enable the separate **Inspect linked source PDFs** option only when you want to trade execution time for a chance of recovering document titles from original public PDFs.

The source-PDF inspector has a 10 MB transfer cap, 30-second processing budget, four-redirect maximum, public-DNS checks before every hop, and no automatic retries. A PDF metadata title can be proposed only when it is also visibly present on the first PDF page. Such a title remains UNVERIFIED. The source PDF bytes are not saved to the study package, and its title does not establish an author or journal. No publisher-paywall bypass or JCR inference is attempted.

## UI and offline operation

The Streamlit app now streams [PDF], [RESEARCH], and [SOURCE] subprocess progress, showing completed source attempts and a progress bar rather than only a blocking spinner. A hard one-hour timeout is retained. The Windows launcher remains unchanged.

- First validate blue-only extraction offline for each new platform.
- For DeepSeek, 156 original linked occurrences / 73 source-number + URL pairs / five displaced-link review cases remain the *provisional* baseline.
- For online full research use provisional green policy with no paid AI; run up to all sources only after the blue-only pilot matches the original.
- Optional linked PDF inspection should be a **separate targeted pilot** for a small batch, not the default for an entire 192-query corpus.

## Other AI platforms

No unprovided proprietary model-PDF export can be promised to parse perfectly. Existing ChatGPT (CGP) and Claude (CLG) parsing paths are intentionally untouched. For other supported tool codes, there is a guarded numbered-annotation fallback only when at least three URI groups are present and at least 85% have nested hitboxes and directly aligned numeric superscripts. This emits an explicit unvalidated-export warning; it does NOT classify search result lists as cited sources.

For each new model, require original saved PDF evidence from at least one multi-page and one mixed reference response; compare the original citation text, URLs, numbering, repetitions and page location manually. If links are collapsed, hidden, image-only or JS popovers, request a better export or reviewer coding rather than synthesizing citations.

## Verification and scientific boundaries

- Study outcome coding requires human checks. Do not automatically write reality verdict U, checked-source URL X, demographic fields, human source statuses, JCR impact factor, or inferred corresponding author information.
- A successful HTTP response, a URL-derived title, a publisher HTML title, an embedded PDF title, or a DOI record is **not** proof that the AI cited the source correctly.
- Source-level research must not be confused with citation occurrence counting; both are reported because the study's preregistration sections disagree on duplicates.
- The original blank workbook and non-target XML remain unchanged. Preserve the OOXML writer and do not round-trip a formula-heavy workbook through a generic spreadsheet library.

## Reproducible testing (one-line commands)

    python -m unittest discover -s tests -v
    python run_agent.py run --stage blue --tool DSK --input inputs/DSK --output outputs/dsk_blue.xlsx --no-ai --offline
    python run_agent.py run --stage all --tool DSK --input inputs/DSK --output outputs/dsk_research.xlsx --green-policy provisional --max-sources 0 --no-ai
    python run_agent.py run --stage all --tool DSK --input inputs/DSK --output outputs/dsk_pdf_pilot.xlsx --green-policy provisional --max-sources 10 --inspect-linked-pdfs --no-ai

Never put the original input PDFs or research participant data in GitHub or in CI test fixtures. CI synthetic fixtures are not substitutes for the original-PDF QA.
