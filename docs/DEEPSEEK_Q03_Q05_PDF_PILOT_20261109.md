# DeepSeek v2.3.0 real-PDF pilot findings and v2.3.1 fixes (2026-11-09)

The original 12 DeepSeek PDFs and investigator workbook are **not committed**. Evidence comes from the user's private uploaded full research ZIP (7) and Q03/Q05 linked-PDF inspection ZIP (8).

## Actual comparison (not a claim of new verification)

| Measure | Full 12-question run (PDF inspection OFF) | Q03+Q05 pilot (ON) |
|---|---:|---:|
| Questions | 12 | 2 |
| Citation occurrences | 156 | 31 |
| Green rows populated | 99 | 13 |
| First-author country occurrences | 55 | 0 |
| Elapsed seconds | 35.30 | 58.16 |
| Research seconds | 31.95 | 56.09 |

Same-question, same-PDF comparison: Q03 green rows **1→1**, Q05 **9→12**. The only new green rows were three linked ASA draft difficult-airway guideline citation occurrences. The first-author country denominator of 31 is not necessarily 31 individually authored publications; both questions include protocols, educational pages, and a book anthology.

## Direct PDF evidence

| Q | Original document | Occurrences | Inspector status | v2.3.1 treatment |
|---|---|---:|---|---|
| Q03 | Västra Götalandsregionen **Massiv blödning - Anestesirutin** | 7 | PDF read; visible first-page title; no embedded matching title | A provisional title only when first-page title equals actual PDF filename; identify the original regional clinical protocol and its version |
| Q03 | ANZCA **Australasian Anaesthesia 2025** (Blue Book) | 7 | PDF read, 159 PDF pages, no established title | Require official ANZCA host + 2025 Blue Book filename + opening-page publication/year corroboration. Treat it as an edited collection; do **not** assign author country to the editor |
| Q03 | Taiwanese health ministry download URL | 3 | PDF time budget exceeded | Continue manual/official metadata investigation; no blind retries |
| Q05 | ASA draft difficult-airway guideline PDF | 3 | PDF read; title supported by embedded metadata and first page | Keep proposed title/type but warn explicitly that the source link points to a draft and is not automatically interchangeable with the final 2022 publication |

Official ANZCA publication index: https://www.anzca.edu.au/safety-and-advocacy/advocacy/college-publications/australasian-anaesthesia-%28the-blue-book%29

Official publisher-repository book identifier (for reviewer comparison, **not** automatically assigned from a DeepSeek citation): https://airr.anzca.edu.au/anzcacrisjspui/handle/11055/1305

VGR original linked source from the output report (do not replace the PDF with a later version during extraction): https://mellanarkiv-offentlig.vgregion.se/alfresco/s/archive/stream/public/v1/source/available/SOFIA/SU9805-1593997-654/SURROGATE/Massiv%20bl%C3%B6dning%20-%20Anestesirutin.pdf

## Avoid misleading QA and wasted researcher time

- DeepSeek exports cite sources using numbered superscripts. A label of **8** is not a parser failure; the linked URL and match still require independent verification. The v2.3.0 message "156 short/domain-only labels" was misleading about format quality. v2.3.1 explicitly reports expected numbered markers, while preserving the **five original displaced-link QA cases**.
- When a PDF was already read and yielded no safe bibliographic title, the source-access report says to inspect publisher metadata or original front matter rather than rerun the same network request.
- PDF title proposals and type classifications remain independently sourced, provisional, and identified in field-level provenance. No human-only verdict, verified URL, gender, organization author country, licensed JCR factor, or fabricated chapter attribution is written.
- Keep the original blue citation occurrences and their literal original URLs unchanged.
- The pilot's 58.16-second runtime is dominated by a slow government document download. It is not evidence that the 12-question base run became slower.

## Rerun after CI passes

Use only Q03 **Intraoperative Hemorrhage Management - DeepSeek.pdf** first. Processing stage: **Copy + research publications**, model DSK, **Provisional** green policy, offline unchecked, paid AI disabled, max sources 0, **Inspect linked source PDFs checked**, reviewed XLSX left empty.

Expected **blue** citation count for Q03 is 19. Compare source-level green proposals and review reasons, not just a total cell count. The Swedish protocol and ANZCA Blue Book should now receive conservative book/document-level *title proposals* if the original PDF evidence satisfies the strict corroboration checks. The Taiwanese source may still require manual review. The next full 12-question run can keep PDF inspection off to validate backward-compatible extraction and revised numbered-marker QA.

Release regression suite: `python -m unittest discover -s tests -v`, on Python 3.11–3.13. Original private PDFs must be manually checked; CI synthetic fixtures alone do not verify a clinical citation or a study outcome.
