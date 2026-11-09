# DeepSeek v2.2.0 real-output audit and v2.2.1 quality fixes

Source: the investigator's private `anesthesia_citation_research_package (5).zip` compared with `(4).zip` (November 9, 2026). Original files are not committed.

## Actual run metrics

| Metric | v2.1.0 | v2.2.0 |
|---|---:|---:|
| Original citation occurrences | 156 | 156 |
| Green rows populated (includes provisional webpage titles) | 58 | 92 |
| Distinct within-question source identities with green | 35 | 47 |
| Informative green cells | 1,068 | 1,180 |
| First-author country occurrences | 47 | 47 |
| Citations with any metadata retrieved | 95 | 95 |
| Distinct source identities processed | 72 | 72 |
| Source memo reuses | not recorded | 83 |
| Reviewer queue entries | 121 | 154 |

Interpretation: the 34 additional green rows largely came from webpage titles and source-type proposals, **not** 34 new identified journal articles. First-author geography did not improve. Of 52 provisionally coded journal-article occurrences, 47 had first-author country; un-authored websites are not automatically eligible for individual-author geography outcomes.

## Evidence-based quality fixes

1. Q07 occurrence #2 linked a PubMed **search results** URL, not an individual paper. The previous version saved a generic search-results title as a government source. Keep the original URL in blue; suppress this source identity in green, flag a distinct reviewer-facing status and counter.
2. Q01 occurrence #15, PMID 41530355, contains a PubMed first-author affiliation ending in `Barranquilla, Colombia` followed by a contact email. Strip only the email and preserve explicit country evidence. Never infer a country from an email domain.
3. Several unresolved DeepSeek URLs encode a candidate PubMed identifier without pointing directly to pubmed.ncbi.nlm.nih.gov. Recognized shapes now include BVS MEDLINE `mdl-...`, Europe PMC `/article/MED/...`, and the exact institutional PubMed proxy observed in Q02. Retrieve the official PubMed metadata, but explicitly warn that the proxy/index link is not evidence of original citation identity.
4. Institutional and government web-document authorship receives applicability review rather than being counted automatically as a missing first-author geography outcome.
5. Add extraction/research elapsed-second fields to future run reports, since HTTP success/cache-hit counts alone do not establish runtime improvements.

## Validation limitations

- Blue citation occurrence count should stay 156 on the same input PDFs; every duplicate and PDF annotation review warning must be preserved.
- A search-results link may ultimately be coded as a citation error by the human investigator. The agent cannot decide that automatically.
- PubMed records derived from alternate URL shapes remain provisional until original link identity is manually checked.
- No automatic hallucination verdict, reviewer-approved URL, author gender, or licensed journal impact factor.
- No new full live research run has been performed after these changes. The next rerun is needed to measure source and geography coverage.
- Continue checking workbook ZIP integrity and non-target worksheet preservation.

## Reproduction

Run all regression tests: `python -m unittest discover -s tests -v`.
Run the 12 DeepSeek PDFs with online bibliographic lookup and provisional green policy using `--stage all --tool DSK --green-policy provisional --max-sources 0 --no-ai`.
Run a separate small opt-in PDF pilot for Q03 sources: `--inspect-linked-pdfs` (may be slow).

The investigator-facing detailed review-priority CSV is provided separately in the chat, not committed to the repository.