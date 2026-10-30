# Google Ads readiness — draft implementation, 2026-10-30

Property: Kontaktlinser.no, Products only. Baseline `afcb4578760a373a84e2342a61267eebdd9b12e5`.
Owner authorized implementation and Draft PRs, not merge, deployment, GTM/account
changes, live clickouts, test purchases or advertising. Core coordination:
https://github.com/chillout-labs/chillout-platform/issues/306 (private).

## Minimum implementation and boundaries

1. This repository owns consent, local acquisition context and rendered surfaces.
2. Existing Chillout owns internal click identity, EPI and transaction reconciliation.
3. Cost input is a complete reviewed daily CSV in Core. No website finance database,
   duplicate importer, new service, Leads change or Google conversion upload.

Contracts read on 30 October: Click Tracking & Attribution v1.0;
Advertising & Revenue Intelligence (concept, not operational authorization);
Project Instructions/Architecture Decision Log and Continuous Learning v1.0.

## OBSERVERT — current website and prior evidence

Published HTML on 30 October contains the following pilot **candidates**:

| Product | Offer | Published internal target |
| --- | --- | --- |
| Biofinity 6-pack | Lensway | `/go/tgt_01M35ASH8T98X8R5PQGDNCYVJZ` |
| Biofinity 6-pack | Shopping4net | `/go/tgt_01M35ASH8Z0QXD3NVE6WVF47SK` |

Both resolve through existing renderer mappings. Prior September pilot evidence
documents browser redirects. Today's observation proves rendered targets, not
current destination validity, sale attribution or operational readiness. No real
click was made. Read-only prefetch responses in the audit do not prove redirects.
Revalidate these exact targets before launch. Do not expand to a retailer's other
products by inference. The winning offer can belong to another retailer: preserve
price ranking and show that attribution coverage is incomplete.

The audit fetched published GTM `GTM-5RZFVNQM`: GA4 `G-ELJYYBLS6H`, an
`outbound_click` tag, a link listener and a Custom HTML tag loading
`s.cartbooster.io/preload`. No execution or behavioral certification of that
script was performed. It is a website configuration finding, not a Chillout
integration. Consent Mode cannot control arbitrary Custom HTML by itself.
Current GA4/Ads account destinations and conversions have not been verified.
Cloudflare's gateway may modify delivery; absence from repository HTML cannot
prove it disabled (see CLAUDE.md, 10 September).

## IMPLEMENTERT IN DRAFT — not deployed

- Consent v2: independent statistics, affiliate and advertising measurement;
  personalization always denied. Explicit unchecked settings, denied defaults,
  updates before GTM load, GA4 disable flag on withdrawal and footer reopening.
- v1 choices do not imply new advertising permission. v2 expires after 180 days;
  this proposed duration must be included in the release review.
- All existing custom analytics emitters use `__klTrack`: no pre-consent buffering.
  This includes search, shipping and offer-expansion events, not just clickout.
- With affiliate denied, normal/middle/modified clicks and context-menu actions
  on affiliate CTAs open settings instead of following the network link. No clean
  merchant destination is guessed. Non-affiliate links, including Extra Optical,
  remain usable. Raw HTML URLs remain unchanged for SEO; this is a browser UI
  guard, not a server-enforced denial of arbitrary direct URL requests or copied
  URLs. JavaScript-disabled/manual requests are not claimed consent-controlled.
- `tracking_readiness.json` defaults both GTM review and acquisition activation
  to false. **Merging/publishing this candidate alone would suppress GTM**, so
  coordinate the reviewed container and configuration in the approved release.
  Do not claim the old live container is safe because this code exists.
- Acquisition needs ads AND affiliate consent, explicit account identity and one
  valid gclid/gbraid/wbraid plus numeric `kl_campaign`. No ID is decoded to guess
  a campaign. `kl_campaign={campaignid}` is a proposed later Ads URL parameter;
  account/auto-tagging changes are not performed here.
- A UUID visit, acquisition timestamp and allowlisted fields are held in tab
  session storage and a Secure/SameSite=Lax cookie scoped to `/go/`, max 30 minutes
  without sliding renewal. No IP, user-agent string, referrer or search term.
- Only pilot-path/retailer internal links receive `acq_visit` at activation.
  This is an opaque consistency reference, never the Google click ID. The edge
  compares it with the cookie so another tab cannot silently change attribution.
  A mismatch loses attribution, not navigation. Google IDs never enter EPI.
- Extra Optical and unverified external links are not rewritten. No offers,
  price ranking, product identity, canonicals or structured data changed.

## Test evidence and learning

Local: existing clickout suites 86/86 passed. The unchanged baseline had 11
failures caused by obsolete winner markup/return arity, outdated CI string
assertions and the documented Extra Optical exception. Tests now assert current
behavior rather than reintroducing old behavior. Two broad `/go/` text checks now
check actual hrefs, because cookie code is not a rendered tracking link.

Consent tests exercise the actual inlined script in an isolated DOM harness;
they do not prove a live Google request or third-party script behavior. Existing
search tests are retained. Full local generation and build validation passed,
231/231 products with prices; this uses saved catalogue data and does not fetch
merchant prices or prove fresh internal mapping availability. CI guards: 15 passed.
Generated pages/lastmod changes are local test output, not committed.

Durable learning: queued dataLayer events are not consent enforcement; GTM
Custom HTML requires its own reviewed purpose gate; a shared cookie must not
silently change a different tab's attribution. Prevented by consent/multitab
regressions. Applicable methods can benefit other Properties, but no data,
permissions, approvals or commercial mappings transfer. Original observations
remain here; shared follow-up belongs in Core #306. Owner: Kai/reviewer.

## Exact release approvals — all still OPEN

1. Review exact website/Core commits and pass their CI, including PostgreSQL
   integration and cross-Property isolation. Approve schema separately; never
   run a migration merely because a Draft PR exists.
2. Approve consent wording, purposes, 180-day preference lifetime, 30-minute
   acquisition window and server retention/deletion policy. Confirm acceptable
   behavior for declined affiliate links and JavaScript-disabled visitors.
3. Review GTM/gateway in a nonpublishing preview. Decide the unrelated Custom
   HTML tag's website purpose or removal; verify separate triggers and withdrawal.
   Approve the container version before `gtm_consent_reviewed=true`. No tag change
   or container publication is authorized by this PR.
4. Verify these two targets, mapping freshness and all three rendered surfaces.
   Set the same exact token allowlist at edge and Core; approve the real account
   identity and pilot config. No automatic winner preference or broader rollout.
5. Separately approve migration/runtime/edge/site release sequence and rollback.
   With capture off, existing clickout behavior remains. Disabling capture keeps
   financial history; schema rollback refuses to delete stored acquisition.
6. Separately approve controlled real click/test-sale verification, including
   later approval/rejection and importer freshness for both TD time windows.
7. Reconcile a complete Ads cost export, reporting coverage, currency/timezone,
   maturity and unmatched rows. Verify account auto-tagging/GA4 linkage and
   secondary vs primary conversion goals. Outbound clicks are not sales.
8. Only after separate approval: ads activation. Google offline conversion
   uploads/bidding are a later bounded change, not included in these drafts.
