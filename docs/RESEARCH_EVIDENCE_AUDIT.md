# Research metadata quality controls (v2.1)

## Original 12-PDF pilot, November 8, 2026

The source PDFs are private and are not checked into GitHub. A complete **offline** rerun recovered 12 study question IDs, **33 candidate citation occurrences** and **28 original linked URLs**. The missing URLs for Q01 and Q02 and the PDF export's collapsed `+N` source groups remain unresolved. These counts do not establish a complete citation census. The independent research stage could not fetch new online records inside the development runtime: **0 live metadata lookups, 0 green rows** in the offline smoke workbook.

Regression tests use synthetic PDFs for CI, plus an *opt-in local-only* test against the 12 original PDF exports. Do not upload unpublished model answers or investigator review workbooks to this repository.

## Reviewer trust boundaries

1. **Blue (A–L):** strictly as-cited transcription from the AI's answer. A wrong DOI, title or absent link must stay wrong/absent; the agent may flag it but must not correct it in blue.
2. **Source identity:** prioritize the document's actual URI-target DOI/PMID for lookup while preserving text/URL contradictions as a high-priority review. Use PMC ID conversion and linked bibliographic APIs only as candidate evidence. Title-only matches always require an independent human decision.
3. **Green (Z–BF):** citation metadata proposals, not verification verdicts. Data in `research_proposals.json` is keyed per source and accompanied by field-level provenance. `research_audit.csv` gives one row per source including those not yet looked up.
4. **Author affiliations:** PubMed AffiliationInfo can be an address for an individual author OR a shared article-wide paragraph listing multiple named authors. The latter cannot be applied to every author. Unclear or multi-institution assignments remain `NR` and produce review flags. Author *current/most-recent* affiliation is not inferred from OpenAlex institution order.
5. **Country and journal metrics:** country is taken only from an explicit terminal geographic designation, not a city or an institution called "University of Georgia". Journal country requires investigator-supplied SCImago confirmation; 2026 impact factor requires licensed JCR evidence.
6. **Human-only (M–Y, BG–BR):** citation reality, link status, source-verification decisions, demographic coding, and final checking remain investigator-controlled.

## Three useful authoritative cross-checks

These sources are cited only to illustrate the metadata-disambiguation cases that motivated the automated tests. They are **not** a claim that the entire batch has been externally verified or that hidden references were recovered:

- Q01 named PONV consensus guideline: PubMed PMID `32467512`, DOI `10.1213/ANE.0000000000004833` — https://pubmed.ncbi.nlm.nih.gov/32467512/ . A similarly titled 2020 editorial has a **different** PMID and DOI; title-only matching must distinguish it.
- Q03 major hemorrhage: PubMed PMID `37277130`, PMCID `PMC10241541`, DOI `10.1503/cmaj.221731` — https://pubmed.ncbi.nlm.nih.gov/37277130/ . The published affiliation paragraph mentions several universities for distinct authors; it is not reliable to assign them all to the first/last author.
- Q06 one-lung ventilation: PubMed PMID `37600211`, PMCID `PMC10435364`, DOI `10.1016/j.bjae.2023.05.006` — https://pubmed.ncbi.nlm.nih.gov/37600211/ . Publisher issue date and first electronic publication date differ.

## Status interpretation

| Audit status | Meaning |
|---|---|
| `not_researched` | No source lookup attempted due to stage, source cap, or insufficient identifiers |
| `metadata_unavailable` | Candidate evaluated but no acceptable external source data was retrieved |
| `lookup_error` | A lookup raised an exception; see run report |
| `identity_conflict_or_ambiguous_source` | Contradictory source identity, green fields withheld |
| `proposed_only_human_verification_required` | Evidence exists but workbook cells were gated by reviewer policy |
| `written_provisional_or_reviewer_gated` | Green cells were written as proposals, never as a human verdict |

A successful API call is not proof that the AI's citation was correct. Investigators must verify the exact source against the original AI citation and study protocol before using the row for publication.
