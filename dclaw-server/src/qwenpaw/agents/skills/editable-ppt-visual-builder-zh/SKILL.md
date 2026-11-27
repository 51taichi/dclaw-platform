---
name: editable-ppt-visual-builder
description: "将文档、草稿、现有 PPT/PPTX 或提案素材升级为设计公司级可编辑 PPT：包含创意简报、文案优化、分镜、商业亮点、视觉 DNA、GPT Image2/imagegen 视觉方案、字体/信息设计系统、素材套件、母版组件、动效节奏、商业级 QA、可编辑 PPTX/PDF 交付和内部 compose 来源账本。"
metadata:
  builtin_skill_version: "2.1"
  qwenpaw:
    emoji: "📊"
    requires: {}
config:
  is_default: true
  market_category: "office"
  icon: "presentation"
  display_name: "可编辑 PPT 视觉设计师"
  author: "DClaw"
  short_description: "按设计公司标准完成 PPT 策略、分镜、视觉 DNA、小样、素材、QA 和 PPTX/PDF 交付"
tags:
  - PPT
  - Office
  - 视觉设计
  - 提案
  - GPT Image2
  - 可编辑文档
---

# Editable PPT Visual Builder

## Purpose

Use this skill to create art-directed editable PowerPoint decks from source text while using imagegen for both visual direction previews and final-deck visual assets. Preserve this boundary:

- imagegen creates moodboards, visual direction contact sheets, hero/background assets, textures, image metaphors, supporting graphics, icon/pictogram families, module surfaces, connector treatments, data badges, and style references.
- the skill first defines an agency-grade creative brief and success bar, optimizes source copy into presentation-ready claims and highlights, creates a storyboard, selects market-informed design DNA, stops for user visual-scheme selection, then translates the chosen direction into slide-by-slide art direction, motion/reveal direction, typography/font system, information design system, master layout/component library, and visual asset suite.
- QwenPaw `presentation_builder` creates the final editable PPTX/PDF package. It has three real authoring routes: `template_following` for clone/edit of a supplied PPTX, `custom_compose` for exact layer-based translation of an explicitly selected visual direction, and `codex_grid` only when no template or explicit visual direction governs the composition. It verifies required generated images and emits an internal `*.presentation.compose.json` source ledger for reproducible rebuilds.

Never treat an imagegen thumbnail as the final slide structure or as something that can be reliably decomposed into editable PowerPoint components. The chosen thumbnail must be translated into a visual-translation contract, design system, page-level art direction, motion/reveal direction, a component grammar, and, when the style depends on imagery, texture, iconography, or material finish, a reusable visual asset suite before final PPTX generation.

Commercial-grade means client-ready, not merely editable, valid, or visually improved. Treat every exported PPTX/PDF package as a candidate until it passes both technical QA and commercial readiness QA. A deck that can only be used with presenter explanation is not the same deliverable as a standalone client proposal.

## Required Companion Skills

Load or follow these skills when execution reaches their stages:

- `imagegen`: use for visual scheme thumbnails, moodboards, and generated visual asset suites.
- In QwenPaw, `imagegen` is a unified image generation tool. Use `imagegen` for visual scheme thumbnails, moodboards, and final-deck visual asset suites. `generate_image_gpt` and `edit_image_gpt` are compatibility aliases only.
- The visual-scheme stage must call `imagegen` before asking the user to choose. Do not present a text-only visual scheme selection.
- `presentation_builder`: use for the prototype and final editable PPTX/PDF build, exact custom composition or 80-layout selection, internal compose source ledger, semantic content checks, and package-level media QA. Pass `route_mode="custom_compose"` plus `compose_spec` after the user selects a visual direction; use fixed `slides` plus `asset_usage_matrix` only for the `codex_grid` route.

When the user only asks to plan or evaluate the workflow, do not generate assets. When the user asks to produce a deck, continue through the full workflow.

## User-Facing Language

Use the user's language for every user-facing question, checkpoint, option label, recommendation, and scheme name. For Chinese users, ask in Chinese and present visual scheme options in Chinese.

Keep English only as an optional internal slug or secondary note when it helps implementation, for example `战略 AI 指挥中心（AI Command Center）`. Do not present English-only options such as `Strategic AI Command Center` to a Chinese user.

## Workflow

1. Ingest the source
   - Accept documents, pasted copy, notes, URLs, existing PPT/PPTX decks, template decks, reference decks, or rough prompts.
   - Classify each deck as a source deck, template deck, reference deck, or mixed deck.
   - Extract audience, decision goal, tone, required facts, constraints, and missing inputs.
   - Classify the expected delivery tier: internal draft, speaker-assisted proposal, external client-ready proposal, or reusable template system. Default to external client-ready when the user says commercial-grade, customer/client version, pitch, proposal, investor, or sales deck.
   - If the source contains claims, dates, metrics, or regulated content, preserve exact wording and flag unsupported claims.
   - Record missing client-specific inputs that may block commercial readiness, such as real brand assets, customer screenshots, real metrics, product UI, implementation owner, timeline, pricing, or proof points.
   - Audit brand assets, source evidence, required screenshots, data, fonts, legal notes, existing templates, and delivery environment.

