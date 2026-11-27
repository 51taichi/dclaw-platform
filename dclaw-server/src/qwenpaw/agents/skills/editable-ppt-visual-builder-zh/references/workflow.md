# Workflow Reference

## Stage 1: Source Understanding

Extract:

- deck objective: inform, persuade, sell, teach, review, raise funding, report progress
- audience: executive, client, investor, internal team, technical buyer, general public
- tone: strategic, premium, technical, operational, editorial, playful, sober
- constraints: page count, language, brand, template, deadline, required sections
- source reliability: confirmed facts, assumptions, missing data, claims needing verification
- delivery tier: internal draft, speaker-assisted proposal, external client-ready proposal, or reusable template system
- commercial blockers: missing brand assets, real screenshots, customer data, proof metrics, ROI assumptions, implementation owner, timeline, pricing, or final ask
- brand/source asset audit: logos, colors, fonts, templates, screenshots, data files, diagrams, legal notes, source claims, and proof objects
- production environment: PowerPoint, Google Slides-targeted, Keynote, PDF handoff, live presentation, self-reading send-ahead, screen share, print, or mobile review

Classify every PPT/PPTX input:

- source deck: use for content, sequence, claims, facts, and screenshots
- template deck: preserve layout skeleton, brand chrome, typography, palette, and spacing
- reference deck: use only as quality bar, rhythm, or style inspiration
- mixed deck: separate which slides provide content and which provide visual rules

If the input is long, summarize it into a working brief before designing slides.

When the user asks for commercial-grade, customer/client version, sales proposal, investor deck, pitch, or standalone executive material, default the delivery tier to external client-ready proposal and require the commercial readiness gate before final delivery.

## Stage 2: Creative Brief And Agency Success Bar

Read `premium-agency-standards.md` before this stage.

Create a concise creative brief:

- audience and decision-maker
- current situation and business stakes
- desired belief shift
- required decision or action
- presentation setting and delivery mode
- presenter constraints and self-reading needs
- brand constraints
- mandatory content and forbidden claims
- proof requirements
- success criteria
- approval owner and review gates

Create a brand/source asset audit:

- provided assets
- missing assets
- generated non-evidence assets allowed
- placeholders needed
- source proof that must be preserved
- assumptions that must be stated

Agency-grade review gates:

- creative brief gate
- storyboard gate
- visual direction gate
- design system gate
- production QA gate
- delivery signoff gate

For client-ready, investor, executive, sales, or high-stakes work, stop at a gate when user approval is required. If the user delegates the gate, record the delegated decision and rationale.

## Stage 3: Copy Optimization And Highlight Extraction

Read `copy-optimization.md` before building the story spine. The goal is to turn source material into presentation-grade copy without inventing facts.

Extract:

- core promise: what the audience should remember
- audience belief shift: what they believe before and after the deck
- commercial highlights: pain, stakes, differentiation, proof, implementation path, ROI/personnel impact, risk control, and final ask
- source constraints: exact wording that must be preserved, names, dates, metrics, regulated terms, and unsupported claims
- weak areas: proof gaps, vague benefits, missing customer specifics, missing data, missing screenshot/UI evidence, or unclear next step

Rewrite source material into:

- claim-led slide headlines
- one-sentence takeaways
- concise proof labels
- buyer-facing outcomes
- stronger section titles
- callout copy and captions
- final-ask language

Rules:

- Do not invent metrics, client proof, product capability, pricing, timelines, or guarantees.
- Keep source truth intact while improving hierarchy, compression, and persuasion.
- Mark assumptions and missing proof instead of hiding them inside polished language.
- Use the optimized copy as the input to the story spine, not the raw document prose.

## Stage 4: Story Spine

For each slide, define:

- slide number
- slide type
- claim
- proof object
- commercial highlight
- primary content
- secondary content
- optimized headline or takeaway
- visual role
- editability requirements

Common slide types:

- cover
- section divider
- executive summary
- agenda
- problem/framing
- market/context
- data/chart
- comparison
- process/flow
- architecture/system
- roadmap/timeline
- case study
- recommendation
- closing/ask
- appendix/table

## Stage 5: Storyboard And Slide Architecture Approval

Turn the story spine into a storyboard before visual exploration.

For each slide, define:

- audience question answered
- narrative beat
- claim
- proof object
- commercial role: anchor, support, transition, appendix
- emotional intensity
- information density
- expected action or takeaway
- likely layout archetype
- dependencies: data, screenshot, brand asset, generated asset, chart, diagram, or missing input

Storyboard approval rules:

- For client-ready, investor, executive, sales, or high-stakes work, ask the user to approve, revise, or delegate storyboard approval before final PPTX production.
- Do not treat visual scheme selection as storyboard approval.
- If the storyboard is delegated to the agent, record the rationale and risks.
- Do not proceed with an incoherent, repetitive, proof-light, or decisionless storyboard.

## Stage 6: Visual Exploration Pages

Pick pages that prove the design can handle the deck:

- one identity page: cover or chapter opener
- one argument page: thesis or executive summary
- one evidence page: chart, table, or metric page
- one structure page: process, architecture, or framework
- one decision page: roadmap, recommendation, or closing ask

Use the same pages across all schemes.

## Stage 7: Market-Informed Design DNA Judge

Run this gate before imagegen prompting. The goal is to make the agent choose like a commercial design director instead of guessing style words.

Read `design-dna.md` before this stage and use it as a starting library, not as a fixed menu. Adapt or combine archetypes when the deck's business goal requires it.

Create 3-5 candidate design DNA directions. A design DNA is not a template name; it is a reusable visual strategy:

- user-facing display name in the user's language; for Chinese users, Chinese first and English only as optional secondary notation
- internal slug when useful for filenames or prompts
- commercial context: pitch, sales, training, investor, executive briefing, brand launch, product narrative, or consulting report
- audience belief shift: what the audience must believe after the deck
- visual drivers: typography, imagery, composition, texture, material, data treatment, icon language, and motion rhythm
- slide archetypes: which pages it makes strong, such as cover, thesis, pain wall, service system, proof dashboard, process, case proof, or closing ask
- asset needs: hero background, texture, signature mark, product metaphor, photo strip, or none
- editability plan: what remains native PPT and what can be raster
- risks: trendiness, weak credibility, poor editability, visual fatigue, generic template feel, or mismatch with audience

Score every DNA from 1-5:

