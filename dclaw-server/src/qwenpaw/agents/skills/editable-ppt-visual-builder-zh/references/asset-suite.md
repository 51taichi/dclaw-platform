# Visual Asset Suite Reference

Use this reference after the user selects a visual scheme and before building the editable PPTX. The goal is to produce the visual ingredients that let body slides feel designed, not merely colored.

## Principle

Imagegen should not only create cover backgrounds. A commercial editable PPT often needs a small suite of reusable visual assets that carry the selected design DNA into process pages, architecture pages, proof pages, and offer pages.

A background-only asset set is incomplete for client-ready work unless the chosen design is deliberately native-only and rendered QA proves the body slides still look designed.

Asset usage must be page-archetype-bound, not quota-bound. A generated asset is useful only when it strengthens a slide's narrative role, focal point, information design, or selected visual scheme. Do not place icons, arrows, badges, connector crops, or small images on a slide simply to increase asset usage.

## Quantity Defaults

Do not default to generating dozens of individual images. For most 10-15 slide commercial decks, create a small coherent suite:

- 6-10 source asset sheets or source images
- 10-25 extracted or cropped reusable elements when the deck needs them
- 1-3 hero, section, or closing backgrounds
- 3-5 page-bound hero, background, or visual-metaphor assets when the selected contact sheet relies on dominant visual anchors
- 2-4 body texture, atmosphere, or pattern plates
- 1 icon/pictogram family sheet with roughly 8-16 symbols
- 1 module surface or component panel sheet with roughly 4-8 variants
- 1 connector/node/diagram accent sheet
- 1 data badge, label, or metric container sheet when proof pages need designed metrics
- 1-3 case image strips, product metaphors, or industry scene images when the story needs them

For shorter decks, reduce the suite. For decks above 20 slides, add assets only when a new slide archetype requires them. More than 10 source asset sheets requires a clear reason, such as multiple chapters, distinct product lines, or a reusable template system.

Generate asset sheets when style consistency matters. Generate individual images only for large backgrounds, chapter visuals, proof/case image strips, or specific visual metaphors that need their own composition.

For selected visual schemes with strong page compositions, generate page-bound hero assets for the representative slide archetypes before relying on reusable kit sheets. These assets should reserve calm editable text zones and carry the large visual anchor that makes the scheme distinctive.

Full-slide backgrounds, section plates, closing plates, and any texture meant to cover the whole slide must be generated or prepared as 16:9 full-bleed images. Do not cut a small tile out of a multi-item asset sheet and use it as a full-slide background unless it is converted into a 16:9 plate and passes edge-coverage QA.

## Required Asset Planning

For each selected scheme, decide which asset families are required:

- cover hero or opening background
- page-bound hero or metaphor plates for the key cover, thesis, product/platform, mechanism, roadmap, or closing slides
- section or closing backgrounds
- body-slide texture plates
- product/platform metaphor images
- case-study or proof image strips
- signature marks such as strokes, frames, glow lines, grid marks, or editorial underlines
- icon or pictogram family
- module surfaces or component panels
- connector treatments for flows, service systems, architecture, and roadmaps
- data badges for metrics and proof points
- diagram accents such as nodes, halos, braces, lanes, ticks, or milestones

Use fewer, stronger assets rather than many generic decorative images.

## Recommended Asset Sheets

Use these as defaults when the selected visual scheme needs a hybrid visual language:

- icon/pictogram sheet: same perspective, stroke/fill logic, metaphor level, and density
- module surface sheet: cards, panels, frames, UI-like surfaces, product/service containers, and active/quiet states
- connector treatment sheet: arrows, bends, endpoints, node halos, braces, lanes, milestones, and sequence markers
- data badge sheet: metric containers, proof labels, small highlight modules, and status chips without real numbers
- texture/background sheet: body plates, overlays, material finishes, lighting, paper/noise/scanline effects, or editorial marks
- section/closing background sheet: stronger chapter or payoff visuals with reserved editable text areas
- case/image strip sheet: image panels or scene crops for proof/case pages, without fake evidence or fake UI text

Each sheet should be reusable. If a sheet cannot support at least two slides or a central slide archetype, either remove it or generate it as a specific single-use asset.

Background and texture sheets should separate two asset roles:

- full-bleed plates: individual 16:9 images used at slide size
- overlay tiles: smaller texture pieces used as transparent/subtle layers, never assumed to fill the whole slide

## Asset Plan Fields

Each asset must record:

