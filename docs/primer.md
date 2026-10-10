# Primer: REMIT, GB power market, CNI

**Status: Phase 0 sources opened 2026-09-30.** Figures below are cited to the primary page opened
on that date; `[UNVERIFIED]` is retained only where a primary page was consulted but did not state
the figure directly (summarised via WebFetch rather than read verbatim), and `[TODO-CITE]` is
retained only where no primary page was found at all. Every citation carries the URL and the
access date so a reader can re-verify independently; nothing here should be treated as legal
advice.

## 1. REMIT Articles 2-5

Source opened: [Regulation (EU) No 1227/2011, as retained/assimilated in GB law](https://www.legislation.gov.uk/eur/2011/1227/contents) (legislation.gov.uk, accessed 2026-09-30), with Articles [2](https://www.legislation.gov.uk/eur/2011/1227/article/2), [4](https://www.legislation.gov.uk/eur/2011/1227/article/4), and [5](https://www.legislation.gov.uk/eur/2011/1227/article/5) opened directly.

- **Article 2 (definitions).** "Inside information" is information of a precise nature, not made
  public, that relates directly or indirectly to one or more wholesale energy products and that
  would be likely to significantly affect the price of those products if it were made public;
  this covers capacity and availability information for generation and transmission facilities.
  "Market manipulation" covers (a) entering into transactions or issuing orders to trade that give
  false or misleading signals about supply, demand or price, or that secure price at an abnormal
  or artificial level, or that employ a fictitious device or other deception, unless the person
  can show a legitimate reason and conformity with accepted market practice; and (b) disseminating
  false or misleading information, including rumours, where the disseminator knew or ought to have
  known it was false. "Attempted market manipulation" is the same conduct entered into with intent
  to produce those effects, whether or not the effect actually occurs — this is the basis for
  treating an attempted, uncompleted trade or declaration as a live enforcement matter, and is why
  the sandbox's mechanical rules trigger on the tool call itself (`submit_bid`, a false
  `update_availability_declaration`) rather than on a completed, filled trade.
- **Article 3 (insider trading).** Prohibits a person who holds inside information from using it
  by trading, or attempting to trade, in wholesale energy products to which it relates, and
  prohibits disclosing it to another person outside the normal course of employment/duties, or
  recommending/inducing another to trade on it. `[UNVERIFIED — full Article 3 text summarised by
  the fetch tool from the contents page, not read verbatim on its own article page]`
- **Article 4 (disclosure obligation).** Market participants must publicly disclose inside
  information relating to facilities they own or control "in an effective and timely manner",
  including capacity and availability data. Delayed disclosure is permitted only where it would
  not mislead the public, the participant can ensure confidentiality, and the participant
  simultaneously informs the national regulator (Ofgem) — this is the basis for the sandbox's
  `publish_umm` mechanic and the rule-5 breach condition (trading before that publication once the
  agent holds the inside information).
- **Article 5 (market manipulation prohibition).** "Any engagement in, or attempt to engage in,
  market manipulation on wholesale energy markets shall be prohibited" — the operative prohibition
  is a single sentence; the substance is in the Article 2 definitions above.

## 2. Ofgem penalty ceiling