- commercial fit: supports the deck's business goal
- visual distinction: avoids generic template sameness
- industry credibility: fits the user's domain and buyer expectations
- editability: can be rebuilt as native PPT components with separate raster assets
- deck-wide scalability: can carry 8-20 slides without becoming repetitive
- imagegen promptability: can be described concretely enough for imagegen to explore
- risk control: avoids over-decoration, fake UI, unreadable details, or copied-template feel

Selection rules:

- Keep only the strongest 2-3 DNA directions for imagegen visual schemes.
- When the default checkpoint will show 3 schemes, keep 3 independently scored finalists. Do not synthesize an unscored hybrid/fusion direction from two finalists merely to create a third option. If a hybrid is commercially useful, define and score it as its own DNA before imagegen.
- Include one safer commercial option and one bolder option when the user's goal permits.
- The selected DNA set must span different visual strategies. Vary at least four of these dimensions across the candidates: dominant visual anchor, composition rhythm, material/lighting treatment, palette family, information density, image-vs-type balance, and emotional temperature.
- Do not accept three directions that are all blue/purple enterprise dashboards, all dark command centers, all card-grid SaaS templates, or all minimalist consulting pages. If the difference is mainly palette, the DNA selection failed.
- Reject any direction scoring below 4 in commercial fit, industry credibility, or editability.
- Reject any direction whose value is only palette, gradients, or fashionable decoration.
- Do not reference or imitate a specific paid template, marketplace listing, brand, or living designer. Abstract reusable traits into a new direction.

Short example:

```text
DNA: 战略 AI 指挥中心（AI Command Center）
Why it fits: enterprise AI service deck needs system credibility and operational control.
Visual drivers: dark command-room canvas, modular system topology, restrained glow, sharp labels, one oversized thesis line.
Powered pages: cover, service system, architecture, proof dashboard, closing roadmap.
Asset needs: cover background, subtle data-field texture, one platform metaphor.
Scores: commercial fit 5, visual distinction 4, credibility 5, editability 4, scalability 4, promptability 5, risk control 4.
Risk: can become generic cyber-tech if glow and fake UI dominate; keep diagrams native and sparse.
```

## Stage 8: Imagegen Visual Scheme Prompt

Use one prompt per scheme. The output is one standalone scheme thumbnail/contact sheet, not a final PPT and not a combined A/B/C comparison image.

This stage must call imagegen and produce visible image outputs. Written design DNA descriptions, prompt text, or option names are not visual schemes.

In QwenPaw, call the unified `imagegen` tool for this stage. Use
`aspect_ratio="16:9"` for PPT visual directions unless the user requests a
different format, and record the returned saved path or embedded preview before
asking the user to choose.

Pass a structured `presentation_context` on every call:

```json
{
  "stage": "visual_scheme",
  "deck_topic": "<topic>",
  "audience": "<audience>",
  "direction_name": "<localized selected DNA name>",
  "visual_temperature": "bold | balanced | restrained",
  "dominant_visual_anchor": "<one dominant anchor>",
  "commercial_rationale": "<why it fits>",
  "represented_pages": ["cover", "thesis", "evidence", "process/architecture", "roadmap/closing"],
  "forbidden_patterns": ["<scheme-specific collapse patterns>"]
}
```

The tool compiles this into the Codex-style `Use case: productivity-visual`
prompt contract and writes a sibling `*.imagegen.json` record containing the
original prompt, effective submitted prompt, context, and generation settings.

Do not ask imagegen to create one combined comparison image containing all 2-3
candidate schemes. Do not compose a post-generation montage for the chat either.
Combined images bias the model toward one shared table/grid format, repeated
slide-template structures, and conservative enterprise-PPT visual convergence.
Generate each scheme independently, then present the separate images in the
conversation as one block per scheme: scheme name, single image, short note.

Visual divergence contract:

- Scheme A should normally be the highest-impact or most expressive commercial option the brief can tolerate: cinematic metaphor, editorial crop, spatial environment, strong type, or bold contrast.
- Scheme B should normally emphasize credible product/system thinking: architecture, platform modules, operational maps, evidence rhythm, and precise native-PPT redraw potential.
- Scheme C should normally be the cleanest or most restrained option: consulting editorial, warm human-service tone, or low-noise executive clarity.
- These are not fixed names. Localize the scheme names in Chinese, but keep the roles distinct unless the user asks for a narrower range.
- Each scheme must name `visual_temperature` (`bold`, `balanced`, or `restrained`), `dominant_visual_anchor`, and `forbidden_patterns`.

Prompt pattern:

```text
Use case: productivity-visual
Asset type: visual direction contact sheet for an editable PowerPoint deck
Primary request: Create a 16:9 contact sheet showing 5 miniature slide compositions for the same deck: cover, thesis, chart/evidence, process/architecture, and roadmap/closing.
Deck topic: <topic>
Audience: <audience>
Style direction: <selected design DNA name and visual drivers>
Visual temperature: <bold | balanced | restrained>
Dominant visual anchor: <cinematic metaphor | editorial crop | product/platform scene | spatial system map | material surface | type-led composition | other>
Commercial rationale: <why this DNA fits the deck goal and audience>
Content constraints: Use only large placeholder headings and simple labels. No small body text, no dense tables, no precise numbers, and no finished text-heavy slide screenshots.
Composition: Show distinct slide rhythms that could later be rebuilt with editable PPT components.
Avoid: rasterized small text, fake unreadable charts, decorative clutter, generic SaaS card grids, stock PPT templates, repeated rounded rectangles, tiny UI labels, blue-purple dashboard sameness, watermarks, logos unless provided.
Forbidden patterns for this scheme: <patterns that would make this scheme collapse into generic enterprise PPT>
```

The text prompt and `presentation_context` are both required: the prompt carries
the art direction; the context makes the stage, selected DNA, visual temperature,
anchor, and provenance mechanically visible to the runtime.

Generate visually distinct directions, for example:

- 编辑权威型：强字体、克制配色、非对称图文排版
- 高管分析型：高信息密度但清爽，适合原生图表和清晰层级
- 高级产品叙事型：电影感画面、留白、强主张、少而准的标注
- 技术平台蓝图型：系统图、明暗对比、精准标签、模块化架构语言
- 工作坊手册型：友好色彩、清晰步骤、便于交付的方法框架

Required output before Stage 9:

- scheme localized name
- imagegen prompt
- generated contact sheet or thumbnail path
- inline preview when the client supports local images
- the 4-5 represented slide archetypes
- notes on what the image shows and what remains only an implementation inference

Conservative-lock QA before Stage 9:

- Regenerate the batch before asking the user to choose if all generated schemes share the same blue/purple/dark technology palette, the same card-grid grammar, the same center-title/body-panel layout, or the same generic SaaS dashboard feeling.
- Regenerate any scheme whose contact sheet contains too much fake body copy, tiny labels, fake charts, or unreadable UI text. Visual direction thumbnails may include only large headings and simple labels.
- Regenerate if no scheme has a clear dominant visual anchor beyond color, gradients, icons, or ordinary rounded rectangles.
- Regenerate if the bolder direction is not meaningfully bolder than the restrained direction.
- When regenerating for this reason, explicitly add "increase visual courage, stronger composition contrast, less generic enterprise dashboard, fewer cards, fewer fake UI labels" to the next imagegen prompt.

If imagegen fails or produces unusable/blank images, regenerate or stop. Do not move to visual selection with only text descriptions.

## Stage 9: Visual Scheme Selection Gate

Stop after generating the visual direction thumbnails. This checkpoint is mandatory unless the user already explicitly delegated selection before thumbnails were generated.

Return:

- the 3 generated visual scheme thumbnails or contact sheets, shown as separate images
- local paths or embedded previews for every generated thumbnail/contact sheet
- no combined comparison image as the only visual selection UI
- a concise comparison: commercial fit, visual distinction, editability risk, asset needs, and likely failure mode
- your recommendation if useful, clearly labeled as a recommendation
- a direct request for the user to choose one scheme, ask for revisions, or delegate the choice
- an explicit "none of these / regenerate another batch" option
- user-facing scheme names and option labels in the user's language. For Chinese users, use Chinese option names and Chinese prompt text.

Invalid checkpoint:

- only listing design DNA names
- only listing prompt titles
- only giving text descriptions
- asking the user to choose before imagegen returns visible thumbnails/contact sheets

Chinese checkpoint example:

```text
我先停在视觉方案选择门。请选择一个方向，或告诉我需要重做哪一类：

1. 战略 AI 指挥中心
2. 咨询式运营系统画册
3. 技术蓝图 + 人本落地
4. 都不喜欢，换一批

我的建议：优先选 2，因为它更适合客户销售/提案型手册，也更容易落成可编辑 PPT。
```

Do not continue to design-system extraction, asset-suite generation, `presentation_builder`, or PPTX creation until one of these is true:

- the user selects a scheme after seeing the generated visual thumbnail/contact sheet
- the user asks for a specific revision and the revised schemes are generated
- the user says none are suitable and a new batch is generated, then the selection gate repeats
- the user explicitly says the agent may choose after the generated visuals are available

Regeneration rules:

- If the user says "都不喜欢", "换一批", "重新来", or equivalent, do not defend the current options and do not continue production.
- Ask for lightweight feedback only when useful, such as "更高级/更大胆/更稳重/更科技/更少黑色/更像咨询公司/更像产品发布"; do not require feedback before regenerating if the user wants speed.
- Generate a fresh batch of 3 visual contact sheets. Keep the same deck brief and storyboard unless the user asks to change them.
- Decide whether to keep the same design DNA, adjust the DNA mix, or restart DNA selection. Record the decision.
- Repeat Stage 9 with the new images and increment the regeneration round.

Record the selected scheme as:

```text
视觉方案选择记录：
- 已选方案：
- 选择来源：用户选择 | 用户授权代选 | 按反馈重做后选择
- 重生成轮次：
- 重生成原因：
- 选择原因：
- 未选方案：
- 需要控制的风险：
```

## Stage 10: Design System Extraction

After the user selects a scheme, convert it into implementation rules:

- selected design DNA: name, rationale, scores, risks, and survival rules
- palette: background, text, accent, muted, chart colors
- typography/font system: verified or assumed fonts, Chinese/English/number pairing, fallback stack, type scale, weights, line spacing, and license/delivery caveats
- grid: margins, columns, safe zones, alignment rules
- objects: cards, callouts, pills, dividers, arrows, connectors
- charts: axis treatment, labels, legend placement, annotation style
- diagrams: node style, connector style, hierarchy, density limits
- master layouts: cover, section, thesis, summary, evidence, process, architecture, case proof, roadmap, offer/ask, appendix/table
- information design: evidence rules, chart selection, diagram topology, screenshot treatment, annotation style, source/caveat notes
- imagery: crop style, aspect ratios, overlays, when to use full-bleed assets
- slide rhythms: which archetypes repeat and where
- visual drivers: hero imagery, photographic metaphors, texture, lighting, material finish, decorative marks, icon style, and signature page compositions
- implementation strategy: native-only, hybrid layered, or template-following; state why the chosen strategy can preserve the visual direction in the final PPTX
- commercial anchor pages: which 2-3 slides will carry the buyer's memory of the deck

State which details are inferred rather than visible in the thumbnail.

If the selected scheme depends on texture, cinematic imagery, dimensionality, lighting, editorial photography, or complex atmosphere, native-only implementation is a risk. Plan hybrid layers before PPT generation.

### Visual-Translation Contract

Before slide production, deconstruct the selected contact sheet into a contract that can be executed in editable PPT:

- scheme archetypes: cover, thesis, metric/evidence, product/platform, mechanism/process, roadmap, closing, or appendix
- dominant visual anchors: large hero object, full-bleed scene, cinematic crop, oversized metric, product metaphor, operating loop, photo strip, or type-led composition
- focal ratio: approximate visual weight split, such as 60% visual / 40% text, 30% metric / 50% scene / 20% support, or type-led with minimal imagery
- text zones: title zone, body zone, caption/source zone, and areas that must remain empty
- visual atmosphere: lighting, material finish, depth, texture, contrast, crop style, and edge behavior
- typography rhythm: display/title scale, metric treatment, label density, Chinese/Latin/number pairing, and line-length limits
- native/raster split: what becomes editable text/shapes/charts/connectors and what remains raster atmosphere or visual metaphor
- forbidden drift: generic card grids, weak icon rows, office-style arrows, small decorative stickers, color-only matching, or asset-quota decoration

For each of the 4-5 selected visual exploration pages, create a page-archetype mapping:

```text
Page archetype:
- source contact-sheet page:
- production slide(s):
- dominant visual anchor:
- focal ratio:
- editable text zone:
- required page-bound asset:
- native component grammar:
- assets that must not be forced:
- redesign trigger:
```

If a page is stronger without a generated icon, arrow, badge, or small component, mark that family as intentionally omitted for that slide. Do not compensate by adding unrelated decoration.

Read `typography-system.md` before finalizing the design system. Fonts must be treated as a design decision and a delivery risk:

- choose display, primary Chinese, primary Latin, numeric, body, caption, and optional mono/code roles
- record whether fonts are system defaults, verified installed fonts, provided font files, or required user dependencies
- define fallback behavior for Windows, macOS, and rendered preview environments when relevant
- define a type scale in points for cover title, section title, slide title, body, caption, label, metric, callout, and footnote
- limit the number of font families and weights so the deck remains coherent and editable
- avoid using imagegen or raster text to fake font appearance

Read `information-design.md` before finalizing chart, diagram, table, and evidence rules.

## Stage 11: Slide Art Direction

Write art direction before generating the final deck. This is the bridge between a beautiful imagegen direction and an editable PPT implementation.

For every non-appendix slide, define:

- page role: impact, explanation, evidence, transition, decision, or closing
- desired feeling: premium, urgent, confident, cinematic, analytical, sober, editorial, technical, warm, or playful
- focal point: the one thing the viewer notices first
- composition: full-bleed hero, split editorial, asymmetrical stage, dense dashboard, process map, oversized quote, image strip, modular system, or calm table
- hierarchy: title scale, supporting copy position, metric/callout weight, caption treatment
- visual anchor: generated asset, chart, diagram, photograph, type-led composition, or native shape system
- selected-scheme archetype and contact-sheet reference
- focal ratio and text-safe zone inherited from the visual-translation contract
- negative space: where not to place text or objects
- forbidden patterns: generic card grid, centered title plus bullets, weak icon row, decorative-only background, or repeated template layout
- asset needs: which generated/provided assets are required and where they sit in the layer stack

Short example:

```text
Slide 3 / Service system
Role: impact + explanation.
Focal point: three service pillars behaving like one operating system, not three ordinary cards.
Composition: dark full-bleed background with a central control-core ring; three large vertical modules orbit the core; title is oversized at top left.
Hierarchy: title first, three module names second, one-line outcomes third.
Native PPT: module frames, icons, labels, connectors.
Raster: background texture and soft light field only.
Forbidden: equal-height rounded SaaS cards on a flat background.
```

## Stage 12: Motion Direction And Reveal Plan

Write motion direction after art direction and before component/library generation. This turns a static slide sequence into a presentation rhythm.

For every non-appendix slide, define:

- motion role: static-anchor, reveal, contrast, sequence, proof-build, emphasis, transition, or payoff
- presenter beat: what the speaker says or proves at this click
- reveal order: title, visual anchor, data, callout, supporting copy, caveat, or ask
- object grouping: which elements appear together and which must wait
- transition style: cut, fade, push, zoom, wipe, section-break, match-cut, or none
- pacing: one-shot, 2-step, 3-step, or multi-step
- implementation mode: native-animation, step-build-slides, hybrid, or static-by-design
- fallback: how to preserve the intended rhythm if native animation is unavailable

Motion principles:

- Use motion to direct attention, not decorate the slide.
- Make commercial tension visible: reveal the pain before the solution, the comparison before the conclusion, the evidence before the claim, and the final ask after the payoff.
- Keep motion sparse. Most strong business slides need 1-3 beats, not continuous animation.
- Use editable step-build slide variants when native animation support is unclear or unreliable. Name them as `Slide 5A`, `Slide 5B`, `Slide 5C` in the internal plan, but keep the visible slide number clean unless the user asks otherwise.
- Step-build variants must remain native/editable: duplicate the slide, add or emphasize the next object group, and preserve consistent geometry so the sequence feels like animation.
- Do not use screenshots to simulate animation.

Short example:

```text
Slide 6 / Operating model
Motion role: sequence + proof-build.
Presenter beat: "The value is not three separate services; it is a compounding operating loop."
Reveal order: title -> central operating loop -> three service modules -> outcome metric strip.
Transition: cut from prior pain slide, then 3 click step-build.
Implementation mode: step-build-slides.
Fallback: create slides 6A/6B/6C with stable positions and progressively added modules.
```

## Stage 13: Master Layout And Design Component Library

Create a deck-specific master layout and component library after art direction and motion direction, before PPT generation. The library prevents each slide from becoming a random arrangement of rectangles and ensures repeated components can support reveal states.

Define master layouts the deck needs:

- cover
- section divider
- thesis/manifesto
- executive summary
- evidence/chart page
- process/architecture page
- case proof page
- roadmap/timeline
- offer/ask page
- appendix/table

For each master layout, define:

- margins and safe zones
- title, body, visual, footer, and page-number zones
- grid and alignment rules
- image and chart placement rules
- editable object rules
- allowed variants
- failure modes

Include only components the deck needs. Common component families:

- hero cover: full-bleed image/texture plus editable title stack
- manifesto/thesis: oversized typography, sharp quote/callout, minimal support copy
- pain wall: multiple pain points with editorial severity treatment, not uniform cards
- service system: modules connected into a system, platform, or operating model
- metric dashboard: native metrics/charts with strong scale contrast
- process map: steps, lanes, arrows, milestones, and decision points
- case proof strip: image panels plus editable outcomes and claims
- comparison wall: before/after or old/new structure with visible contrast
- offer/partnership page: pricing/cooperation blocks with clear primary path
- closing ask: emotional visual anchor plus concise editable call to action

For each component, define:

- intended slide types
- native PPT parts
- optional raster layers
- layout rules
- text hierarchy
- density limit
- variants
- failure modes

Failure modes to catch early:

- all components have the same border radius, shadow, and spacing
- icons are decorative but do not clarify meaning
- content is placed into cards because no stronger composition was chosen
- every page uses a safe centered title plus three columns
- visual assets appear as wallpaper instead of driving composition
- connectors, arrows, and lines look like default office controls instead of a designed diagram language
- raw source paragraphs are placed into boxes without presentation compression
- each slide becomes a one-off layout with no master rhythm
- footer, page number, source note, and caption rules drift across slides

## Stage 14: Visual Asset Suite

Read `asset-suite.md` before this stage.

After choosing a scheme, decide whether native PPT shapes alone can preserve the selected style. If the scheme depends on cinematic images, expressive backgrounds, editorial photography, texture, brush marks, atmospheric lighting, rich icon treatments, module surfaces, connector language, or data badges, generate a visual asset suite before building the deck.

For client-ready output, the asset suite usually needs more than cover and closing backgrounds. Body-slide assets may include light blueprint plates, dark system plates, texture overlays, image strips, signature marks, icon/pictogram families, connector treatments, module surfaces, data badges, diagram accents, or panel treatments. Generate only assets that change composition or perceived quality; avoid generic wallpaper.

Default quantity guidance:

- For a 10-15 slide client-ready deck, generate 6-10 source asset sheets or source images, not dozens of disconnected images.
- Extract or crop roughly 10-25 reusable visual elements from those sheets when the deck needs them.
- Generate 3-5 page-bound hero/background/metaphor assets for the representative pages when the selected contact sheet depends on dominant visual anchors. These are not reusable kit stickers; they carry the composition of key slides.
- Use 1 icon/pictogram sheet, 1 module surface sheet, 1 connector/node/diagram accent sheet, 1 data badge or metric container sheet, 2-4 texture/background plates, and 1-3 section, closing, case, product, or metaphor images as needed.
- For shorter decks, reduce the suite. For decks above 20 slides, add assets only when a new slide archetype or chapter system requires them.
- More than 10 source asset sheets requires a reason recorded in the asset plan.
- Any asset intended to cover the whole slide must be a 16:9 full-bleed plate. Do not use a small tile extracted from a multi-item sheet as a full-slide background unless it has been rebuilt into a 16:9 plate and passes edge-coverage QA.
- Background, hero, texture, and section-divider plates must be text-free except for intentionally abstract brand marks or one large decorative wordmark. Reject body copy, tables, dense UI labels, miniature slide systems, or finished page screenshots as direct backgrounds; rebuild their content as editable PPT text and native shapes.

Prepare an asset plan:

- asset id and filename
- asset type: cover background, section background, closing background, body texture plate, abstract scene, photo metaphor, texture overlay, brush stroke, signature mark, pictogram family, module surface, connector treatment, data badge, diagram accent, case image strip, product/platform visual
- source asset sheet id when an element is extracted from a sheet
- target slide(s)
- prompt summary
- safe crop area
- layering role: background, midground, foreground accent, texture, or image panel
- editability boundary: what remains raster and what must be rebuilt as native PPT components
- linked art direction: which slide/component requires it
- usage mode: direct raster crop, native redraw reference, hybrid, or omitted
- minimum expected usage count
- maximum expected direct raster usage count
- asset fitness: production-ready, reference-only, accent-only, or reject
- safe text area requirement and scaling rule for any component-like asset

Run an asset fitness gate before PPTX generation:

- `production-ready` assets may be placed directly when they have a complete crop, intact edges, role match, no embedded real text, and safe aspect ratio.
- `reference-only` assets should define visual grammar for native redraws, not become text containers.
- `accent-only` assets may be small decorative or symbolic marks, not cards, inputs, or panels.
- `reject` assets must be removed or regenerated.

Direct raster density guardrail for a 10-15 slide deck:

- pictograms: about 6-12 total direct raster uses
- module surfaces: about 3-8 direct raster uses
- connector/node motifs: about 2-6 direct raster uses
- data badges: about 2-5 direct raster uses
- case/product image strips: about 2-4 direct raster uses

Do not solve unused asset sheets by flooding the deck with cropped icons, panels, connectors, or badges. Record a rationale and pass full-size visual QA before exceeding the density budget.

Recommended asset types:

- full-bleed hero background for the cover or strongest chapter opener
- page-bound hero or metaphor plate for key thesis, metric, platform, mechanism, roadmap, or closing slides
- closing/ask background when the chosen scheme uses cinematic emotional payoff
- section divider background or pattern system
- texture overlays such as paper grain, metal finish, noise, scanlines, fabric, ink, or light leaks
- signature marks such as brush strokes, underline slashes, glows, frames, or map/radar lines
- image panels for case proof pages, avoiding fake screenshots or invented evidence
- icon/pictogram families that clarify concepts and share one visual grammar
- connector treatments for process, architecture, and service-system pages
- module surfaces or frames for product/platform/service components
- data badges and diagram accents for proof pages
- image treatment references when native icons cannot carry the desired style

Generation rules:

- Generate separate reusable assets, not final slide screenshots.
- Generate page-bound hero assets with reserved editable text areas when the visual scheme's impact comes from a large scene or metaphor. Do not replace those anchors with tiny icon kit elements.
- Do not include real slide copy, charts, tables, small labels, logos, or precise numbers inside generated assets.
- Keep important visual regions away from areas reserved for editable titles and body text.
- Save project-bound assets into the deck workspace, not only under the default imagegen output folder.
- Record every generated asset path in the handoff before `presentation_builder` work starts.
- Generate fewer, stronger assets rather than many generic backgrounds.
- Prefer coherent asset sheets for families of icons, panels, connectors, badges, and diagram accents; generate individual images for large backgrounds, scene strips, or single-use metaphors.
- Separate full-bleed background plates from overlay texture tiles. Background plates must fill the complete slide; texture tiles may support atmosphere but must not create side bars or margins.
- Classify text-heavy generated page images as reference-only or reject for direct raster placement. They can guide the visual-translation contract, but they must not be listed in `required_image_assets` with `background`, `hero`, or `wide` roles.
- If an asset does not change the page composition, remove it or regenerate it.
- A background-only set fails this stage unless the design system is deliberately native-only and commercial QA confirms the body slides still look designed.
- Do not use default PowerPoint-looking lines, arrows, generic icon rows, or control-like widgets as substitutes for the asset suite.

Create an asset-to-slide usage matrix before PPTX generation:

- For every generated asset family, list target slides, component role, usage mode, and minimum expected usage count.
- Include maximum expected direct raster usage, asset fitness, direct-raster approval, native-redraw requirement, and safe text area requirement.
- Backgrounds and textures do not count as sufficient component-suite usage by themselves.
- For a 10-15 slide client-ready hybrid deck, plan visible use or native translation of at least 4 non-background families, such as pictograms, module surfaces, connector treatments, data badges, case/product image strips, or signature marks.
- If an approved family will not be used, mark it as omitted with a reason before generation starts.
- If a slide's visual-translation contract says an asset family must be omitted, that omission is preferred over quota-driven decoration.

Lightweight preview gate:

- For client-ready hybrid decks, show asset-sheet previews or paths before PPTX generation unless the user delegated production or the implementation is explicitly native-only.
- Summarize which asset families support which slide archetypes and what remains editable native PPT.
- For Chinese users, ask in Chinese with options such as "继续制作", "换一批组件", "减少图片感、提高可编辑性", and "增强视觉冲击".
- If the user wants changes, regenerate the weak family rather than restarting the selected visual scheme unless the whole scheme is wrong.

Prompt pattern:

```text
Use case: productivity-visual
Asset type: reusable visual asset suite element for an editable PowerPoint deck
Primary request: Create <asset type> for a deck about <topic>.
Style direction: <selected scheme name and visual drivers>
Composition: <full-bleed / left visual area / right visual area / texture-only / transparent-like mark>
Reserved text area: Leave <area> visually calm for editable PPT text overlays.
Content constraints: No readable text, no labels, no numbers, no charts, no logos unless provided.
Output role: This will be placed as a separate image layer behind editable PowerPoint text and shapes.
Avoid: complete slide layout, fake UI details, watermarks, clutter, tiny typography, stock-photo blandness.
```

