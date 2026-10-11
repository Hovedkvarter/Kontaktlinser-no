# Store price observations

Append-only archive for future per-store price charts. This is independent of the
existing daily lowest-price chart; no public UI or price ranking changes here.

- Key: product_id (specific pack), retailer and source checked_at timestamp.
- Preserve price, NOK currency, shipping policy, stock status, source/network and
  product name/specs as recorded in the catalog.
- Identical observations are deduplicated by SHA-256 of normalized content.
  A repeated website build does not confirm a price. Changed observations at the
  same timestamp remain separate, rather than silently overwriting evidence.
- Record out-of-stock offers too; chart eligibility must be applied on reading.
  Missing offers or missing timestamps never produce invented observations.
- No age-based deletion. Compressed baselines and subsequent JSONL files must
  both be read. These archives are repository data, not copied into the website.
- New catalog observations are archived and committed with each scheduled or
  manually triggered catalog refresh. Source checked_at is used, not build time.
- Reused/cached source checks retain their original timestamp. A feed failure or
  disappearing offer must not be interpreted as a fresh price or sold-out event.

## Initial recovery, 2026-10-11

244 committed catalog revisions yielded 147,846 distinct recorded observations,
203 product IDs and 15 retailer labels. Timestamps span 2026-08-07 through
2026-10-11. Coverage varies by product/store; this is not a claim of continuous
coverage or independent upstream validation. Each recovered row identifies its
first recovered Git commit in provenance. Mapping/specs reflect that historical
catalog; validate mapping changes before drawing continuous chart lines.

Run `python scripts/backfill_store_price_history.py` from the repository root
with full Git history for documented recovery. Existing compressed baselines are
never overwritten. Run `python store_price_history.py` for the current catalog.