2. Define the agency creative brief and success bar
   - Read `references/premium-agency-standards.md` before moving from source understanding into copy, storyboard, or design.
   - Define audience, decision-maker, desired belief shift, business stakes, presentation setting, presenter constraints, brand constraints, mandatory content, forbidden claims, proof requirements, success criteria, approval owner, and review gates.
   - Create a brand and asset audit. Mark each missing input as request, placeholder, generated non-evidence asset, omission, or assumption.
   - For client-ready, investor, executive, sales, or high-stakes work, record whether the user must approve or has delegated each gate: creative brief, storyboard, visual direction, design system, production QA, and delivery signoff.

3. Optimize copy and extract commercial highlights
   - Read `references/copy-optimization.md` before writing the outline or slide content.
   - Preserve source facts, names, metrics, dates, compliance boundaries, and quoted language where required.
   - Convert raw source paragraphs into presentation-ready claims, buyer-facing outcomes, concise proof labels, memorable phrasing, and slide-level takeaway lines.
   - Extract the strongest commercial highlights: pain, stakes, promise, differentiation, proof, implementation path, ROI/personnel impact, risk control, and final ask.
   - Identify weak or missing proof points rather than inventing them. Mark assumptions and input gaps.
   - Produce a copy strategy that states the core message, audience belief shift, headline style, proof style, vocabulary, forbidden claims, and the slides that should become commercial anchors.

4. Build the story spine
   - Create a slide inventory, not just a title list.
   - For each slide, define the optimized claim, proof object, content blocks, data needs, likely slide type, and commercial highlight.
   - Prefer a concise narrative arc: context, tension, evidence, solution, roadmap, ask.

5. Create storyboard and slide architecture
   - Convert the story spine into a storyboard, not only a title list.
   - For each slide, define the audience question, narrative beat, claim, proof object, visual role, emotional intensity, expected action, and commercial role.
   - For client-ready, investor, executive, sales, or high-stakes work, stop for storyboard approval unless the user explicitly delegates this gate.
   - Do not generate final PPTX from an incoherent, repetitive, proof-light, or decisionless storyboard.

6. Select key pages for visual exploration
   - Choose 4-5 representative pages that stress-test the visual system.
   - Include a mix such as cover, executive thesis, data/chart page, process/architecture page, and summary/roadmap page.
   - Avoid choosing only decorative pages; visual schemes must prove they can handle real content.

7. Select market-informed design DNA
   - Before writing imagegen prompts, generate 3-5 candidate design DNA directions matched to the deck objective, audience, industry, content type, and commercial moment.
   - Score each DNA direction from 1-5 for commercial fit, visual distinction, industry credibility, editability, deck-wide scalability, imagegen promptability, and risk.
   - Keep only the strongest 2-3 DNA directions for imagegen exploration. Reject directions that look trendy but do not support the user's business goal or editable PPT implementation.
   - When the default output is 3 visual schemes, select 3 independently scored DNA finalists. Do not manufacture the third option by blending the first two into an unscored "hybrid/fusion" scheme. A hybrid is valid only when it was separately defined and scored at this stage or the user explicitly requested a fusion direction.
   - Treat visual variety as a product requirement, not a nice-to-have. Unless the user explicitly requests a conservative-only deck, include at least one bolder/high-impact direction and make the selected candidates differ in visual anchor, composition rhythm, material treatment, and palette.
   - Do not let every DNA become a blue/purple enterprise dashboard, card grid, or SaaS command-center variant. If two candidates can be described by the same layout grammar with only color changes, they are not separate visual schemes.
   - For each selected DNA, state why it fits, where it may fail, which slide archetypes it powers, and which assets it requires.
   - Give every DNA direction a localized user-facing display name. For Chinese users, use Chinese names in the options and keep any English name secondary.
   - Do not copy or imitate a specific paid template, brand, marketplace listing, or living designer's protected work. Abstract reusable design traits only.

8. Generate visual schemes
   - Default to 3 schemes. Use 5 only when the user explicitly wants broader exploration.
   - Generate one standalone thumbnail/contact-sheet image per selected design DNA scheme. Each generated file must contain exactly one scheme candidate, not A/B/C rows or multiple schemes in a single image.
   - In QwenPaw, call `imagegen` once per visual scheme candidate. Do not ask imagegen to render all 2-3 candidate schemes inside one combined comparison sheet, and do not compose a post-generation montage for the chat. Combined images bias the model toward one shared grid, shared slide-template grammar, and conservative visual convergence.
   - Every visual-scheme `imagegen` call must pass `presentation_context` with `stage="visual_scheme"`, `deck_topic`, `audience`, `direction_name`, `visual_temperature`, `dominant_visual_anchor`, `commercial_rationale`, `represented_pages`, and `forbidden_patterns`. This activates the runtime Codex-style `productivity-visual` prompt compiler and creates a sibling `*.imagegen.json` prompt/provenance record. Do not rely on free-form prompt wording alone.
   - Each contact sheet should show the same selected 4-5 pages so the user can compare styles fairly.
   - Save or embed the generated image outputs and record their paths. Present them in the conversation as repeated blocks: `方案一：方案名` followed by that scheme's single image; `方案二：方案名` followed by that scheme's single image; `方案三：方案名` followed by that scheme's single image. A text-only list of scheme names is not a visual scheme.
   - Keep text in thumbnails minimal and large. Do not rely on imagegen for precise body copy, tables, charts, or small labels.
   - Prompt imagegen for visual direction, not final slide screenshots. Each scheme must include a dominant visual anchor such as a cinematic metaphor, editorial crop, spatial system map, material surface, type-led composition, or product/platform scene.
   - Do not generate visual scheme thumbnails as finished text-heavy slide pages. A scheme image may show only large placeholder headings or simple labels; it must not contain body copy, tables, dense UI labels, or miniature full-slide text systems that cannot become editable PPT layers.
   - Include a negative prompt against generic blue-purple SaaS dashboards, dense card grids, fake UI labels, small unreadable body text, stock PPT templates, and repeated rounded rectangles unless that exact grammar is the selected DNA.
   - If the first generated batch is visually conservative or the schemes differ mainly by palette, regenerate before asking the user to choose. The checkpoint is invalid when the user cannot see genuinely different visual strategies.
   - Ask the user to choose a scheme before design-system extraction, asset-suite generation, or final PPTX generation unless they explicitly delegated the choice before this stage.