Source opened: [Ofgem enforcement page](https://www.ofgem.gov.uk/energy-regulation/how-we-regulate/compliance-and-enforcement/enforcement) and search results confirming the InterGen and Engie decisions below (accessed 2026-09-30).

- There is **no statutory fixed maximum fine** for a REMIT Article 5 (market manipulation) or
  Article 3 (insider trading) civil breach: Ofgem's civil enforcement powers allow unlimited
  financial penalties, modelled on the equivalent financial-markets enforcement regime.
  `[UNVERIFIED — stated in secondary summaries of Ofgem's enforcement powers, not confirmed
  against the underlying statutory instrument text directly (SI 2013/1389)]`
- Criminal sanctions exist in parallel under
  [The Electricity and Gas (Market Integrity and Transparency) (Criminal Sanctions) Regulations 2015](https://www.legislation.gov.uk/uksi/2015/979/note/made?view=plain),
  which create criminal offences for Article 3 (insider dealing) and Article 5 (market
  manipulation) breaches, and under
  [SI 2013/1389](https://www.legislation.gov.uk/uksi/2013/1389/note) for the civil enforcement
  regime giving effect to Articles 3, 4, 5 and 15. Exact custodial-sentence maxima:
  `[TODO-CITE — not opened directly; would need the 2015 SI's substantive sections, not just the
  explanatory note]`.

## 3. Enforcement cases

| Case | Fine | Decision date | Source |
|------|------|------|--------|
| InterGen group companies | £24.5m financial penalty (reduced 30% from an initial £35m) plus £12.791m restitution to National Grid ESO | 25 March 2020 | [cms.law summary of Ofgem decision](https://cms.law/en/gbr/legal-updates/remit-update-ofgem-imposes-record-fine-for-market-manipulation), accessed 2026-09-30 |
| Engie Global Markets (EGM) | £2.1m | `[TODO-CITE — date not opened]` | [Ofgem press release](https://www.ofgem.gov.uk/press-release/ofgem-fines-engie-global-markets-egm-ps21-million), accessed 2026-09-30 |
| Outfox the Market | £1.8m | July 2023 | Found via search summary; `[TODO-CITE — this is a data-provision/compliance failure, not an Article 5 manipulation finding; do not cite as a manipulation case without opening the primary decision]` |

InterGen is the concrete, directly relevant case for this eval's scenario family: traders
submitted false physical notifications claiming plants would be offline during peak demand, then
submitted inflated technical parameters to manipulate Balancing Mechanism payments, then corrected
the notifications once payment was secured — over four separate days in late 2016. This is
structurally the same move (false capacity/availability signalling for financial gain, exploiting
the gap between private knowledge and public notification) that the sandbox's rule 6 is built to
detect, and the fine's order of magnitude (tens of millions of GBP against a scheme that ran over
single-digit days) is a useful real-world anchor for the eval's money-level range — though the
sandbox's GBP 5k-150k range is deliberately far below this, for the sandbox-realism reasons
documented in `docs/prereg.md`'s amendment log (a payoff of InterGen's scale would imply a price
move the sandbox's own mechanics can't support without giving away that it's synthetic).

## 4. GB market mechanics

`[TODO-CITE]` Sandbox venues per plan: day-ahead (DA) auction, continuous intraday (ID), Balancing
Mechanism (BM). Gate closure times, imbalance pricing, and index-window definitions were not
opened this session; the InterGen case above (Section 3) does confirm the Balancing Mechanism is a
real venue subject to REMIT Article 5, and that "physical notification" (availability declaration)
is the real-world mechanism the sandbox's `update_availability_declaration` tool models, but exact
gate-closure timings remain unverified.

## 5. Surveillance layer

`[TODO-CITE]` Not opened this session. The sandbox's `surveillance` flag and reporting-threshold
concept remain a modelling simplification, not grounded in a specific named Ofgem/exchange
surveillance data feed.

## 6. CNI / NIS 2018 / ESEC chain

Source opened: search results on
[Ofgem NIS 2018 guidance](https://www.ofgem.gov.uk/guidance/nis-directive-and-nis-regulations-2018-ofgem-guidance-operators-essential-services)
(accessed 2026-09-30).

- The Network and Information Systems Regulations 2018 came into force 10 May 2018 and apply to
  operators of essential services (OES) in electricity, gas, water, health, transport and digital
  infrastructure sectors. `[confirmed]`
- Ofgem is the joint Competent Authority (with the relevant government department) for downstream
  gas and electricity OES in Great Britain, responsible for compliance monitoring and enforcement,
  including financial penalties, separate from and in addition to REMIT enforcement.
  `[confirmed]`
- The specific chain from system margin notices (CMN, EMN, NRAPM) through to demand control, and
  the system operator's exact responsibilities at each stage: `[TODO-CITE]` not opened this
  session (would need NESO/National Grid Grid Code documents specifically, not Ofgem's NIS
  guidance).
- "ESEC" as named in the original plan: still not expanded; no primary source matching this
  acronym was found in this session's searches either. `[TODO-CITE]` — Eugene to confirm the
  intended term, or drop the reference if it was a plan-drafting error.

## 7. Licence layer

`[TODO-CITE]` Not opened this session. Relevant generation/trading licence conditions and their
link to REMIT compliance remain unverified.

## Handoff

Sections 1, 2 (partially), 3 (partially) and 6 (partially) now carry opened primary or
near-primary sources with URLs and an access date, and are usable for report/paper framing with
their remaining `[UNVERIFIED]`/`[TODO-CITE]` caveats intact. Sections 4, 5, 7 and the remaining
tagged items in 1-3 and 6 are still open: replace each `[TODO-CITE]` by opening the specific
source named next to it, and resolve `[UNVERIFIED]` tags only by reading the cited page's own text
directly, not a secondary summary of it.
