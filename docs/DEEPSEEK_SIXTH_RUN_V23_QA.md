# DeepSeek sixth-run QA and source-level research coverage (2026-11-09)

## Original v2.2.1 pilot evidence

Input: the investigator's private `anesthesia_citation_research_package (6).zip`. The original PDFs/workbook stay private and are NOT committed to GitHub.

| Metric | Previous v2.2.0 | Sixth run v2.2.1 |
|---|---:|---:|
| As-cited occurrences (blue) | 156 | 156 |
| Green rows populated | 92 | 99 |
| Informative green cells | 1,180 | 1,331 |
| Linked source identities with green | 47 | 50 |
| First-author country occurrences | 47 | 55 |
| Sources with any metadata | 95 | 101 |

The sixth run took 43.95 seconds total, including 40.64 seconds of bibliographic research and 1.70 seconds of PDF extraction. The previous run did not record elapsed time, so a speedup percentage cannot be verified. Same-run source memo reuses: 83.

Of 55 citation occurrences with a proposed first-author country, approximately **34 DOI/PMID/original-link grouped publication candidates** remain when repeated citations and equivalent source URLs are grouped. These candidate groups are NOT independently verified source identities. They do not replace any original citation rows and do not establish unique-publication counts for analysis.

The 156 original citation fields, URLs, repeats and extraction locations matched the previous run exactly. The only changed XLSX OOXML file between the last two run outputs was the Data_Extraction worksheet. Human-owned cells remained unpopulated.

## Remaining work supported by this pilot

- 22 original linked source identities (57 citation occurrences) still lack substantive green data.
- Q03 hemorrhage: only 1/19 rows has green data. High-priority original sources include a Swedish regional anesthesia protocol and the ANZCA 2025 Blue Book PDF; the latter is officially listed as **16.82 MB**, above the former 10 MB opt-in transfer limit. Reference: https://www.anzca.edu.au/safety-and-advocacy/advocacy/college-publications/australasian-anaesthesia-%28the-blue-book%29
- Q05 difficult airway: 9/12 rows have green data, predominantly educational webpages. The original ASA guideline PDF must be manually matched to the official 2022 publication (candidate PMID 34762729 / DOI 10.1097/ALN.0000000000004002). Reference: https://pubmed.ncbi.nlm.nih.gov/34762729/
- Q09 delirium: a TMG MEDLINE index source URL includes candidate PMID 39570649; the exact provider hostname and `/portal/resource/pt/mdl-<PMID>` pattern can now retrieve a PubMed candidate, with a warning requiring source comparison. Reference: https://pubmed.ncbi.nlm.nih.gov/39570649/
- The 3 possible source-alias groups span 19 citation occurrences; their publications must not be silently collapsed.

## Changes in v2.3.0

1. `first_author_source_coverage.csv`: provenance-labeled, identifier-grouped candidate articles with first-author country, country-evidence type, counts of repeated citations, and unresolved conflicts.
2. `source_access_review.csv`: one action per unresolved linked source with flags for PDF/downloadable document, search results, original URL, citation occurrence count, and recommended review.
3. Streamlit ZIP and download options for both reports; clear distinction between per-occurrence and per-candidate source geography.
4. **Opt-in only** linked PDF fetch budget raised to 24 MB (45 seconds maximum) to cover larger institutional reports. A prominent heading from the first PDF page can be stored as a reviewer-only title **hint** if embedded metadata does not establish a title; the hint must not automatically populate green research fields.
5. Recognized TMG MEDLINE link pattern yields a **candidate** PubMed ID but does not authenticate the original citation.

## Reproduction (one-line PowerShell commands)

    git switch main
    git pull origin main
    python -m unittest discover -s tests -v
    ./run_windows.bat

Full 12-PDF DeepSeek: Copy + research publications, provisional green policy, offline unchecked, no paid AI, max sources 0, linked PDF inspection unchecked.

PDF pilot: Q03 and Q05 only, same settings but **Inspect linked source PDFs checked**. PDF bytes are never added to the evidence ZIP. Confirm source version, title, document type and individual authors manually.

The CI regression suite is synthetic and does not replace a new real-PDF online research run. No U/X/human-only values or investigator demographic outcomes are automatically verified.