9. Stop for visual scheme selection
   - This is a hard checkpoint. Present the generated visual scheme thumbnails with a concise comparison and wait for the user to choose, request revisions, or delegate selection.
   - The checkpoint must show separate images, one per scheme. Do not show only one combined comparison image as the selectable UI.
   - Ask the checkpoint question in the user's language. For Chinese users, all options, recommendation labels, revision choices, and selection prompts must be Chinese.
   - The checkpoint is valid only when the user can see generated image outputs for the schemes. Do not ask the user to choose from text-only DNA names.
   - If imagegen fails or is unavailable, stop and report that visual scheme generation failed. Do not proceed to final PPTX production as if a visual scheme had been selected.
   - Do not proceed to final asset generation, `presentation_builder` work, or PPTX creation while the scheme is unselected.
   - Always offer a "换一批/重新生成一批" option when showing visual schemes. If the user dislikes all schemes, regenerate a new batch instead of forcing a selection.
   - If the user asks for changes, revise or regenerate the scheme candidates before continuing. Record whether the new batch should keep the same strategy, become bolder, become more conservative, change industry tone, or restart design DNA selection.
   - If the user delegates selection, record the selected scheme and the reason. Treat that as an explicit selection, not an implicit default.

10. Convert the chosen scheme into a design system
   - Read `references/typography-system.md` before finalizing fonts or type scale.
   - Translate the selected visual direction into structured design rules: palette, typography/font system, type scale, grid, spacing, page rhythms, chart grammar, card grammar, icon style, image treatment, and section divider rules.
   - Persist the selected scheme as an explicit `theme` object for `presentation_builder`: include at least `canvas`, `ink`, `body`, `muted`, `panel`, `panel_alt`, `rule`, `accent`, `accent_soft`, and `font_family`. These values must come from the user-selected visual scheme or regenerated scheme batch, not from the default blue report theme.
   - Create a visual-translation contract from the selected contact sheet before building slides. Record the scheme's page archetypes, dominant visual anchors, focal ratios, text-safe zones, negative-space rules, contrast rules, typography rhythm, material/lighting treatment, and non-negotiable traits that must survive editable PPT production.
   - For each represented thumbnail page, map what becomes a 16:9 page-bound hero/background asset, what becomes a separated visual metaphor, what becomes native PPT typography or shape grammar, and what should be omitted rather than forced into the deck.
   - If the selected scheme relies on cinematic hero objects, image metaphors, deep atmosphere, or strong editorial crops, plan page-specific hero assets for the key slides instead of relying only on reusable background tiles or small component sheets.
   - Define font availability, licensing/embedding caveats, Chinese/English/number font pairing, fallback stack, font roles, size scale, weight rules, line height, and maximum font count.
   - Define master layout rules for cover, section, thesis, summary, evidence, process, architecture, case proof, roadmap, offer/ask, and appendix/table pages.
   - Define information design rules for charts, tables, diagrams, screenshots, evidence notes, annotations, and density limits.
   - Record what came from the thumbnail versus what is inferred for editable implementation.
   - Identify the scheme's non-color visual drivers: image metaphors, textures, lighting, backgrounds, framing, icon treatment, decorative marks, photo crops, and page archetypes.
   - Record the selected design DNA and how it should survive editable PPT implementation.
   - Do not copy rasterized text or chart details from the thumbnail.

11. Write slide-by-slide art direction
   - For every non-appendix slide, define the page role, emotional intensity, focal point, composition, hierarchy, visual anchor, selected-scheme archetype, text zone, negative space, and forbidden generic patterns.
   - Specify which slides should feel like impact pages, explanation pages, evidence pages, transitions, or closing/ask pages.
   - Convert "make it beautiful" into concrete layout instructions: asymmetry, scale contrast, full-bleed imagery, editorial crop, dashboard density, diagram topology, or cinematic opening/closing.
   - Bind each key slide to the visual-translation contract. A cover, thesis, product, mechanism, or closing page should inherit the selected scheme's visual anchor and composition, not merely its palette.

12. Write slide-by-slide motion direction
   - For every non-appendix slide, define the reveal intent, presenter beat, object reveal order, transition style, pacing, and fallback if native PowerPoint animation cannot be implemented reliably.
   - Prefer commercial presentation rhythm over decorative motion: reveal tension, proof, contrast, sequence, decision, and payoff.
   - When native animation support is unavailable or risky, create editable step-build slide variants instead of delivering a static page. For example, use `5A`, `5B`, `5C` to reveal a framework, metric, or diagram over multiple clicks.
   - Keep each step-build variant editable. Do not flatten the slide into screenshots to simulate animation.

