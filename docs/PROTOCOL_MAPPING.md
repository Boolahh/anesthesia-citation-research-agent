# Study-workbook column ownership and research-source mapping

This document describes **how the existing supplied workbook is used**, not an alteration to its study protocol. Allowed categorical values are always read from the workbook's original `Lists` worksheet.

| Columns | Owner | Meaning / evidence rule |
|---|---|---|
| A–L | Agent, copied | Citation as AI supplied it, original hyperlink/IDs, order and repeats; do not correct errors in blue |
| M–S | Human | Platform company, country, business/retrieval status, tool classification and configuration |
| T–Y | Human | Verifier initials, U reality/error verdict, error type, original link status, independent real source URL, blue validation |
| Z–AC | Agent proposes; human verifies | Actual title, year, DOI, PMID from DOI/PubMed/publisher records; issue year preferred when applicable |
| AD | Agent proposes; human verifies | Source type from authoritative publication type, not blindly from title |
| AE–AG | Agent proposes; human verifies | Study design, anesthetic specialty, funding; `NR` unless evidence supports a categorical choice |
| AH | Agent proposes; human verifies | OpenAlex cited-by count, can vary by day and corpus |
| AI–AK | Agent proposes; human verifies | Author category, count, distinct institutional countries with sufficient author-level data |
| AL–AP | Agent proposes; human verifies | First author name and *author-specific* institution/country/WHO region/income |
| AQ–AU | Agent proposes; human verifies | Last author name and independently evidenced institution/country/WHO region/income |
| AV–AZ | Agent proposes; human verifies | Corresponding author and independent affiliation. Never infer from first/last author position |
| BA–BD | Agent proposes; human verifies | Journal/publisher name and country/WHO/income; journal country requires SCImago, not publisher HQ |
| BE | Agent proposes only with licensed proof; human verifies | Impact factor from **2026 Journal Citation Reports release**; otherwise blank |
| BF | Agent proposes; human verifies | Open-access category from OpenAlex/Unpaywall where independently supported |
| BG–BO | Human | Author gender/certainty and race/ethnicity; only explicitly self-reported race/ethnicity |
| BP–BR | Human | Green coding verifier, whether coding was checked, notes |

Research proposals are *not* definitive and do not establish a real-source verdict. The study's statistician sheets and human-only columns are never altered by automatic source lookup. A separate reviewer tool can populate only explicitly human-provided values.

Missing-state conventions: `NR` when absent/not reported; `NOT FOUND` when lookup cannot find evidence; `Not applicable` for inapplicable categories. These states are not interchangeable. A DOI/PMID candidate is not a link-verification status. The original `Query_Log` date/investigator/Done? fields remain human-entered; the agent records local processing time and PDF hashes separately in its report.