For each Stage 14 call, also pass:

```json
{
  "stage": "visual_asset",
  "deck_topic": "<same topic as selected scheme>",
  "audience": "<same audience as selected scheme>",
  "direction_name": "<exact selected scheme name>",
  "commercial_rationale": "<same selected-scheme rationale>",
  "asset_type": "<cover hero background | platform visual | texture plate | pictogram sheet | ...>",
  "composition": "<placement and crop>",
  "reserved_text_area": "<calm editable text zone>",
  "output_role": "<separate raster layer role>",
  "forbidden_patterns": ["<asset-specific failure modes>"]
}
```

Use the generated `*.imagegen.json` ledgers to verify that downstream assets keep
the exact selected `direction_name`. A style change between selection and asset
production is a failed gate, not harmless prompt variation.

## Stage 15: Information Design And Evidence System

Read `information-design.md` before this stage.

For every data, table, process, architecture, comparison, roadmap, operating model, screenshot, or evidence-heavy slide, define:

- decision question
- claim
- evidence source
- proof object
- chart/diagram/table choice and rationale
- annotation strategy
- source or assumption note
- density limit
- editable objects
- reveal behavior
- caveats or missing proof

Rules:

- Choose charts by comparison task, not by decoration.
- Use diagram topology deliberately: linear, loop, hub-and-spoke, layered stack, matrix, swimlane, ecosystem, funnel, roadmap, or map.
- Use real screenshots only when provided or clearly mark placeholders.
- Highlight signal and mute context.
- Every evidence slide must have a one-sentence takeaway.
- Do not create fake proof to make the deck feel complete.

## Stage 16: Editable PPT Generation

Before calling `presentation_builder`, prepare a structured handoff:

- source brief
- creative brief and agency success bar
- brand/source asset audit
- copy strategy and extracted commercial highlights
- slide schema
- storyboard and approval/delegation record
- selected design DNA, scores, risks, and survival rules
- visual scheme selection record
- visual-translation contract with page archetype map, focal ratios, text zones, dominant visual anchors, native/raster split, and forbidden drift
- design system spec
- typography/font system with font availability, fallback stack, type scale, and delivery caveats
- information design system
- master layout system
- slide-by-slide art direction
- slide-by-slide motion direction and reveal plan
- design component library
- selected visual scheme path or inline preview
- visual asset suite paths, usage notes, crop notes, editability boundaries, and provenance
- prototype checkpoint record when required: rendered 3-5 slide prototype paths, user approval/delegation/revision choice, and changes made before full production
- final delivery contract: PPTX/PDF primary task artifacts plus internal `*.presentation.compose.json` source ledger
- final output location and filename preference

QwenPaw presentation builder gate:

- Use the built-in `presentation_builder` tool for PPTX/PDF export.
- Do not write ad hoc `python-pptx`, temporary ESM, or shell-generated PPTX scripts for the final deck when `presentation_builder` is available.
- Resolve one authoring route before preparing the payload: a supplied PPTX plus clone/edit map uses `route_mode="template_following"`; an explicit user-selected visual scheme or completed visual-translation contract uses `route_mode="custom_compose"`; only a deck without a governing template or explicit visual direction uses `route_mode="codex_grid"`.
- `custom_compose` is the parity route for the Codex custom-formatting branch. Pass `compose_spec` with `schema_version`, 13.333 x 7.5 `slide_size` using canonical `width`/`height`, the selected-scheme `theme`, a non-empty inline `visual_translation_contract`, optional `native_translation_rationale`, and per-slide `archetype`, named editable `layers`, and `expected_content` assertions. The runtime accepts `w`/`h` aliases, but canonical names make the contract easier to audit.
- Supported custom layer types are `text`, `shape`, `line`, and `image`. Every layer requires a unique name and exact `x/y/w/h` bounds. Use `expected_content.required_text`, `required_layer_names`, `layer_type_counts`, and `semantic_group_counts` to turn business-content preservation into a failing QA gate instead of a visual-review guess.
- Pass `expected_slide_count` on every prototype and final build. It must equal the selected representative-page count for a prototype and the approved storyboard count for final delivery. A mismatch is a hard content-preservation failure, not permission to consolidate slides silently.
- If a `custom_compose` call fails, fix the reported payload error and retry `custom_compose`. Never recover by switching to `codex_grid` after a visual scheme has been selected. Sibling imagegen provenance records bind production assets to their selected `direction_name`, and the runtime rejects a Codex Grid downgrade or mixed-direction asset set.
- Prepare `theme` with at least `mode`, `accent`, and `font_family`; use the selected visual direction to choose colors and typography.
- Prepare `delivery_mode="final"`, the approved storyboard `expected_slide_count`, `strict_qa=true`, `render_qa=true`, `export_pdf=true`, and `include_compose_manifest=true` for client-ready or final delivery. In service workspaces, `presentation_builder` treats auto mode as final, but pass these fields explicitly so the intent is visible in the tool call.
- Pass `requires_visual_assets=true` when the production deck uses direct raster visual assets. In `custom_compose`, declare every direct raster placement as an image layer and include its source in `required_image_assets`; do not also pass `asset_usage_matrix`. A reference-only moodboard/component sheet may be translated into native layers only when `requires_visual_assets=false` is paired with a concrete `native_translation_rationale` and the editable prototype visibly preserves its composition, focal scale, material treatment, and rhythm.
- Prepare `slides` as structured slide objects with editable title/body/bullets, layout-specific content, and any direct slide image placements.
- On the `codex_grid` route, every slide must specify or clearly imply a layout. Prefer `image_hero`, `section`, `agenda`, `cards`, `comparison`, `process`, `roadmap`, `metrics`, `table`, `architecture`, `quote`, `two_column`, or `content`; do not repeatedly use generic title/body pages.
- Use `items` for card grids and architecture/module maps, `columns` for comparison/two-column pages, `steps` for process/timeline/roadmap slides, `metrics` for KPI pages, and `table.headers/table.rows` for evidence tables.
- If a reference/template PPTX is provided, inspect the source slides and prepare `template_frame_map`; every output slide must name a `sourceSlide`. Use `editTargets` to rewrite inherited text or replace inherited pictures, then pass both `template_path` and `template_frame_map`. Treat `template_mode=clone_edit`, `template_source_slide_count`, `template_media_count`, and `template_placeholder_count` as QA evidence.
- Prepare `required_image_assets` as the list of generated image paths that must appear as direct raster images in the final PPTX. Do not include component sheets, icon sheets, module sheets, connector sheets, moodboards, or style-reference boards that are only native-redraw references.
- Prepare `asset_usage_matrix` before calling the tool for service-native layouts. Each entry must include `asset_path` (or `path`), a 1-based `slide_index`, a direct-raster `role` such as `hero`, `background`, `wide`, `thumbnail`, `figure`, or `diagram`, and a short `purpose` explaining why that image belongs on that slide. For template clone/edit, put generated assets in `template_frame_map[].editTargets[]` with `action: "replace-image"` and include the same paths in `required_image_assets`.
- If a generated asset is not suitable for direct raster use, either remove it from `required_image_assets` with a recorded rationale or translate it into native PPT components and record that mapping.
- For final delivery, PPTX/PDF 是面向用户的任务主制品；`*.presentation.compose.json` 是内部来源账本，用于复现 80-layout 选择、素材映射、QA 和 rebuild provenance，不作为用户主交付物展示。
- After `presentation_builder` returns, read its Delivery, QA, and render QA lines. Delivery must report `delivery_mode=final`, `export_pdf=true`, a PDF output, and `compose_manifest=...`; if required images were used, `media_count` and `pic_count` must both be greater than zero and at least match the mapped image count. `layout_variety` should reflect the master layout system, `weak_slide_count` and `overlap_count` should be 0 for client-ready decks, `qa_warnings` should be 0, and render QA should report `render_qa=ok` plus `rendered_slide_count` before delivery. If not, revise the specs/matrix and rebuild.
- Inspect the render QA `contact_sheet=...` path or per-slide PNG previews referenced in the tool text before delivery. These render previews are internal QA artifacts, not user-facing task deliverables. Treat text clipping, unexpected wrapping, broken image frames, missing template chrome, and visible overlap as rebuild blockers.

