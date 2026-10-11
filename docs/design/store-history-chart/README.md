# Product chart store selection

Scope: existing product price chart and controls only. Thin orange baseline,
store picker at left, period controls at right and one caption underneath.
No store selection: hover across chart height. Selected stores: tooltip only
near the selected store curve (14 px desktop, 24 px coarse pointer). Tap and
keyboard range control supported. Selection survives period changes.

Historical daily store points use latest source observation per Oslo calendar
day, matched by canonical product ID and product name. Out-of-stock, conflicting
observations at the same timestamp, and missing days create gaps. No forward
fill. Existing lowest-price history and surrounding statistics are unchanged.
Existing SSR SVG and readable HTML metrics remain when JavaScript is disabled.

Validated: full static build and validation (201/201 products with offers),
Python regression tests for local dates/stock/conflicts/product identity, JS
syntax, desktop/mobil browser checks with no runtime errors or page overflow;
whole-height hover, selected-curve tooltip, off-curve hiding and period retention.
Screenshots use the Acuvue Oasys 6-pack historical dataset from 11 October 2026.
Preview omits current offers; production keeps the unchanged offer-backed cards.