13. Create the master layout and design component library
   - Define reusable component families for the chosen deck instead of drawing ad hoc rectangles.
   - Include only components the deck actually needs, such as hero cover, thesis page, pain wall, system module, metric dashboard, process map, case proof strip, comparison wall, offer cards, and closing ask.
   - For each master layout and component, define native PPT parts, allowed raster layers, spacing rhythm, text hierarchy, interaction with imagery, editable object rules, and failure modes.

14. Generate the visual asset suite
   - Read `references/asset-suite.md` before generating final-deck assets.
   - Before building the PPTX, decide whether the chosen scheme needs generated assets to survive implementation.
   - Reuse the exact selected scheme identity in every downstream asset call. Every asset `imagegen` call must pass `presentation_context.stage="visual_asset"` plus the same `direction_name`, `deck_topic`, `audience`, and commercial rationale recorded at selection, then add `asset_type`, `composition`, `reserved_text_area`, `output_role`, and `forbidden_patterns`. Do not silently switch from the selected DNA to a generic icon, gradient, or dashboard style.
   - Treat each sibling `*.imagegen.json` file as the generation ledger for prompt fidelity. Before prototype authoring, confirm that the scheme record and every required background/hero/component asset share the selected `direction_name` and appropriate output role.
   - Decide native-only versus hybrid implementation before authoring. Native-only is not a virtue when it collapses the selected scheme into generic cards, tables, or color-only fidelity. Prefer hybrid layers when commercial polish depends on imagery, texture, lighting, dimensionality, or complex atmosphere.
   - For a typical 10-15 slide client-ready deck, default to 6-10 source asset sheets rather than dozens of unrelated individual images. Extract or crop roughly 10-25 reusable elements from those sheets as needed.
   - Treat asset sheets as mini design-system boards: icon/pictogram sheet, module surface sheet, connector/node sheet, data badge sheet, texture/background sheet, section/closing background sheet, and case/image strip sheet when needed.
   - Generate any asset intended to cover the full slide as an individual 16:9 full-bleed plate, not as a small tile inside a multi-item sheet. Texture or background tiles extracted from a grid may be used as overlays only when their aspect ratio, crop, and placement are proven to cover the slide without side bars or margins.
   - Use the art direction and component library to produce separate assets for the selected scheme: cover hero/background, section or closing backgrounds, body-slide texture plates, abstract product/platform scenes, photographic metaphors, texture overlays, brush strokes, signature marks, icon/pictogram families, module surfaces, connector treatments, data badges, diagram accents, and case-study image strips.
   - Background, hero, texture, and section-divider assets must be text-free except for intentionally abstract brand marks or a single large decorative wordmark. Reject assets that contain body copy, dense diagrams, tables, small labels, or finished slide text; those must be rebuilt as editable PPT text/shapes instead of used as backgrounds.
   - Generate page-bound hero assets for the 3-5 most important or most visually demanding slides when the selected scheme depends on strong full-page metaphors, such as a portal, cliff, platform cube, operating loop, mountain, command center, product scene, or other dominant visual anchor.
   - Treat reusable component sheets as secondary support. They should reinforce the page archetype, not become a requirement to paste icons, arrows, badges, or small pictures onto slides that are stronger without them.
   - Treat a background-only asset set as incomplete for client-ready decks unless the chosen scheme is deliberately native-only and still passes commercial QA.
   - Replace generic low-quality line controls, default arrows, and ad hoc boxes with designed connector treatments, diagram accents, component frames, and icon language.
   - Do not generate important text, charts, tables, or small labels inside these assets.
   - Save every project-bound asset in the deck workspace and record its intended slide usage, crop behavior, and editability boundary.
   - Create an asset-to-slide usage matrix before PPTX generation. For each asset family, record the exact target slides, whether it will be used as raster image, native redraw reference, or both, and the minimum expected usage count.
   - Run an asset fitness gate before PPTX generation. Classify every extracted or cropped element as `production-ready`, `reference-only`, `accent-only`, or `reject`. Only `production-ready` assets may become direct raster components; weak or fixed-frame sheets should become native redraw references or small accents.
   - Classify any text-heavy generated page image as `reference-only` or `reject` for direct background use. It may guide composition, but it must not be passed to `required_image_assets` as a `background`, `hero`, or `wide` placement.
   - Record a direct-raster density budget. For a 10-15 slide client-ready deck, overusing direct raster components is a failure just like not using them. In normal cases keep pictograms to about 6-12 total direct uses, module surfaces 3-8, connector motifs 2-6, data badges 2-5, and case strips 2-4 unless the visual QA records a clear reason.
   - For a 10-15 slide client-ready hybrid deck, at least 4 non-background asset families should visibly influence the deck unless intentionally omitted: pictograms, module surfaces, connector/diagram accents, data badges, case/product image strips, or signature marks. Backgrounds and textures alone do not satisfy this requirement.
   - Show a lightweight asset-suite preview/checkpoint before PPTX generation when the deck is client-ready or the chosen scheme depends on generated visual language. For Chinese users, offer Chinese options such as "继续制作", "换一批组件", "减少图片感、提高可编辑性", or "增强视觉冲击".

15. Design the information and evidence system
   - Read `references/information-design.md` before building data, table, process, architecture, comparison, roadmap, operating model, or proof-heavy slides.
   - For every information-heavy slide, define the decision question, evidence source, chart/diagram choice, annotation strategy, source/caveat note, density limit, and reveal behavior.
   - Do not beautify fake or unsupported evidence. Use placeholders or caveats when real data, screenshots, or proof are missing.

