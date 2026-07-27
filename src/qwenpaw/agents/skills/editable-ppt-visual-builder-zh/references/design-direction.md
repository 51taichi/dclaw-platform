# Design And Motion Direction Reference

Use this reference when translating a selected visual scheme into an editable PPTX that should feel designed and presentable, not merely formatted.

## Design DNA Judge Rules

- Choose visual DNA from the deck's commercial purpose, audience, industry, and persuasion job before writing imagegen prompts.
- Treat design DNA as a reusable strategy, not a style label. It must define visual drivers, slide archetypes, asset needs, editability plan, and risks.
- Score candidate DNA directions for commercial fit, visual distinction, industry credibility, editability, deck-wide scalability, imagegen promptability, and risk control.
- Keep only DNA directions that can survive editable PPT implementation.
- Do not copy a specific paid template, marketplace listing, brand system, or protected designer style. Abstract traits such as editorial typography, cinematic crop, dashboard density, paper texture, or modular system topology.
- Reject DNA that is only a palette, gradient, decoration trend, or imagegen mood.

## Design Director Rules

- Start from the creative brief. A visually impressive slide that does not serve the audience, belief shift, and decision is not successful.
- Design after storyboard. Do not let visual exploration hide a weak narrative sequence.
- Every non-appendix slide needs a deliberate role: impact, explanation, evidence, transition, decision, or closing.
- Every designed slide needs one clear focal point. If everything has equal weight, the slide is not designed yet.
- Strong decks vary rhythm: full-bleed image pages, type-led manifesto pages, dense evidence pages, calm explanation pages, and decisive closing pages should not all share the same grid.
- Do not default to cards. Use cards only when grouping or comparison is the best visual logic.
- A generated asset should drive composition, not sit behind content as wallpaper.
- Preserve editability by layering: raster atmosphere and imagery behind editable text, native shapes, charts, tables, and diagrams.
- Choose native-only or hybrid PPT deliberately. If native-only objects flatten the visual direction into generic cards, tables, and diagrams, use raster assets for atmosphere and material finish while keeping business content editable.
- Treat connector style, icon style, module surfaces, data badges, and diagram accents as designed assets or components, not defaults.
- Body slides must carry the selected visual DNA through composition and component language, not only through a cover background.

## Visual Translation Contract Rules

After a visual scheme is selected, translate it before producing the deck:

- Deconstruct the selected contact sheet into page archetypes, dominant visual anchors, focal ratios, text zones, typography rhythm, image treatment, and atmosphere.
- Identify which key slides need page-bound hero assets, such as a large scene, portal, cliff, product object, operating loop, platform metaphor, or closing landscape.
- Define what remains native editable PPT: real text, metrics, labels, charts, diagrams, process names, and business content.
- Define what can remain raster: atmosphere, lighting, texture, photographic or illustrative metaphor, background plate, and complex non-text visual object.
- Mark assets that must not be forced onto a slide. Do not add icons, arrows, badges, or small pictures to a strong hero page just to prove asset usage.
- Build a real 3-5 slide editable PPT prototype for client-ready or highly visual decks before full production unless the user delegates or cancels that checkpoint.

The prototype is the bridge between imagegen and `presentation_builder`. If it preserves only color but loses scale, focal point, composition, typography rhythm, or atmosphere, revise before building the rest of the deck.

## Agency Production Director Rules

- Record review gates: creative brief, storyboard, visual direction, design system, production QA, and delivery signoff.
- Define master layouts before producing the full deck. Premium decks use governed variation, not one-off slide improvisation.
- Keep footer, source note, page number, logo, title zone, and caption behavior consistent unless a slide intentionally breaks the system.
- Build for the delivery environment: live presentation, send-ahead, investor readout, board review, training, or reusable template.
- Deliver edit notes, font notes, asset notes, preview evidence, and caveats for client-ready work.

## Information Design Director Rules

- Every data, chart, table, process, architecture, roadmap, and proof slide must answer a decision question.
- Choose chart type by comparison task, not decoration.
- Define diagram topology before drawing nodes and connectors.
- Highlight signal and mute context. If everything is emphasized, nothing is.
- Use real evidence or clearly labeled placeholders. Never make fake UI, fake data, or fake customer proof look real.
- Put source, assumption, and caveat notes where they protect trust.

## Typography Director Rules

