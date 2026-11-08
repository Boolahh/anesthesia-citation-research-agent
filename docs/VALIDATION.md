# Validation plan

Before running the full study:

1. Export a full response for one question from one AI tool and independently count every explicit citation in the original chat.
2. Confirm the exported PDF preserves hyperlinks; note any collapsed `+N` sources and export them separately if the platform allows.
3. Run `python run_agent.py scan --no-ai` and compare each citation, source URL, question and order to the original answer.
4. Run `python run_agent.py run --stage blue --no-ai --offline`. Inspect Data_Extraction A–L and the Query_Log changes.
5. Have a reviewer enter citation-verification decisions in the workbook. Only then run verified-only source research.
6. Independently check bibliographic fields against the underlying publications. Mark any incorrect agent values in the workbook as specified in the study protocol.
7. Open the resulting workbook in Excel and validate formulas, dropdowns, country classification, and the unchanged reviewer columns.
8. Repeat across multiple tools and a paywalled or missing-link example before large-scale processing.

Record model, version, input file hashes, query timestamps (if available), and any manually corrected fields in study records. Do not claim that a successful API lookup establishes citation authenticity.