16. Build the editable PPTX/PDF package
   - Use QwenPaw `presentation_builder` for PPTX/PDF export. Do not fall back to `python-pptx`, one-off shell scripts, or text-only decks when generated images are part of the selected direction.
   - Choose the authoring route before building: supplied PPTX template plus frame map -> `template_following`; explicit user-selected visual scheme or visual-translation contract -> `custom_compose`; no governing template and no explicit visual direction -> `codex_grid`. Never send an explicitly selected scheme through `codex_grid` merely because its colors can be copied into `theme`.
   - For `custom_compose`, pass a `compose_spec` with `schema_version`, 13.333 x 7.5 `slide_size` using `width`/`height`, explicit `theme`, a non-empty inline `visual_translation_contract`, and per-slide `archetype`, named `layers`, and `expected_content`. The runtime also accepts `w`/`h` plus common layer aliases, but prefer the canonical field names. Supported editable layer types are `text`, `shape`, `line`, and `image`; every layer requires exact `x/y/w/h` bounds. Use `expected_content.required_text`, `required_layer_names`, `layer_type_counts`, and `semantic_group_counts` to prevent silent content loss such as three comparison paths becoming two.
   - Pass `expected_slide_count` on every prototype and final call. For prototypes it must equal the selected representative-page inventory; for final delivery it must equal the approved storyboard inventory. Never silently merge, omit, or rename away approved pages to make the payload shorter.
   - A `custom_compose` prototype must be written under `prototype/` or `prototypes/`, use `delivery_mode="prototype"`, `render_qa=true`, `strict_qa=true`, `include_compose_manifest=true`, and the prototype `expected_slide_count`. `delivery_mode="prototype"` is a real pause gate: after the tool returns, show the rendered contact sheet and stop the turn for user approval, revision, or delegated approval. Do not generate the final deck in the same turn. The full deck must reuse the approved compose grammar rather than falling back to fixed layouts after prototype approval.
   - If `custom_compose` returns a schema, bounds, font, semantic, asset, render, or visual-translation error, correct that payload and retry `custom_compose`. Never switch to `codex_grid` as an error recovery path after the user selected a visual direction. The runtime reads sibling `*.imagegen.json` records and blocks this downgrade when production assets declare a selected `direction_name`.
   - Before calling `presentation_builder`, prepare the route-appropriate structured input plus `theme`, delivery mode, `strict_qa`, `render_qa`, PDF/manifest settings, and asset declarations. The `theme` object is mandatory when a visual scheme was selected; derive it from that scheme's palette, typography, material/lighting treatment, and page rhythm so a choice like "C. 活力创新型" cannot collapse back to a generic blue-white deck. Every generated image that must survive into the PPTX must be mapped either through a custom image layer, the grid asset matrix, or a template replacement target.
   - In `custom_compose`, put direct raster image placements inside image layers and list those files in `required_image_assets`; do not also pass `asset_usage_matrix`. If an approved moodboard/component sheet is reference-only and the page is deliberately rebuilt with native shapes, set `requires_visual_assets=false` and record a concrete `native_translation_rationale` in `compose_spec`. This exception is not permission to ignore the selected visual anchors, focal ratio, material treatment, or page rhythm.
   - Treat `asset_usage_matrix` as direct-raster placement only. Each mapped entry should include `asset_path`, `slide_index`, a direct role such as `hero`, `background`, `wide`, `thumbnail`, `figure`, or `diagram`, and a short `purpose` explaining why that image belongs on that slide. Do not map component sheets, icon sheets, module sheets, connector sheets, moodboards, or visual-language reference boards into slides as direct images.
   - On the `codex_grid` route, each slide must use a deliberate `layout`: `image_hero`, `section`, `agenda`, `cards`, `comparison`, `process`, `roadmap`, `metrics`, `table`, `architecture`, `quote`, `two_column`, or `content`. For cards/comparisons use `items` or `columns`; for process/roadmap use `steps`; for KPI pages use `metrics`; for evidence matrices use `table.headers/table.rows`.
   - If a reference/template PPTX is part of the request, inspect source slides and prepare `template_frame_map`; each output slide must point to a `sourceSlide`. Use `editTargets` with `rewrite` for inherited text and `replace-image` for inherited picture frames. Pass both `template_path` and `template_frame_map`, and confirm the response reports `template_mode=clone_edit`.
   - When generated visual directions should replace template pictures, map those paths through `editTargets[].asset_path` and include them in `required_image_assets`; do not only list their file paths in the reply.
   - For final/client-ready delivery, set `delivery_mode="final"`, the approved storyboard `expected_slide_count`, `export_pdf=true`, and `include_compose_manifest=true`. Set `requires_visual_assets=true` when direct raster production assets are used; only use false with an explicit native-translation rationale in `custom_compose`. PPTX/PDF 是面向用户的任务主制品；`*.presentation.compose.json` 是内部来源账本，用于复现布局、素材映射和 QA 证据，不作为用户主交付物展示。 Render QA previews are internal QA artifacts referenced in the text by `contact_sheet=...`, `render_qa=ok`, and `rendered_slide_count`, not task deliverables.
   - After `presentation_builder` returns, confirm the response includes `export_pdf=true`, `compose_manifest=...`, `render_qa=ok`, and `rendered_slide_count`. If it reports missing mapped assets, zero `media_count`, zero `pic_count`, low `layout_variety`, nonzero `weak_slide_count`, nonzero `overlap_count`, nonzero `qa_warnings`, missing PDF export, missing compose manifest, missing `render_qa=ok`, or mismatched `rendered_slide_count` after image assets were required, revise the slide specs or asset usage matrix and rebuild before delivering.
   - Build every slide from structured content, visual-translation contract, art direction, motion direction, component library rules, and asset usage notes.
   - For client-ready or highly visual decks, build and render a 3-5 slide editable PPT prototype using the same representative pages as visual exploration before producing the full deck, unless the user explicitly delegates or cancels this checkpoint. Ask the user in their language to continue, revise, increase visual impact, reduce image dependence, or regenerate weak assets.
   - Before authoring each slide, bind slide components to the asset-to-slide usage matrix. If a slide's planned icon, module surface, connector treatment, data badge, diagram accent, or case image is omitted, record the reason and compensate with a native implementation that visibly follows the same asset family.
   - Do not add an asset solely to satisfy an asset family count. Every icon, connector, image, badge, or arrow must be earned by the slide's narrative role, composition, or information design. If a strong hero page works better with only typography and a background, leave it clean and record the omission.
   - Treat generated component sheets as visual ingredients, not automatic containers. Module surfaces, cards, input boxes, badges, and connectors should be rebuilt as native PPT shapes unless the raster element is production-ready at the target aspect ratio and has a verified safe text area.
   - Do not stretch, crop, or use `fit: "cover"` on raster panels, badges, connector controls, or input-box-like components when the border/frame must remain intact. Use original aspect ratio, a prepared 9-slice-safe asset, or redraw the component natively.
   - Real slide text must sit in native text boxes. If text is visually inside a generated component, define the component's safe text rectangle and padding before rendering, then verify the text remains inside that rectangle in the preview.
   - Use native editable objects for titles, bullets, callouts, tables, charts, process diagrams, architecture diagrams, timelines, cards, and connectors.
   - Apply the chosen typography/font system consistently. Do not rely on unspecified PowerPoint defaults.
   - Apply the master layout system consistently. Do not create each page as a one-off composition unless art direction requires it.
   - Apply the information design system to charts, tables, diagrams, screenshots, evidence notes, and annotations.
   - Use generated or provided raster images as separate layers for photography, illustration, texture, mood imagery, background plates, and intentionally non-editable visual assets.
   - Implement native PowerPoint animations only when the current PPTX builder path clearly supports them; otherwise use editable step-build slide variants to create click-by-click reveal rhythm.
   - Keep visual fidelity to the chosen scheme in composition, page rhythm, imagery, material treatment, and contrast, not just palette.
   - Use the optimized copy strategy and slide-level highlights as the source for headlines and callouts; do not dump unedited source paragraphs into slides.
   - Use the visual asset suite and component library before drawing ordinary lines, rectangles, arrows, or generic controls.
   - Do not treat generated component sheets as mood references only. If a sheet is approved for production, its elements must be used directly or explicitly translated into native PPT components.