- Treat typography as a design system, not a decorative font choice.
- Define separate roles for display titles, Chinese body text, Latin text, numbers/metrics, captions, and optional code/technical labels.
- Pair Chinese, English, and numeric fonts deliberately. Mixed fallback is a common reason editable PPTs look cheap.
- Use type scale, weight, line spacing, and hierarchy to create polish before adding decoration.
- Verify or clearly mark font availability. A beautiful font name that is not installed becomes an accidental fallback in PowerPoint.
- Use fallback stacks and delivery notes for cross-machine decks. Do not depend on unprovided paid fonts.
- Keep real slide text editable. Do not rasterize text just to preserve a font style.

## Copy Director Rules

- Optimize source copy before designing slides. A raw document paragraph inside a styled box is still weak.
- Slide titles should usually make a claim, not simply name a topic.
- Extract commercial highlights before the story spine so the deck has buyer-facing anchors.
- Keep proof honest. Mark missing proof rather than decorating weak claims.
- Rewrite for compression, hierarchy, and persuasion while preserving facts and constraints.

## Asset Suite Director Rules

- A visual asset suite is more than backgrounds. It may include pictogram families, connector treatments, module surfaces, data badges, proof image strips, texture plates, and diagram accents.
- Use assets only when they improve perceived quality, composition, or clarity.
- Generate body-slide assets when the selected scheme would otherwise collapse into cheap lines, default arrows, generic icon rows, or flat cards.
- Keep text, labels, metrics, and charts editable; use raster assets for atmosphere, material finish, metaphor, and complex visual treatment.
- Record every asset's target slide, crop behavior, layer role, and editability boundary before building the PPTX.

## Commercial Director Rules

- Decide whether the deck must be internal-draft, speaker-assisted, or client-ready before final QA.
- A client-ready deck needs buyer memory: at least 2-3 slides should be anchor pages that express ROI, operating change, implementation path, proof, or final decision.
- Make missing client reality visible. If there are no real logos, screenshots, metrics, routes, user roles, or implementation owners, reserve them or list them as missing inputs; do not invent them.
- Reduce self-reading friction. Dense tables and process maps are acceptable only when hierarchy lets a non-presenter understand the argument.
- Do not let step-build variants bloat the customer-facing deck unless the requested deliverable is a presenter-click version.

## Motion Director Rules

- Every non-appendix slide needs a reveal strategy or an explicit static-by-design reason.
- Motion exists to guide attention and build persuasion, not to decorate.
- Prefer 1-3 meaningful beats per slide: setup, proof, conclusion.
- Reveal conclusions after evidence when the slide needs persuasion; reveal conclusions first only when executive clarity matters more than suspense.
- If native animation support is unclear, use editable step-build slides instead of static output.
- Step-build variants must preserve object positions so the presenter experiences them as animation.

## Slide Art Direction Fields

For each slide, write:

- role
- desired feeling
- focal point
- composition
- visual anchor
- hierarchy
- native PPT objects
- raster assets
- negative space
- forbidden patterns
- redesign trigger

## Slide Motion Direction Fields

For each slide, write:

- motion role
- presenter beat
- reveal order
- object groups
- transition
- pacing
- implementation mode
- fallback
- redesign trigger

Example:

```text
Role: evidence.
Feeling: credible, sharp, outcome-oriented.
Focal point: one oversized metric at 3x the size of secondary numbers.
Composition: left editorial headline, right dashboard cluster, bottom proof strip.
Visual anchor: native metric dashboard with one generated texture panel.
Native PPT objects: metric text, chart bars, labels, dividers, captions.
Raster assets: subtle background plate only.
Forbidden patterns: four equal cards, decorative icons without data meaning.
Redesign trigger: if the page reads as a normal report page instead of proof.
Motion role: proof-build.
Reveal order: headline -> oversized metric -> chart -> annotation.
Implementation mode: step-build-slides if native animation is unavailable.
Motion redesign trigger: if all evidence appears at once and the audience has no guided path.
```

## Component Library Rules

Component definitions should include:

- name
- purpose
- slide types
- native PPT parts
- allowed raster layers
- layout grammar
- text hierarchy
- variants
- failure modes

High-value components:

- hero cover
- chapter opener
- thesis/manifesto
- pain wall
- service system
- operating model
- metric dashboard
- case proof strip
- process map
- comparison wall
- offer page
- closing ask

## Visual QA Rubric

Score each slide from 1 to 5:

- Design DNA fidelity: does the slide express the selected DNA beyond colors?
- Commercial fit: does the visual language help the deck achieve its business purpose?
- Visual translation fidelity: does the slide preserve the selected scheme's page archetype, dominant visual anchor, focal ratio, text zone, typography rhythm, and atmosphere?
- Composition: is the layout intentional and distinctive?
- Focal point: does the eye know where to land first?
- Hierarchy: are title, proof, support, and captions clearly ranked?
- Typography system fidelity: do font roles, sizes, weights, line spacing, and numeric treatment follow the written system?
- Font availability safety: are fonts verified, provided, or safely replaceable with documented fallback?
- Master layout fidelity: does the slide follow the deck's layout system or intentionally break it for a strong reason?
- Information design integrity: do charts, tables, diagrams, screenshots, and evidence objects clarify the decision?
- Evidence honesty: are source notes, assumptions, caveats, and placeholders honest?
- Rhythm: does this slide add variety to the deck?
- Scheme fidelity: does it retain the chosen direction beyond color?
- Quota-decoration control: are assets present because they serve the story or composition, not because a usage count needed to be satisfied?
- Asset integration: do images/textures affect structure instead of decorating it?
- Asset suite completeness: do required icons, connectors, module surfaces, data badges, or support images exist and feel coherent?
- Copy sharpness: are headlines and callouts optimized into claims and buyer-facing takeaways?
- Motion clarity: does the reveal order guide attention and argument?
- Presentation rhythm: does the deck alternate impact, explanation, proof, and payoff?
- Editability: are real content, charts, and diagrams still editable?
- Source fidelity: are claims and metrics faithful to the source?
- Client specificity: does the page feel tailored to the named client and operational context?
- Brand alignment: does the slide respect brand assets, tone, logo, color, typography, and evidence constraints?
- Handoff readiness: can the user understand what is editable, what is raster, what is missing, and how to modify the slide?
- Business persuasion: does the page move the buyer toward a decision, not merely explain a feature?
- Self-readability: can the page be understood without narration?

Redesign any non-appendix slide scoring below 4 on design DNA fidelity, commercial fit, composition, focal point, hierarchy, motion clarity, presentation rhythm, or scheme fidelity.
For client-ready decks, redesign or add context when client specificity, business persuasion, or self-readability is below 4 on any anchor slide.

## Common Failure Patterns

- color-only fidelity: palette matches but composition, imagery, and typography do not
- thumbnail-to-PPT drift: the generated PPT keeps the color mood but loses the selected visual scheme's page archetypes, dominant visual anchors, focal scale, or atmosphere
- missing prototype gate: the agent jumps from imagegen contact sheet to full deck without testing 3-5 real editable PPT pages
- font-default drift: the deck silently falls back to Aptos, Calibri, Arial, SimSun, or another system default
- font soup: too many unrelated fonts or weights compete
- CJK/Latin mismatch: Chinese, English, and numbers come from unrelated fallback fonts
- fake font polish: real slide text is flattened into images to preserve appearance
- briefless beauty: the slide looks good but is not tied to audience, stakes, or decision
- storyboard bypass: visual polish hides a weak or repetitive argument
- master drift: every slide has different margins, title zones, footers, or source-note behavior
- decorative data: charts and diagrams look styled but do not answer a decision question
- fake evidence: generated screenshots, numbers, or UI imply proof that was not provided
- handoff gap: final PPTX is delivered without edit guidance, font notes, asset notes, or caveats
- card soup: every idea is placed in a rounded rectangle
- weak wallpaper: generated background has no relationship to the content
- equal weight: all text blocks, metrics, and icons compete at the same level
- template sameness: every slide uses the same title position and content grid
- fake polish: shadows, gradients, or icons are added without improving the story
- quota-driven decoration: arrows, badges, icons, or small images are inserted only to satisfy asset-suite usage
- kit-first composition: the slide is arranged around available component sheets instead of the page's narrative beat and visual archetype
- screenshot escape: poor layout is hidden by flattening content into an image
- static dump: all objects appear at once even when the argument needs a reveal
- animation promise: native PowerPoint animation is claimed without being supported or verified
- DNA cosplay: final slides borrow a trendy surface but do not support the deck's business goal
- template imitation: the deck copies a specific commercial template instead of abstracting traits
- technical pass false positive: final export succeeds, renders are nonblank, and text is editable, but the deck still looks like a draft
- native-only ceiling: editability is over-prioritized until the visual system collapses into flat report pages
- background-only asset suite: cover pages look designed but body slides rely on generic controls
- low-quality control language: lines, arrows, widgets, and boxes look like default office drawing rather than a designed system
- raw copy dump: source paragraphs are placed into slides without claim-led rewriting
- no commercial anchor: every slide explains something, but no slide creates a memorable business reason to act
- generic client story: the deck could be sent to any company because it lacks real brand, data, screenshots, or operating specifics
