# Copilot / Edge viewport extraction QA (November 2026)

## Test corpus and provenance

The investigator supplied **13 actual one-page PDFs** of a Microsoft Copilot
conversation and the v2.4.1 full evidence-package ZIP. No source PDFs or study
workbook are committed to this public repository. This document contains
only non-sensitive extraction conclusions and test instructions.

The ZIP reported:

| v2.4.1 metric | Observed |
|---|---:|
| Source rows created in Excel | **216** |
| Original supposed citation appearances | 234 |
| Question/model pairs | 12 (COP Q01–Q12) |
| Original clickable medical-publication URLs recovered | **0** |
| Rows incorrectly linked to `copilot.com` UI navigation | **216** |
| Strictly matched academic publications | 0 |
| Substantive green metadata fields written | 0 |
| Original PDFs | 13, each 1 page |

**Failure cause:** Every Copilot print PDF had 18 clickable URI annotations,
all pointing at sidebar navigation (`copilot.com/chat`, `/search`,
`/library/all`, `/projects`, and previously opened conversations). The
old generic URI parser treated these as references, even though they appear
in the left navigation bar, not the answer. The content area instead had
small grey **non-clickable** badges such as `lww +1`, `bmj`, `nih`,
`bjaed`, and `wfsahq`. A total of **45 visible badge appearances**
were manually audited by deterministic PDF text/span geometry. These are
**not 45 verified unique publications**; duplicates, truncation and
collapsed `+1` source groups cannot be resolved without the actual URLs.

Q06 is duplicated across two *different* PDFs, and the last Q12 PDF
begins in the middle of a scrolled response. These files cannot establish
a complete, defensible 12-question Copilot bibliography.

## Corrected acceptance conditions

- No Copilot UI navigation URI becomes a medical source, anywhere.
- Exact source badges printed in the body are preserved as source *labels*
  only. URLs absent from the original PDF are `NR`; never inferred.
- A visible `+1` means at least one unseen source may be in the interface,
  **not** permission to create a reference for an invisible source.
- Unknown as-cited authors, titles, DOI, PMID, countries and research metadata
  remain `NR` / `NOT FOUND`. No title-only bibliographic searches.
- Full, original source hyperlinks explicitly present in a better export are
  extracted normally. An unresolved badge over a real linked source is not
  duplicated.
- Multiple distinct PDF replies to the same model/question are rejected
  before Excel is written; the investigator chooses exactly one response.
- Old workbooks with sidebar-link contamination are blocked from being
  reused as an otherwise plausible master workbook.

## Required test sequence for the investigator

1. Discard the v2.4.1 Copilot output workbook as a research source. **Do not
   reuse it as a reviewed Excel workbook**, because it contains all 216 fake
   navigation rows.
2. Open each *complete* original Copilot response and expand its citation
   groups. Record **every actually shown original source URL** without
   substituting a newer or better-matching work.
3. Export the entire answer and complete actual source list to a searchable
   PDF, with all hyperlinks preserved. Verify by clicking a source link in
   the resulting PDF. A one-page viewport print is insufficient.
4. Use one Copilot answer for each of Q01–Q12; choose ONE of the two Q06
   responses, not both.
5. Run blue-only/offline first and compare the resulting links to the
   original transcript. Then run green with offline unchecked, no paid
   AI, maximum lookups 0, and provisional source policy.
6. Confirm the green fields follow the strict original-source rule. Any
   unmatched/unretrievable source stays in blue with `NOT FOUND` green
   values, not invented authors, countries, years or publication types.

**Limitation:** Synthetic CI tests validate the parser and workbook
guards. The investigator's private original corpus must be rerun locally
against the merged version for final real-data acceptance.