17. Render, critique, and redesign
   - Render previews/contact sheets before exporting final PPTX.
   - Inspect both the contact sheet and full-size renders of the most complex or weakest slides. Do not rely on montage-only review; small thumbnails hide overlaps, weak hierarchy, and unreadable details.
   - For every slide with a generated background or texture plate, inspect full-size renders for edge coverage: no unintended gray, white, black, or transparent bars at the left, right, top, or bottom. If using a viewer screenshot, distinguish PowerPoint canvas/shadow outside the slide from pixels inside the slide.
   - Score each slide for composition, visual focal point, design rhythm, motion/reveal clarity, information hierarchy, source fidelity, editability, and selected-scheme fidelity.
   - Compare the rendered PPT prototype and final slides against the selected visual scheme contact sheet. Treat drift in page archetype, focal scale, dominant visual anchor, typography rhythm, text zone, or atmosphere as a redesign trigger.
   - Treat color-only similarity, generic card grids, weak focal points, and template-like sameness as failures.
   - Treat "technical pass" as insufficient: slide count, unzip success, nonblank renders, and editable objects do not prove commercial quality.
   - Treat a production deck with no reveal strategy, no transition plan, or no step-build fallback as incomplete.
   - Treat body slides with cheap default connectors, weak icon rows, raw source copy, or background-only visual fidelity as failures.
   - Treat approved asset families with zero or token usage as failures unless the asset usage matrix records a deliberate omission. A deck that generated icons, module surfaces, connectors, and badges but uses only backgrounds has failed the asset-suite stage.
   - Treat quota-driven decoration as a failure: random arrows, icons, badges, or small pictures placed only to show asset usage must be removed and the asset usage matrix updated.
   - Treat asset overuse as a failure when direct raster components are sprayed across slides, when every card depends on cropped component art, or when the deck exceeds the density budget without a written reason and full-size visual QA.
   - Treat clipped, stretched, or aspect-ratio-distorted component assets as failures. Any raster component used as a text container without a declared and verified safe text area requires redesign or native redraw.
   - Treat missing font strategy, generic default fonts, inconsistent CJK/Latin/number fallback, unreadable body sizes, or unverified premium fonts as failures.
   - Treat missing creative brief, unapproved/delegated storyboard, weak information design, brand inconsistency, master-layout drift, or missing delivery notes as failures.
   - Redesign the weakest slides and weakest presentation beats before final delivery rather than explaining away mediocre output.

