# Architecture and trust boundaries

1. **Inputs:** PDFs from a named AI tool, an auto-detectable `CODE/` folder or a ZIP containing such folders. PDF size, file count, ZIP paths and ZIP compression are bounded. Hash each PDF to identify identical duplicates. Confidential source conversations stay local.
2. **Citation transcription (A–L):** PyMuPDF observes original URI annotations and visible text. Detect references sections, numbered/bulleted citations, literal URLs and explicit DOI/PMID. Avoid indexed "sources searched" lists. A source's *original* URL is not replaced by research metadata. Linkless or ambiguous entries remain visible in the review queue. Optional LLM extraction is constrained to PDF text and known annotation URLs.
3. **Question attribution:** read the original 12 questions from `Questions`. Use verbatim prompt, then a `Q01` filename, and finally limited filename/heading heuristic (flagged as less certain). A combined PDF is supported when each question starts on a new page. Tool attribution prioritizes exact workbook codes and unambiguous model aliases.
4. **Research (Z–BF):** explicit citation identifiers → Europe PMC/PubMed author-linked XML → Crossref/OpenAlex → accessible publisher meta tags → tightly constrained title candidate. Preserve API lookup status and evidence per field in sidecar JSON. A matching DOI/URL is *not* a human verdict.
5. **Human verification:** U is written only from reviewer-entered Excel/CSV decisions. `review_workbook.py` validates against allowed study dropdown values and audits every changed field; automated source research never sets U, W, X or other human-only columns. A reviewer verifies every green field, and flags incorrect ones as specified in study protocol.
6. **Workbook fidelity:** surgical OOXML updates to `Data_Extraction`/`Query_Log` retain all other original workbook XML parts, validation, styling and formulas. Never write into the original path. The shipped blank workbook is GZIP-compressed, byte-for-byte restored at runtime.
7. **Output:** human-readable citation preview, explicit review queue, original-template workbook, source proposals and lookup-provenance JSON, report and ZIP package. Local API credentials are never included in output packages.

## Research principles

- Publication issue year is preferred to electronic-first year when PubMed distinguishes both; evidence records the basis.
- PubMed author-specific affiliations are preferred. If there are multiple current affiliations and no chronology, leave the institution/country unknown and flag a review rather than arbitrarily choosing the last element. OpenAlex institution ordering cannot prove which affiliation is most recent.
- No guessed journal origin/SCImago country, 2026 JCR impact factor, gender, or race/ethnicity.
- Unknown funding is `NR`, not "none declared"; no author found in the API does not prove the publication had no author.
- Use exact study dropdown categories; unsupported countries are not silently mapped to a WHO region.
- A cached API result is reusable for resumability but must not be assumed current. Record each run's timestamp and compare dynamic citation counts when finalizing.
- Underlying PDF may not contain complete tool references; uncertainty must survive the pipeline.
