# Astra Historical Data Infrastructure V1 — resume completion

## PROVEN
Recovered the interrupted archive, adapter, PIT and provider-router implementation. Finnhub acquisition is one symbol and one calendar day per request. Raw bodies and metadata are durably retained before normalization. UTC membership is start midnight <= timestamp < next midnight; spill evidence remains retained under its proper canonical date. Provider/article identity deduplicates observations while raw hashes preserve versions. Missing IDs use explicitly derived deterministic identities.

SQLite transactions atomically index raw evidence and checkpoints by provider/symbol/day; resume verifies body checksums. At least 250 rows means SATURATED_INCOMPLETE. Saturation persists even if a later retry returns fewer rows. COMPLETE_OBSERVED does not claim exhaustive provider coverage.

Publication, provider observation, historical source availability, actual Astra receipt and ingestion are distinct. Unknown Finnhub observation/availability clocks remain null; actual receipt is never replaced with publication time. Finnhub defaults PARTIALLY_POINT_IN_TIME and replay_safe=false. The existing canonical PIT contract owns the single HISTORICAL_NEWS_EVIDENCE_GATE. No generic provider proof validator exists; only the existing version-bound SEC acceptance basis is implemented.

SEC economic/report dates remain separate from accession acceptance. Existing FMP earnings/actions are exposed through a bounded streaming normalization adapter with source references; no bulk normalized copy or reacquisition was performed. Current FRED snapshots cannot enter historical replay. Analyst revisions and quote/trade microstructure have readiness schemas, not invented archives. The canonical registry covers all 18 requested domains using prior reports; its counts are reused evidence, not a new census.

## NOT PROVEN
Exhaustive news coverage, Finnhub version availability, external historical datasets, natural PAPER performance, and production worker loaded-source alignment. Existing SEC pilot counts refer to prior evidence and are not new acquisitions. Readiness does not establish dataset availability.

## WHAT WAS WRONG
The interrupted task lacked completion reports and final verification. A smaller retry could replace a saturated checkpoint.

## WHAT CHANGED
Completed explicit UTC interval handling and persistent saturation, added regression tests, and produced the four requested reports. Recovered changes to the PIT contract and optional raw-evidence router path are included. Default router requests retain existing behavior. Worker/Sentinel truth and reconciliation edits are unrelated and remain untouched and unstaged.

## TESTS / RUNTIME VERIFICATION
57 focused and adjacent tests passed in the repository virtualenv, including canonical PIT and prior SEC pilot regressions. Changed Python files passed py_compile; git diff --check passed. Initial system Python 3.9 collection failed because datetime.UTC requires the repository's newer interpreter; the virtualenv run passed. Mocked transport tests exercised the router, daily acquisition and durable resume against temporary archives. Executed module path/hash are recorded in the JSON report. No production worker restart or deployment was performed; loaded worker revision alignment is not claimed.

## REMAINING FIRST BLOCKER
PROVIDER_EXTERNAL: version-specific historical news availability proof; macro vintages, analyst revisions, and true quotes/trades require external evidence. No dataset acquisition is authorized by registry membership.

## SAFETY
PAPER ONLY. Zero provider acquisition calls in this resume. No bulk download, broker truth, learning acknowledgement, policy promotion, trade forcing, lane policy, risk/sizing/capacity, ETH ownership or reconciliation changes. Planner defaults DRY_RUN; BOUNDED_PILOT is limited to three symbols/ten daily windows and AUTHORIZED_SCALE requires explicit authorization. The CLI writes manifests only. No worker restart.

## GIT
Only the two attributable existing source files, new script/test, and four requested reports are intended for this commit. Unrelated state deletions, worker/Sentinel edits/tests and pre-existing reports are preserved. Commit/push identity is reported in the completion response.

## FINAL STATUS
ASTRA_HISTORICAL_DATA_INFRASTRUCTURE_V1_RESUME_COMPLETE. Infrastructure verified offline; external historical availability remains fail-closed.