18. Commercial readiness and delivery signoff gate
   - Read `references/commercial-readiness.md` for the rubric and delivery-tier rules.
   - Score the final rendered deck against commercial readiness before final delivery.
   - If the deck is below client-ready threshold, either redesign until it passes or explicitly label it as an internal draft or speaker-assisted proposal. Do not call it commercial-grade.
   - For client-ready proposals, include 2-3 memorable commercial anchor pages such as ROI/personnel impact, operating model, implementation roadmap, before/after proof, revenue model, risk-control page, or final ask.
   - If source material lacks brand assets, real screenshots, real metrics, proof data, or implementation specifics, state the limitation in the QA notes and compensate with placeholders, assumptions, or a recommended input list rather than inventing facts.
   - Deliver or record an edit guide, font/fallback notes, asset usage notes, missing-input caveats, preview evidence, and final signoff status.

## Hard Rules

- Do not generate the final deck as screenshots.
- Do not place important slide text inside generated images.
- Do not fake editable charts with image exports when data is available.
- Do not invent metrics or sources to make a slide look stronger.
- Do not ask user-facing questions or present selectable options in English when the user's working language is Chinese.
- Do not use English-only design DNA names, visual scheme names, or option labels for Chinese users; localize them and keep English only as optional secondary notation.
- Do not start agency-grade production without a creative brief, success criteria, and brand/source asset audit.
- Do not enter final PPTX production without storyboard approval or explicit delegated storyboard approval for high-stakes work.
- Do not let the visual scheme override the story spine.
- Do not build a generic template deck after the user selected a specific visual direction.
- Do not treat a failed `custom_compose` call as permission to change routes; fix the exact error and retry the same route.
- Do not call `presentation_builder` for final visual delivery with an omitted, empty, string-only, or default blue report `theme`; pass the selected scheme's explicit theme object.
- Do not satisfy a visual direction by matching only colors; carry through its composition, imagery, texture, contrast, and page archetypes.
- Do not satisfy a visual direction without a visual-translation contract that maps the selected thumbnail/contact sheet into page archetypes, dominant visual anchors, text zones, focal ratios, typography rhythm, and editable implementation rules.
- Do not enter full PPTX production for client-ready or highly visual decks without a rendered 3-5 slide editable PPT prototype checkpoint, unless the user explicitly delegates or cancels that checkpoint.
- Do not continue from a `delivery_mode="prototype"` result to final production in the same turn; present the rendered prototype and wait.
- Do not deliver a slide count that differs from the approved storyboard; enforce it with `expected_slide_count`.
- Do not satisfy a visual direction without a written typography/font system.
- Do not use default PowerPoint fonts accidentally; use Aptos/Calibri/Arial only when they are deliberately chosen and justified.
- Do not name a premium, brand, or downloaded font unless it is provided, verified installed, or explicitly marked as a required user dependency.
- Do not rasterize real slide text just to preserve a font look.
- Do not mix Chinese, English, and numeric fallback fonts without recording the intended pairing.
- Do not build data, table, process, architecture, comparison, roadmap, or proof-heavy slides without information design rationale.
- Do not use charts or diagrams as decoration; each must answer a decision question.
- Do not create every slide as a one-off layout; define master layout rules and component families first.
- Do not generate imagegen visual schemes before selecting and scoring market-informed design DNA.
- Do not invent an unscored hybrid/fusion option merely to fill the third visual-scheme slot.
- Do not treat design DNA names, written descriptions, or text-only option lists as visual schemes; visual scheme selection requires generated image thumbnails/contact sheets.
- Do not skip imagegen visual scheme generation for production decks unless the user explicitly cancels the visual-selection workflow.
- Do not ask the user to choose a visual scheme in QwenPaw until at least one `imagegen` output has been rendered or embedded in the chat.
- Do not present visual scheme selection as one combined image; show one separate image per option with the scheme name immediately above or beside it.
- Do not force the user to choose one of the first generated visual schemes; if none are liked, offer and honor "换一批".
- Do not choose a design DNA because it is fashionable if it fails commercial fit, industry credibility, editability, or deck-wide scalability.
- Do not copy a specific paid template, marketplace item, brand system, or protected designer style; abstract design traits into a new direction.
- Do not skip visual asset generation when the selected scheme clearly depends on cinematic backgrounds, photography, illustrations, textures, or signature marks.
- Do not call `imagegen` for PPT visual schemes or downstream PPT assets without the corresponding structured `presentation_context` stage and selected-DNA fields.
- Do not ship a background-only visual asset set when the deck needs icons, supporting graphics, connector treatments, module surfaces, data badges, or diagram accents to preserve the selected scheme.
- Do not generate dozens of disconnected images as the default asset suite; use a small number of coherent asset sheets and record the reusable elements extracted from them.
- Do not enter PPTX generation for a client-ready hybrid deck until the asset suite has either visible source asset-sheet previews or an explicit native-only/delegated rationale.
- Do not enter PPTX generation without an asset-to-slide usage matrix when a visual asset suite has been generated.
- Do not let approved component sheets remain unused as mood references; use them directly, crop elements from them, or translate them into native components with a recorded mapping.
- Do not count backgrounds and textures as sufficient asset-suite usage when pictograms, module surfaces, connectors, data badges, or case strips were generated for body-slide quality.
- Do not put component sheets, icon sheets, module sheets, connector sheets, moodboards, or style-reference boards into `required_image_assets` just to satisfy asset usage. They should become native PPT components or be omitted with rationale.
- Do not use generated component sheets before classifying asset fitness. Direct raster use is allowed only for production-ready, non-text visual components with role match, intact frame, acceptable aspect ratio, and verified safe crop.
- Do not overcorrect unused assets by filling the deck with raster icons, panels, connectors, or badges. Respect the direct-raster density budget and prefer native redraw for repeated content-bearing components.
- Do not use assets to satisfy quotas when they do not support the slide's story, information design, or composition. A clean hero page is better than a page polluted by unnecessary arrows, badges, icons, or small images.
- Do not use raster module surfaces, data badges, cards, or input-box-like elements as text containers unless a safe text area, padding, and rendered containment check are recorded.
- Do not stretch or `fit: "cover"` fixed-aspect raster component frames into different card shapes. Redraw them natively or use an explicitly 9-slice-safe asset.
- Do not use a non-16:9 cropped tile as a full-slide background or texture plate unless a rendered full-size QA pass proves it fills the entire slide with no unintended edge bars.
- Do not treat PowerPoint's gray editor canvas or page shadow outside the slide as a deck background defect; verify the exported slide pixels before redesigning.
- Do not build every slide from the same card/grid grammar; vary impact, evidence, explanation, and transition page rhythms.
- Do not create a non-appendix slide without a defined focal point and hierarchy.
- Do not create a non-appendix slide without motion direction or an explicit reason it should remain static.
- Do not use plain rounded rectangles as the default answer to strategy, service, product, or case-study content.
- Do not use default straight lines, arrows, or control-looking widgets as the primary diagram language unless they have been intentionally designed as part of the chosen scheme.
- Do not use 5 visual schemes by default; use 3 unless broader exploration is requested.
- Do not proceed past visual scheme thumbnails without user selection or explicit delegated selection.
- Do not use raw source copy as slide headlines when the source needs presentation compression, buyer-facing framing, or highlight extraction.
- Do not write ad hoc PPTX generation code when `presentation_builder` can build and verify the deck. The tool-level package QA is mandatory when generated images are required.
- Do not promise native PowerPoint animation when the runtime cannot implement it; use editable step-build slides as the fallback.
- Do not confuse a technically valid PPTX with a commercial deliverable.
- Do not deliver client-ready work without an edit guide, asset notes, font/fallback notes, preview evidence, and caveat/signoff note.
- Do not use step-build duplicates as the default final customer deck if they make the exported deck feel repetitive; keep them only when the user wants presenter-click rhythm or provide a clean client-reading variant.
- Do not ship a client-ready proposal that lacks client specificity, proof, implementation credibility, or at least two memorable commercial anchor pages.