- asset id
- filename
- asset type
- source asset sheet id when extracted from a sheet
- target slides
- prompt summary
- safe crop and reserved text area
- layer role: background, midground, foreground accent, texture, image panel, or reusable symbol
- editability boundary
- linked component or slide archetype
- full-bleed status: `full-slide-16:9`, `partial-bleed`, `overlay-only`, or `symbol`
- asset fitness: `production-ready`, `reference-only`, `accent-only`, or `reject`
- direct raster approval: whether this asset may be placed directly in the PPT as a component
- safe text area and padding when the asset is used near or behind editable text
- scaling rule: original-aspect only, 9-slice-safe, full-bleed 16:9, accent-only, native-redraw, or reject

## Asset Fitness Gate

Before PPTX generation, inspect every extracted or cropped element and classify it:

- `production-ready`: complete frame or symbol, clean crop, role match, acceptable aspect ratio, no embedded real text, no broken edges, and safe for direct placement.
- `reference-only`: useful visual grammar but not safe as a component because it has a fixed frame, opaque background, decorative internal lines, awkward crop, or no usable text area.
- `accent-only`: safe as a small decorative mark or non-text visual cue, but not as a card, input box, badge, or container.
- `reject`: low-quality, clipped, unreadable, off-style, or impossible to integrate without making the slide look cheap.

Direct raster use is allowed only for `production-ready` assets. Use `reference-only` and `accent-only` assets to redraw native PPT components or to define style, not as content containers.

Never assume a multi-item generated sheet produces production components automatically. A beautiful sheet can still be unsuitable for direct PPT placement if the individual elements cannot be cropped cleanly or resized safely.

## Asset-To-Slide Usage Matrix

Before PPTX generation, create a usage matrix. A generated asset suite is not successful until its families influence actual slides.

For each asset family, record:

- asset family: background, texture, icon/pictogram, module surface, connector treatment, data badge, diagram accent, case/product image strip, signature mark
- planned target slides
- usage mode: direct raster crop, native redraw reference, hybrid, or omitted
- minimum expected usage count
- component or slide archetype it supports
- fallback if the image asset cannot be cleanly used
- maximum expected direct raster usage count
- asset fitness and whether native redraw is required
- safe text area requirement when the asset supports a content-bearing component

For a typical 10-15 slide client-ready hybrid deck:

- backgrounds/textures should support atmosphere but cannot be the only asset usage
- at least 4 non-background asset families should visibly affect the deck unless intentionally omitted
- connector treatments must appear on flow, roadmap, architecture, service-system, or operating-loop slides
- module surfaces must inform service cards, product modules, offer cards, proof panels, or case frames
- pictograms should clarify service modules, commitments, product features, or proof points
- data badges should carry metrics, proof labels, recommendations, commitment seals, or caveat notes

If an asset family was generated but not used, record why before delivery. Do not silently leave approved asset sheets unused as mood references.

If a slide's visual-translation contract marks a family as not needed, omit it without guilt. A deliberate clean composition is better than quota-driven decoration.

## Direct Raster Density Budget

The usage matrix must include both minimum and maximum expected usage. Asset underuse is a failure, but asset overuse is also a failure.

For a normal 10-15 slide client-ready deck, use these starting limits unless the art direction records a reason and full-size QA passes:

- pictograms: about 6-12 total direct raster uses
- module surfaces: about 3-8 direct raster uses, with repeated service cards usually redrawn natively
- connector treatments or node motifs: about 2-6 direct raster uses, with most paths rebuilt as native connectors
- data badges: about 2-5 direct raster uses
- case/product image strips: about 2-4 direct raster uses

Using dozens of direct raster icons, panels, badges, or connector crops in a 10-15 slide deck is normally a density failure. Prefer fewer signature assets plus native component redraws.

Using even one direct raster icon, arrow, badge, or small component can be a failure when it is disconnected from the slide's claim or visual composition.

## Prompt Rules

Generate assets as separate reusable pieces, not finished slide screenshots.

Prompts should include:

- use case: productivity visual
- asset type
- deck topic
- selected visual scheme and design DNA
- page archetype and visual-translation role when the asset is page-bound
- composition and crop role
- reserved calm area for editable PPT text
- no readable text, labels, charts, logos, watermarks, or numbers
- intended layer usage inside an editable PowerPoint deck

## Designed Body-Slide Language

When a slide needs lines, arrows, boxes, UI-like controls, or icons, create a designed language before drawing:

- connectors should have a consistent weight, cap style, bend logic, endpoint style, and accent behavior
- module surfaces should match the material, lighting, radius, border, and shadow rules of the selected scheme
- pictograms should share perspective, stroke/fill logic, visual density, and metaphor level
- data badges should have a distinct hierarchy from normal cards
- diagram accents should help structure the argument instead of decorating empty space

## Native vs Raster

Use native PPT for:

- text, labels, metrics, chart values, table cells, process names, module names, and captions
- simple connectors, frames, icons, and badges when they can be drawn cleanly
- repeated cards, module surfaces, input boxes, data badges, service panels, and connectors that contain or align to editable text

Use raster assets for:

- texture, lighting, atmosphere, dimensionality, photo/illustration metaphors
- complex icon/pictogram treatments that cannot be cleanly drawn with native shapes
- decorative marks that create the selected scheme's signature feel

Keep raster assets as independent PowerPoint image objects. Do not bake real slide content into them.

## Component Safe Text Area And Scaling Rules

A generated module surface, badge, card, input-box-like element, or connector panel may hold nearby editable text only when the slide plan records:

- safe text rectangle: x, y, width, height relative to the placed asset or native component
- padding: minimum internal margin from frame, glow, shadow, clipped edge, or decorative line
- text hierarchy: title, value, body, caption, or label role
- scaling rule: original aspect ratio, 9-slice-safe, native redraw, or reject
- rendered containment check: text remains inside the intended area in the exported slide preview

Do not stretch fixed-aspect raster panels or badges to become wider cards. Do not use `fit: "cover"` on component assets when the border, corners, frame, or internal decorative logic must stay intact. If the deck needs a different size, redraw the component with native shapes or regenerate a proper 9-slice-safe / transparent asset.

Native redraw should preserve the visual DNA: material, border weight, glow/shadow, radius, corner treatment, accent line, and contrast. Native redraw does not mean falling back to plain rounded rectangles.

## Edge Coverage QA

For every slide using a generated full-slide background or texture:

- Render a full-size slide preview, not only a montage.
- Confirm the exported slide image is the intended 16:9 size.
- Inspect the left, right, top, and bottom edges for unintended bars, margins, transparency, or viewer-gray bleed.
- If a screenshot comes from PowerPoint or another editor, distinguish the gray application canvas/page shadow outside the slide from pixels inside the slide.
- Regenerate or rebuild the background as a true 16:9 full-bleed plate if edge bars are inside the slide.

## Preview Gate

Before building the editable PPTX for a client-ready hybrid deck, show a lightweight asset-suite preview when possible:

- source asset sheets or contact-sheet paths
- which reusable elements will be extracted
- which slides/components each asset family supports
- what remains native editable PPT
- any visual risk, such as too much image dependence, weak icon consistency, or insufficient connector language

For Chinese users, ask in Chinese and offer clear options:

```text
组件素材套件已经准备好，我建议用这套继续制作 PPT。

1. 继续制作
2. 换一批组件
3. 减少图片感、提高可编辑性
4. 增强视觉冲击
```

If the user requests changes, regenerate only the weak asset family when possible instead of restarting the entire visual direction.

## Post-Build Usage Audit

After rendering the deck, audit actual usage:

- Count how many slides use each generated asset family directly.
- Count how many slides translate each asset family into native PPT components.
- Flag generated families with zero usage.
- Flag generated families that exceed the direct raster density budget without a recorded reason.
- Flag any direct raster component whose asset fitness was not `production-ready`.
- Flag component assets that are clipped, stretched, distorted, or placed with broken frame edges.
- Flag any raster component used as a text container without a declared and rendered safe text area.
- Flag decks where only backgrounds/textures/case images appear but icons, module surfaces, connectors, badges, or diagram accents were unused.
- Redesign affected slides or record a deliberate omission before delivery.
- Flag quota-driven decoration: generated assets placed on a slide without a recorded narrative, information-design, or composition role.

## Failure Patterns

- only cover and closing backgrounds are generated
- dozens of disconnected decorative images are generated instead of a coherent suite
- a non-16:9 texture tile is stretched or placed as a full-slide background and creates side bars, empty margins, or viewer-dependent edge artifacts
- approved icon, panel, connector, or badge sheets are generated but never appear in the final PPT
- approved icon, panel, connector, or badge sheets are overused as decoration and make slides noisy or cheap
- assets are added to strong hero pages only to satisfy usage targets
- generated component sheets are treated only as mood references with no asset-to-slide mapping
- generated component sheets are treated as ready-made containers without asset fitness review
- fixed-aspect raster panels are stretched, cropped, or `fit: "cover"` placed into different card shapes
- editable text is overlaid on raster panels without a safe text area and rendered containment check
- body slides use default arrows, raw lines, generic rounded rectangles, and office-like controls
- icons are mixed from unrelated styles
- assets act as wallpaper and do not change composition
- every module surface has the same card treatment regardless of slide role
- imagegen creates small unreadable text or fake UI labels
- asset usage is not recorded before `presentation_builder` work begins
