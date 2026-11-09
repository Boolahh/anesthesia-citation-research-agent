# DeepSeek PDF extraction: 12-question pilot (2026-11-09)

## Important input warning

The 12 original DeepSeek PDF exports are private and are not checked into GitHub. The ZIP provided alongside them was actually a Claude run: its report listed CLG for all twelve questions, 63 Claude citation occurrences and 22 distinct Claude source identities. Do not treat those as DeepSeek results.

The PDFs use numbered superscript citation links and a separate "Found N web pages" search-results count. The count of pages found is **not** the count of sources cited.

## Direct original PDF audit

| Question | Linked occurrences | Distinct linked source identities | PDF link offsets requiring review |
|---|---:|---:|---:|
| Q01 PONV | 16 | 7 | 0 |
| Q02 Hypotension | 20 | 6 | 4 |
| Q03 Hemorrhage | 19 | 5 | 0 |
| Q04 LAST | 17 | 6 | 0 |
| Q05 Difficult airway | 12 | 5 | 0 |
| Q06 OLV hypoxemia | 22 | 9 | 1 |
| Q07 Cesarean | 7 | 6 | 0 |
| Q08 AKI/THA | 8 | 6 | 0 |
| Q09 Delirium | 10 | 7 | 0 |
| Q10 Pediatric URI | 8 | 4 | 0 |
| Q11 CABG | 9 | 6 | 0 |
| Q12 Raised ICP | 8 | 6 | 0 |
| **Total** | **156** | **73** | **5** |

The 12 PDFs had 468 PDF URI annotations, representing 156 printed linked citation occurrences (three nested hitboxes per citation). There are 83 repeat occurrences within responses. Counts are provisional and require a human extraction audit, not independent publication verification.

Displaced links requiring review: Q02 label 4 and 7 (PDF page 2), labels 1 and 2 (PDF page 3), and Q06 label 12 (PDF page 2). Their original links are retained and confidence is flagged for reviewer confirmation.

## Implementation / trust

- agent/deepseek_numbered.py groups nested link rectangles and matches visible numbered superscripts.
- agent/pdf_extract.py selects this route only for recognizable DSK numbered exports and preserves the generic fallback.
- Preserve blue D as the original displayed number and blue E as the original hyperlink. A numeric marker is **not** a full bibliographic title; blue F remains NR.
- All independently researched green values remain provisional until checked. Do not auto-set reality verdict U, reviewer source URL X, or other human-only fields.
- Sources merely found by a search but not cited must not be counted.
- The original PDF exports and blank workbook are not modified.

## Local commands (one command per line)

Run with the original DeepSeek PDFs in inputs/DSK:

    python -m unittest discover -s tests -v
    python run_agent.py run --stage blue --input inputs/DSK --output outputs/deepseek_blue.xlsx --tool DSK --no-ai --offline --report-dir outputs/deepseek_blue_reports

Compare the generated citation_preview.csv to the 156 printed occurrences, every repetition, and the five link-offset cases.

For provisional publication research after that audit:

    python run_agent.py run --stage all --input inputs/DSK --output outputs/deepseek_provisional.xlsx --tool DSK --green-policy provisional --max-sources 0 --no-ai --report-dir outputs/deepseek_research_reports

Always validate the original links and each substantive green proposal against authoritative records. Use verified-only after the investigators enter human U and X decisions.

The study preregistration has conflicting counting rules: page 15 requires occurrence counting, while an older section on page 84 describes distinct-source counting. Preserve both, and let investigators resolve analysis rules.
