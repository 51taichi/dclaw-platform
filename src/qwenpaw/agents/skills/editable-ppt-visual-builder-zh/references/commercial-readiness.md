# Commercial Readiness Reference

Use this reference after visual QA and before final delivery whenever the deck is intended for commercial, client-facing, investor, sales, proposal, or standalone executive use.

## Core Principle

A deck can be technically valid and still not be commercial-ready. Nonblank renders, editable objects, successful PPTX export, and source-faithful text prove file quality, not buyer confidence.

## Delivery Tiers

| Tier | Score | Meaning | Delivery rule |
| --- | ---: | --- | --- |
| Client-ready proposal | 8.2-10 | Can be sent to a decision-maker and understood without the presenter | Deliver as commercial-grade |
| Speaker-assisted proposal | 6.8-8.1 | Works in a meeting when the presenter explains context | Deliver with caveats or revise |
| Internal draft | 5.5-6.7 | Useful for alignment, content review, or next design pass | Do not call commercial-grade |
| Redesign required | <5.5 | Visual, story, or proof gaps undermine trust | Redesign before delivery |

If the user requested commercial-grade or client-ready output, anything below 8.2 must trigger redesign or an explicit downgrade.

## Score The Rendered Deck

Score 1-10, using full-size rendered slides and a contact sheet:

- Creative brief fit: serves the documented audience, setting, belief shift, and decision.
- Storyboard strength: narrative sequence is clear, non-repetitive, and leads to an action.
- Visual completion: polished hierarchy, deliberate layouts, no generic card soup, no obvious AI/template residue.
- Client specificity: uses or clearly reserves brand, real operational facts, actual system/UI, real routes, customer roles, and domain details.
- Business persuasion: answers why buy, why now, what changes, who benefits, what success looks like.
- Self-readability: a decision-maker can understand the argument without live narration.
- Evidence and proof: metrics, assumptions, baselines, examples, screenshots, or acceptance indicators are sourced or clearly labeled.
- Information design: charts, diagrams, tables, roadmaps, and evidence slides clarify the decision and preserve source truth.
- Implementation credibility: timeline, owners, phase logic, operational constraints, risks, and next steps are believable.
- Editability boundary: important text/data remain editable, while raster layers carry atmosphere, texture, photos, or complex visual polish.
- Handoff readiness: the user receives enough edit notes, font notes, asset notes, preview evidence, and caveats to maintain the deck.

Average the scores and record the lowest two dimensions as blockers.

## Commercial Anchor Pages

Client-ready business decks need at least two strong anchor pages, and high-stakes proposals usually need three. Choose based on the deck goal:

- before/after operating model
- ROI or personnel-impact estimate
- revenue or cost model
- customer-specific current-state map
- system architecture tied to business outcomes
- implementation roadmap with ownership
- acceptance metrics and risk controls
- final decision/ask page

Anchor pages should be memorable at thumbnail size and defensible at full size. If every slide is explanatory, the deck is not yet commercial.

## Hybrid PPT Boundary

Use native PPT for:

- real titles, copy, labels, metrics, tables, charts, process nodes, roadmap text, and module names
- content that the user must edit or localize
- source-derived facts and numbers

Use raster assets for:

- cinematic or photographic backgrounds
- texture, lighting, material finish, dimensionality, atmosphere
- non-evidence visual metaphors
- edge/corner compositions that create premium finish

Failure signal: if preserving full native editability makes the slide look like a flat report page, switch to hybrid layering while keeping business content editable.

## Common Failure Patterns From Editable PPT Builds

- technical QA passed but visual QA did not happen at commercial standard
- imagegen direction was treated as a mood image rather than translated into page archetypes and assets
- final deck matched palette but lost composition, texture, lighting, and visual hierarchy
- native-only implementation produced white-background cards, tables, and diagrams with weak focal points
- step-build variants inflated page count and made the customer-facing deck feel repetitive
- source content was complete but lacked buyer-facing proof, ROI, implementation detail, or final ask
- generated assets appeared only on cover/closing while body slides collapsed into generic components
- the deck had no client-specific assets, screenshots, data, or terminology beyond the source title

## Required Commercial QA Note

Before final delivery, write a short QA note containing:

```text
Commercial readiness:
- Intended tier:
- Score:
- Lowest dimensions:
- Client-ready? yes/no
- Missing inputs:
- Redesign actions taken:
- Remaining caveats:
```

Never state that a deck is commercial-grade unless this note supports the claim.

## Agency Delivery Signoff

For client-ready, investor, executive, sales, or high-stakes decks, final delivery must include:

- creative brief and gate decisions
- storyboard approval or delegated approval
- selected visual direction record
- design system notes
- font/fallback notes
- asset suite usage notes
- edit guide
- rendered contact sheet and full-size spot-check evidence
- missing-input and assumption list
- commercial readiness note

If these are missing, the deck may be technically complete but is not agency-grade.
