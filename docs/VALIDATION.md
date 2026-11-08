# Validation protocol before full study processing

## Deterministic regression suite

`python -m unittest discover -s tests -v` on Python 3.11+; GitHub Actions runs 3.11, 3.12 and 3.13. These fixtures are synthetic: no original research conversations or commercial source content are committed.

## Pilot QA per platform (all 16)

1. Preserve the exact prompt, tool settings, run date, any model version and subscription tier, and the complete original response separately per tool (human-owned `Query_Log` fields).
2. Export a test response to PDF with **all source drawers expanded**, checking that every explicit citation remains visible and each link can still be opened. Expand any collapsed `+N` labels. Annotate searched-but-not-cited results; do not count them as citations.
3. Start with one platform and one question, ideally a response with numbered citations, bare URLs, unlinked references, a guideline and a journal article. Run offline blue extraction.
4. Compare every source occurrence in the original with `citation_preview.csv`, not just the total count. Check exact citation text, order, duplicate semantics, URL, Q number, platform, and PDF page. Hidden references and screenshot-only PDFs require re-export/OCR/manual review.
5. Compare output XLSX against original blank template: A–L, Query_Log, human fields, formulas, drop-down values and `Statistician_Dataset` unchanged except calculated cell results.
6. Review `review_queue.csv`; do not interpret a missing URL as a fabricated citation. Record unrecoverable sources explicitly.
7. Populate source-verification verdicts in U and real-link X **only after independent human verification**. Use DOI/PMID, title, author-year-journal and authoritative publisher record as described in the protocol.
8. In online research-only mode, check each proposed Z–BF field against the *right publication*. Compare first, last and corresponding author affiliations separately. Ensure correct journal issue vs electronic year and verify country names against the built-in country list.
9. For each outside source, verify `research_proposals.json` provenance, source lookup events and notes. Never treat an OpenAlex authorship institution order as proof of the most-recent affiliation.
10. Check that restricted/unsourced fields are missing rather than fabricated: 2026 JCR factor, SCImago journal origin, explicit funding, author demographics. A reviewer must mark bad green values as incorrect for the study's internal agent validation.
11. Repeat the entire pilot for all 16 platforms using real exported PDFs; test cases where sources are shown in popovers, two-column lists, 'sources searched' pages and paywalled articles.
12. Run a full 192-query sample only after each platform meets the investigator-defined accuracy and missing-reference thresholds. Save the run report and input SHA-256 hashes alongside the study dataset.

## Known 12-PDF ChatGPT pilot

- 33 candidate sources, 28 preserved URLs, two PDFs with no clickable URL annotations. Count remains provisional because collapsed `+N` groups may conceal references.
- The 2025 blood-component guideline can be matched to formal bibliographic records; one-lung ventilation and author-specific affiliation examples demonstrated that earlier retrieval had missing or incorrectly attributed fields. New code conservatively leaves ambiguous author data for human verification.
- No live end-to-end validation across all 16 platforms is claimed. API availability, subscription entitlements, record versioning, OCR quality and source export fidelity can change over time.
