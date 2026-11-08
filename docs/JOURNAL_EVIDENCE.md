# Optional investigator-supplied SCImago and 2026 JCR journal evidence

The public source APIs cannot reliably provide the protocol's SCImago **journal-country classification** or licensed **2026 Journal Citation Reports impact factor**. Rather than guessing or scraping access-controlled sites, the agent optionally accepts an independent, **investigator-verified** CSV (uploaded in Streamlit or passed with `--journal-evidence`).

The required CSV headers are:

```csv
journal_name,country,scimago_url,impact_factor_2026,jcr_evidence_id,date_checked
```

- `journal_name`: exact journal title of the independently matched record (case-insensitive punctuation-insensitive matching).
- `country`: exact value from the study workbook's `Countries` tab, **only after** confirming the journal's SCImago country entry. Leave blank if not independently verified.
- `scimago_url`: an HTTPS URL at `scimagojr.com` pointing to that verified journal; required when country is supplied.
- `impact_factor_2026`: a nonnegative numeric value from the **2026 JCR release**. Leave blank if no authorized, verified value exists.
- `jcr_evidence_id`: reference to the *investigator's licensed* JCR 2026 record/export, required when impact factor is supplied. The agent does not attempt to fetch it.
- `date_checked`: exact `YYYY-MM-DD` date when the investigator confirmed both fields.

Keep licensed exports **outside GitHub**, including in private repositories if your institutional terms forbid redistribution. Do not add this CSV to source control; keep it in `outputs/` or another appropriately protected location. Journal evidence is not included in the app's downloadable evidence package. The recorded provenance identifies these fields as investigator supplied and still requires review under the original study protocol.

CSV rows must be unique by journal title and are validated *as a complete file* before any output workbook is written. Non-matching journals retain `NOT FOUND` country and blank impact factor rather than adopting another journal's metrics. This workflow cannot independently validate that the operator truly has a JCR license; the study team retains that responsibility.