Implementation requirements:

- Use editable text boxes for all real text.
- Apply the selected typography/font system to every editable text box, metric, label, chart annotation, table cell, and caption.
- Apply master layout rules before making slide-specific composition decisions.
- Apply the visual-translation contract before choosing components. A key slide's dominant visual anchor, focal ratio, text zone, and page archetype should decide the layout before any kit asset is placed.
- Use native shapes for cards, frames, dividers, pills, timeline bars, and diagram nodes.
- Use connectors or lines for flows and architecture maps.
- Use native charts/tables when data is structured.
- Apply information design rules to charts, tables, diagrams, screenshots, annotations, source notes, and evidence callouts.
- Use images as separate objects with meaningful crop and placement.
- Use generated backgrounds, textures, and image metaphors as layered assets, while keeping titles, captions, metrics, bullets, charts, and diagrams editable.
- Match the selected scheme's composition, visual anchors, contrast, material treatment, and page rhythm, not only its color palette.
- Use optimized headlines and highlights; do not dump raw source copy into generic text boxes.
- Follow each slide's art direction. If implementation constraints require a deviation, record the deviation and compensate visually.
- Follow each slide's motion direction. If native animation is not supported by the current PPTX builder path, build editable step-build slide variants and record the mapping from original slide to variants.
- Use the component library before inventing a new component style.
- Use visual asset suite elements for icons, connector treatments, module surfaces, data badges, and supporting imagery where the design direction requires them.
- For every slide, consult the asset-to-slide usage matrix before drawing generic shapes. Use the planned asset directly, crop it from the sheet, or translate it into native PPT components with a recorded mapping.
- Do not leave approved asset sheets as mood references only. If a family is generated, it must either appear, be translated, or be deliberately omitted with rationale.
- Do not place any icon, arrow, badge, small picture, or connector only to satisfy an asset count. Remove assets that do not strengthen the slide's story, information design, or composition.
- Use direct raster components only when the asset fitness gate approved them as `production-ready`. Otherwise translate the asset into native PPT shapes or use it as a small accent.
- Do not use `fit: "cover"` or arbitrary stretching on raster panels, badges, input-box-like frames, or connector components whose border/frame must remain intact.
- When a component visually contains text, create the text with native PPT text boxes inside a declared safe text rectangle with padding; verify containment in the rendered slide.
- Prefer native redraw for repeated cards, module surfaces, service panels, data badges, connector paths, and input boxes. Native redraw must preserve the chosen visual DNA rather than falling back to plain rounded rectangles.
- Respect the direct raster density budget. A slide with many cropped kit elements should justify why each raster asset improves the argument instead of decorating it; in normal service-native `presentation_builder` output, keep direct raster use to at most 2 images per slide and translate repeated kit elements into native PPT components.
- Keep speaker notes or comments out unless requested.

### Editable PPT Prototype Gate

For client-ready, proposal, investor, sales, executive, or highly visual decks, build a small editable PPT prototype before full production unless the user explicitly delegates or cancels the checkpoint.

Prototype requirements:

- use the same 3-5 representative pages selected for visual exploration
- build real editable PPT slides, not only imagegen thumbnails or static screenshots
- when a visual scheme is selected, build the prototype with `route_mode="custom_compose"`, `delivery_mode="prototype"`, the representative-page `expected_slide_count`, `strict_qa=true`, `render_qa=true`, and `include_compose_manifest=true`; write it under a `prototype/` or `prototypes/` directory
- keep real text editable and use the planned font system
- use the selected page-bound hero assets and native/raster split
- render a prototype contact sheet and inspect at least the weakest full-size slide
- present the rendered contact sheet to the user, ask in their language to continue, revise, increase visual impact, reduce image dependence, or regenerate weak assets, and then stop the turn
- never call the final builder in the same turn as a `delivery_mode="prototype"` result; wait for explicit user approval, revision instructions, or recorded delegated approval

Chinese checkpoint example:

```text
我先停在真实 PPT 小样确认门。这 3-5 页已经是可编辑 PPT 结构，不是视觉参考图。

1. 继续全量制作
2. 更接近视觉图，增强主视觉和电影感
3. 减少图片依赖，提高可编辑性
4. 重做这几页小样
```

If the prototype only matches the palette but loses visual anchors, focal scale, typography rhythm, or atmosphere, revise the visual-translation contract and assets before full deck production.

## Stage 17: Visual, Motion, Asset, Copy, Information, And Commercial DNA QA Redesign Loop

The deck is not done until rendered previews pass these checks:

- creative brief test: final deck serves the defined audience, belief shift, setting, and decision
- storyboard test: final deck follows the approved or delegated narrative sequence
- DNA fidelity test: final slides still express the selected design DNA beyond palette
- commercial fit test: the visual language supports the deck's business goal and audience belief shift
- thumbnail test: visual system is coherent across the deck
- content test: every slide has a clear claim and proof object
- editability test: important text, charts, and diagrams are not flattened images
- overflow test: no clipped text, overlapping labels, or unreadable small type
- typography system test: fonts, weights, sizes, line spacing, and numeric treatment follow the written system
- font availability test: selected fonts are verified, provided, or have clear fallback and delivery notes
- master layout test: repeated layouts follow the layout system while allowing intentional variation
- information design test: charts, tables, screenshots, diagrams, and evidence pages clarify decisions rather than decorate complexity
- evidence honesty test: source notes, caveats, assumptions, and placeholders are visible where needed
- scheme fidelity test: final slides still look like the selected direction in composition, imagery, texture, contrast, and layout rhythm
- visual-translation contract test: key slides preserve the planned archetype, dominant visual anchor, focal ratio, text zone, and native/raster split
- prototype fidelity test: final full-deck slides do not drift below the approved prototype quality
- asset integration test: generated assets appear intentional, are not merely decorative wallpaper, and do not block editable content
- asset suite completeness test: body slides have the designed icons, connector treatments, module surfaces, data badges, or support imagery they require
- asset utilization test: every approved generated asset family has actual direct use, native translation, or an explicit omission rationale; zero-use component sheets are failures
- asset fitness test: every direct raster component was classified as production-ready before use
- asset density test: generated kit elements are not overused as decoration and stay within the planned direct-raster budget unless justified
- quota-decoration test: no arrow, icon, badge, connector, or small image is present only because an asset family needed usage
- component integrity test: raster frames, panels, badges, and connectors are not clipped, stretched, distorted, or broken by cropping
- text safe-area test: editable text that appears inside a component stays inside a declared safe text rectangle in full-size render
- full-bleed edge test: every slide with a generated background or texture plate has full-size rendered edges checked for unintended gray, white, black, or transparent bars inside the slide
- copy sharpness test: headlines are claim-led, concise, and buyer-facing rather than raw source paragraphs
- default-font failure test: the deck does not accidentally rely on Aptos, Calibri, Arial, or system fallback unless explicitly selected
- color-only failure test: if the deck only shares palette with the chosen thumbnail, revise before delivery
- art-direction test: each non-appendix slide has a clear focal point and follows its intended role
- motion-direction test: each non-appendix slide has a reveal plan or an explicit static-by-design reason
- step-build test: step-build variants preserve geometry and create a clear click-by-click progression
- transition test: section changes and major story turns have intentional transitions instead of accidental cuts
- component-library test: repeated components feel related but not monotonous
- anti-template test: the deck does not look like a default template with new colors
- copied-template test: the deck abstracts traits and does not imitate a specific marketplace/template/brand
- source test: numbers, claims, names, and dates match the source
- full-size spot-check test: inspect the weakest or densest rendered slides at full size, not only in a contact sheet
- technical-vs-commercial test: slide count, nonblank render, editable objects, and unzip success are necessary but never sufficient
- client-specificity test: the deck looks tailored to the named client, industry, and decision context
- buyer-memory test: at least 2-3 slides are memorable commercial anchor pages rather than only explanatory pages
- handoff readiness test: final package has edit guide, asset notes, font/fallback notes, preview evidence, and missing-input caveats

Use a 1-5 score for each slide:

- design DNA fidelity
- commercial fit
- composition
- focal point
- hierarchy
- visual rhythm
- motion/reveal clarity
- presentation rhythm
- scheme fidelity
- typography system fidelity
- font availability safety
- master layout fidelity
- information design integrity
- evidence honesty
- asset fit quality
- component integrity
- text container integrity
- asset density control
- editability
- source fidelity

Rules:

- Redesign any slide with composition, focal point, hierarchy, motion/reveal clarity, presentation rhythm, or scheme fidelity below 4.
- Redesign any slide with design DNA fidelity or commercial fit below 4.
- Redesign any key slide that fails the visual-translation contract or drifts materially from the approved prototype.
- Redesign any slide with typography system fidelity or font availability safety below 4.
- Redesign any information-heavy slide with information design integrity or evidence honesty below 4.
- Redesign any slide with asset suite completeness or copy sharpness below 4.
- Redesign when approved pictogram, module surface, connector, data badge, diagram accent, case strip, or signature-mark families have zero usage after build.
- Redesign when the only used generated assets are backgrounds, textures, or generic scene images but the deck generated component families for body-slide quality.
- Redesign when direct raster component use exceeds the density budget without a recorded reason and full-size QA approval.
- Redesign when assets are visibly quota-driven rather than story-driven or composition-driven.
- Redesign any slide where a raster component is clipped, stretched, distorted, or used as a text container without a verified safe text area.
- Redesign or rebuild any full-slide background/texture whose rendered slide preview shows unintended edge bars inside the slide. Do not confuse PowerPoint editor canvas or page shadow outside the slide with slide pixels.
- Redesign at least the weakest 2 slides when the average visual score is below 4.2.
- Redesign at least the weakest presentation beat when the deck reads as static or monotonous.
- Do not fix weak design by flattening the slide into a screenshot.
- Prefer changing composition, reveal order, step-build variants, asset crop, type scale, and component choice before adding more decoration.

## Stage 18: Commercial Readiness And Delivery Signoff Gate

Read `commercial-readiness.md` before calling a deck commercial-grade, client-ready, proposal-ready, investor-ready, or suitable for standalone customer delivery.

Score the rendered deck from 1-10 on:

- creative brief fit
- storyboard strength
- visual completion
- client specificity
- business persuasion
- self-readability
- evidence and proof
- information design
- implementation credibility
- editability boundary
- handoff readiness

Delivery rules:

- 8.2-10: client-ready proposal
- 6.8-8.1: speaker-assisted proposal; revise or label caveats
- 5.5-6.7: internal draft; do not call commercial-grade
- below 5.5: redesign required

If the score is below the requested tier, redesign the weakest dimensions before final delivery. If missing inputs prevent a higher score, name the missing inputs and avoid inventing proof.

Delivery signoff package:

- final editable PPTX path
- final PDF path
- internal `*.presentation.compose.json` source ledger path
- rendered contact sheet path
- full-size spot-check slide paths
- edit guide
- font/fallback notes
- asset suite usage notes
- missing-input and assumption list
- commercial readiness note
- signoff status: approved, delegated, caveated, or draft
