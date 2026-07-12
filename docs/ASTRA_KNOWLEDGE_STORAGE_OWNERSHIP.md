# Astra Knowledge and Storage Ownership

This catalog is the Build H ownership boundary. It is intentionally compact and
lists known stores rather than walking the runtime tree. The runtime validator
is `/api/astra_build_h_ownership_map_v1`.

## Authority rules

| Responsibility | Classification | Canonical owner | Rebuildable |
| --- | --- | --- | --- |
| Broker-confirmed positions, orders, fills, and closed-trade truth | AUTHORITATIVE | broker truth reconciliation / closed-trade truth registry | No |
| Canonical outcomes | DERIVED | canonical outcome builder and reconciliation | Yes, from broker lineage |
| Lifecycle lessons | DERIVED | `cortex_lifecycle_evidence_master_truth_v1` | Yes, from source evidence |
| Recommendation history and attribution | DERIVED audit | recommendation history and attribution | No, append-only audit |
| Symbol similarity memory | DERIVED | `long_term_memory_symbol_retrieval_suite_v1` | Yes |
| Replay and counterfactual records | DERIVED | replay/counterfactual learning | Yes |
| Market context and catalyst records | DERIVED | market-context and catalyst suites | Yes |
| Summary indexes | INDEX | `astra_storage_cache_attribution_learning_efficiency_v1` | Yes |
| Knowledge retrieval metadata | INDEX | `knowledge_retrieval_indexing_v1` | Yes |
| Dashboard and Learning Center summaries | CACHE | unified diagnostics cache | Yes |

## Reuse and non-duplication

The existing storage analyzer remains the owner of summary-index inventory and
storage/cache diagnostics. The existing Tier 2A librarian remains the owner of
lesson categorization, master truth summarization, and executive routing. Build
H adds a bounded ownership map and later a warehouse query contract; it does not
replace either system or create a second librarian, truth registry, or cache.

## Operational policy

* Runtime checks use metadata and existing manifests/indexes where available.
* Normal rendering must not scan all of `state/` or open raw historical files.
* Authoritative broker truth and order/fill audit history are never compacted or
  deleted by Build H.
* Derived indexes, summaries, caches, and lessons are rebuildable only when
  source lineage is preserved.
* Unknown ownership and authoritative conflicts remain warnings until resolved;
  the validator must not silently claim a clean audit.