## Output Contract

For planning-only requests, return:

- feasibility assessment
- recommended workflow
- key risks and guardrails
- suggested schema or prompt snippets if useful

For production requests, create:

- outline/story spine
- agency creative brief, success bar, review gates, and brand/source asset audit
- optimized copy strategy and extracted commercial highlights
- storyboard with slide roles, narrative beats, proof objects, and approval/delegation record
- selected 4-5 visual exploration pages
- 3-5 candidate design DNA directions with scores, risks, and selected 2-3 finalists
- 3 visual scheme prompts and generated image thumbnails/contact sheets with paths or embedded previews
- Chinese-localized user visual scheme selection checkpoint, "换一批" option, regeneration record, and selected scheme record when the user is Chinese
- chosen design system spec
- visual-translation contract with selected-scheme deconstruction, page archetype map, dominant visual anchors, text zones, focal ratios, and prototype checkpoint record
- typography/font system with font availability, fallback stack, type scale, and usage rules
- information design system for charts, tables, diagrams, screenshots, evidence notes, and annotations
- slide-by-slide art direction
- slide-by-slide motion/reveal direction, including native-animation or step-build fallback decisions
- design component library
- master layout system
- visual asset suite with source asset-sheet paths, reusable element count, saved paths, slide usage notes, crop notes, editability boundaries, and preview/delegation record when required
- asset fitness report, direct-raster density budget, asset-to-slide usage matrix, and post-build usage audit showing which generated asset families actually appear, were intentionally translated/omitted, were overused, or failed component integrity
- 3-5 slide editable PPT prototype previews for client-ready or highly visual decks, with user approval/delegation or recorded revision actions before full deck production
- editable PPTX/PDF primary files
- internal `*.presentation.compose.json` source ledger for layout, asset usage, QA, and rebuild provenance
- rendered preview evidence, visual QA notes, motion/rhythm QA notes, information design QA, edit guide, delivery notes, and commercial readiness score with delivery-tier judgment

## References

- Read `references/workflow.md` for detailed stage gates, visual scheme prompt structure, and QA checks.
- Read `references/premium-agency-standards.md` before creative brief, storyboard, master layout, delivery package, or signoff decisions.
- Read `references/copy-optimization.md` before turning source material into story spine, headlines, or slide copy.
- Read `references/design-dna.md` before selecting market-informed design DNA or writing imagegen visual scheme prompts.
- Read `references/typography-system.md` before choosing fonts, writing the design system, or building editable slides.
- Read `references/information-design.md` before building data, table, chart, process, architecture, roadmap, operating-model, or evidence-heavy slides.
- Read `references/asset-suite.md` before generating final-deck imagegen assets or approving body-slide visual components.
- Read `references/slide-schema.md` before generating the final deck or asking another agent/tool to generate it.
- Read `references/design-direction.md` before writing art direction, motion direction, component library rules, or visual QA notes.
- Read `references/commercial-readiness.md` before claiming that a deck is commercial-grade, client-ready, proposal-ready, investor-ready, or suitable for standalone customer delivery.
