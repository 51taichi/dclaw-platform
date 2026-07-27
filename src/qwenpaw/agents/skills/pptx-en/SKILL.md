---
name: pptx
description: "Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even if the extracted content will be used elsewhere, like in an email or summary); editing, modifying, or updating existing presentations; combining or splitting slide files; working with templates, layouts, speaker notes, or comments. Trigger whenever the user mentions \"deck,\" \"slides,\" \"presentation,\" or references a .pptx filename, regardless of what they plan to do with the content afterward. If a .pptx file needs to be opened, created, or touched, use this skill."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.1"
---

> **Important:** All `scripts/` paths are relative to this skill directory.
> Run with: `cd {this_skill_dir} && python scripts/...`
> Or use the `cwd` parameter of `execute_shell_command`.

# PPTX Skill

## Prerequisites

- **markitdown[pptx]**: text extraction from presentations
- **Pillow**: thumbnail grid generation
- **presentation_builder**: preferred built-in tool for creating or regenerating presentations from scratch
- **pptxgenjs** (`npm install -g pptxgenjs`): legacy reference or special template-editing fallback only; not the default generation path
- **LibreOffice** (`soffice`): presentation-to-PDF conversion
- **pdftoppm** (poppler-utils): PDF-to-image conversion for thumbnail/visual workflows
- If `pdftoppm` is unavailable, a Python fallback path may use `pdf2image`.
- On Windows, dependencies must be installed and available in `PATH`; if missing, report the dependency issue and stop (do not keep retrying).

## Quick Reference

| Task | Guide |
|------|-------|
| Read/analyze content | `python -m markitdown presentation.pptx` |
| Edit or create from template | Read [editing.md](editing.md) |
| Create/regenerate from scratch | Prefer the built-in `presentation_builder` tool |

---

## Reading Content

```bash
# Text extraction
python -m markitdown presentation.pptx

# Visual overview
python scripts/thumbnail.py presentation.pptx

# Raw XML
python scripts/office/unpack.py presentation.pptx unpacked/
```

---

## Editing Workflow

**Read [editing.md](editing.md) for full details.**

1. Analyze template with `thumbnail.py`
2. Unpack → manipulate slides → edit content → clean → pack

---

## Creating from Scratch

Use the built-in `presentation_builder` tool when no template or reference
presentation is available, or when the user asks to regenerate a PPT/PPTX.

- Do not use `python_sandbox`, `python-pptx`, temporary scripts, or hand-written ZIP/XML as the final PPTX generation path.
- Pass structured `slides` to `presentation_builder`.
- If generated images exist or the user expects visual directions to survive into the deck, pass `required_image_assets` and `asset_usage_matrix`.
- Every slide must specify or clearly imply a `layout`. Prefer `image_hero`, `section`, `agenda`, `cards`, `comparison`, `process`, `roadmap`, `metrics`, `table`, `architecture`, `quote`, `two_column`, and `content`. Do not reduce the full deck to repeated `title/body/bullets` pages.
- Use layout-specific structures: `items` for cards/comparisons, `steps` for process slides, `metrics` for large-number evidence, `table.headers/table.rows` for tables, and `columns` for two-column slides.
- Pass a `theme` with at least `mode`, `accent`, and `font_family`. Prefer a light grid/brand system for client-ready work unless the user asks for a dark deck.
- If the user provides a reference/template PPTX, do not stop at theme inheritance. Inspect the source deck and build `template_frame_map`: every output slide needs a `sourceSlide`, and `editTargets` should rewrite inherited text or replace inherited images. Pass both `template_path` and `template_frame_map`; the response should report `template_mode=clone_edit`.
- `editTargets` supports `rewrite` and `replace-image`. Select inherited elements with `shapeName`, `shapeId`, `matchText`, or `placeholderType`; `rewrite` needs `text`, and `replace-image` needs `asset_path`. When a generated image must land inside a template image frame, put it in a `replace-image` target and include it in `required_image_assets`.
- Only use `template_path` as a theme seed when the request does not require template following. In that mode the tool audits source slide count, media count, placeholder count, and inherits the template theme when no explicit `theme` is provided.
- For final or client-ready delivery set `delivery_mode="final"`. This forces the equivalent of `strict_qa=true` and `render_qa=true`, even if the model forgets those fields. The Delivery line must report `delivery_mode=final`; the QA line must report `layout_variety`, `weak_slide_count`, `overlap_count`, and `qa_warnings`; the render line must report `render_qa=ok`, `rendered_slide_count`, and `contact_sheet`. If required images were expected but `media_count` or `pic_count` is 0, or if `weak_slide_count > 0` or `overlap_count > 0`, revise the slide specs and rebuild.
- If the request is a visual-direction deck, visual enhancement, brand visual deck, or has generated visual assets in the conversation, also set `requires_visual_assets=true` and provide non-empty `required_image_assets` plus `asset_usage_matrix`. Do not ship a text-only deck as a visual-enhanced deck.

Example structure:

```json
{
  "theme": {"mode": "light", "accent": "#2563EB", "font_family": "Microsoft YaHei"},
  "delivery_mode": "final",
  "strict_qa": true,
  "render_qa": true,
  "slides": [
    {"layout": "image_hero", "kicker": "Proposal", "title": "Enterprise AI Co-build Service", "subtitle": "From diagnosis to Agent platform", "images": [{"asset_path": "/path/hero.png", "role": "hero"}]},
    {"layout": "cards", "title": "Three implementation tracks", "items": [{"title": "AI training", "body": "Build shared understanding"}, {"title": "Strategy consulting", "body": "Define the roadmap"}, {"title": "Agent platform", "body": "Reuse capabilities"}]},
    {"layout": "process", "title": "Co-build workflow", "steps": [{"title": "Diagnose", "body": "Find scenarios"}, {"title": "Pilot", "body": "Validate loop"}, {"title": "Scale", "body": "Roll out"}]},
    {"layout": "comparison", "title": "Option comparison", "columns": [{"title": "Traditional outsourcing", "body": "One-off delivery\\nKnowledge is hard to retain"}, {"title": "Co-build service", "body": "Build while transferring\\nReusable components"}]},
    {"layout": "metrics", "title": "Expected impact", "metrics": [{"label": "Deployment cycle", "value": "4 weeks", "caption": "Pilot online"}]},
    {"layout": "table", "title": "Service matrix", "table": {"headers": ["Module", "Deliverable", "Value"], "rows": [["Training", "Workshop", "Team alignment"]]}}
  ]
}
```

Template-following example:

```json
{
  "template_path": "/path/reference.pptx",
  "template_frame_map": [
    {
      "outputSlide": 1,
      "sourceSlide": 3,
      "narrativeRole": "opening thesis",
      "editTargets": [
        {"action": "rewrite", "matchText": "Old title", "text": "New title"},
        {"action": "replace-image", "shapeName": "Hero Image", "asset_path": "/path/generated-hero.png"}
      ]
    }
  ],
  "required_image_assets": ["/path/generated-hero.png"],
  "delivery_mode": "final",
  "requires_visual_assets": true,
  "render_qa": true,
  "strict_qa": true
}
```

---

## Design Ideas

**Don't create boring slides.** Plain bullets on a white background won't impress anyone. Consider ideas from this list for each slide.

### Before Starting

- **Pick a bold, content-informed color palette**: The palette should feel designed for THIS topic. If swapping your colors into a completely different presentation would still "work," you haven't made specific enough choices.
- **Dominance over equality**: One color should dominate (60-70% visual weight), with 1-2 supporting tones and one sharp accent. Never give all colors equal weight.
- **Dark/light contrast**: Dark backgrounds for title + conclusion slides, light for content ("sandwich" structure). Or commit to dark throughout for a premium feel.
- **Commit to a visual motif**: Pick ONE distinctive element and repeat it — rounded image frames, icons in colored circles, thick single-side borders. Carry it across every slide.

### Color Palettes

Choose colors that match your topic — don't default to generic blue. Use these palettes as inspiration:

| Theme | Primary | Secondary | Accent |
|-------|---------|-----------|--------|
| **Midnight Executive** | `1E2761` (navy) | `CADCFC` (ice blue) | `FFFFFF` (white) |
| **Forest & Moss** | `2C5F2D` (forest) | `97BC62` (moss) | `F5F5F5` (cream) |
| **Coral Energy** | `F96167` (coral) | `F9E795` (gold) | `2F3C7E` (navy) |
| **Warm Terracotta** | `B85042` (terracotta) | `E7E8D1` (sand) | `A7BEAE` (sage) |
| **Ocean Gradient** | `065A82` (deep blue) | `1C7293` (teal) | `21295C` (midnight) |
| **Charcoal Minimal** | `36454F` (charcoal) | `F2F2F2` (off-white) | `212121` (black) |
| **Teal Trust** | `028090` (teal) | `00A896` (seafoam) | `02C39A` (mint) |
| **Berry & Cream** | `6D2E46` (berry) | `A26769` (dusty rose) | `ECE2D0` (cream) |
| **Sage Calm** | `84B59F` (sage) | `69A297` (eucalyptus) | `50808E` (slate) |
| **Cherry Bold** | `990011` (cherry) | `FCF6F5` (off-white) | `2F3C7E` (navy) |

### For Each Slide

**Every slide needs a visual element** — image, chart, icon, or shape. Text-only slides are forgettable.

**Layout options:**
- Two-column (text left, illustration on right)
- Icon + text rows (icon in colored circle, bold header, description below)
- 2x2 or 2x3 grid (image on one side, grid of content blocks on other)
- Half-bleed image (full left or right side) with content overlay

**Data display:**
- Large stat callouts (big numbers 60-72pt with small labels below)
- Comparison columns (before/after, pros/cons, side-by-side options)
- Timeline or process flow (numbered steps, arrows)

**Visual polish:**
- Icons in small colored circles next to section headers
- Italic accent text for key stats or taglines

### Typography

**Choose an interesting font pairing** — don't default to Arial. Pick a header font with personality and pair it with a clean body font.

| Header Font | Body Font |
|-------------|-----------|
| Georgia | Calibri |
| Arial Black | Arial |
| Calibri | Calibri Light |
| Cambria | Calibri |
| Trebuchet MS | Calibri |
| Impact | Arial |
| Palatino | Garamond |
| Consolas | Calibri |

| Element | Size |
|---------|------|
| Slide title | 36-44pt bold |
| Section header | 20-24pt bold |
| Body text | 14-16pt |
| Captions | 10-12pt muted |

### Spacing

- 0.5" minimum margins
- 0.3-0.5" between content blocks
- Leave breathing room—don't fill every inch

### Avoid (Common Mistakes)

- **Don't repeat the same layout** — vary columns, cards, and callouts across slides
- **Don't center body text** — left-align paragraphs and lists; center only titles
- **Don't skimp on size contrast** — titles need 36pt+ to stand out from 14-16pt body
- **Don't default to blue** — pick colors that reflect the specific topic
- **Don't mix spacing randomly** — choose 0.3" or 0.5" gaps and use consistently
- **Don't style one slide and leave the rest plain** — commit fully or keep it simple throughout
- **Don't create text-only slides** — add images, icons, charts, or visual elements; avoid plain title + bullets
- **Don't forget text box padding** — when aligning lines or shapes with text edges, set `margin: 0` on the text box or offset the shape to account for padding
- **Don't use low-contrast elements** — icons AND text need strong contrast against the background; avoid light text on light backgrounds or dark text on dark backgrounds
- **NEVER use accent lines under titles** — these are a hallmark of AI-generated slides; use whitespace or background color instead

---

## QA (Required)

**Assume there are problems. Your job is to find them.**

Your first render is almost never correct. Approach QA as a bug hunt, not a confirmation step. If you found zero issues on first inspection, you weren't looking hard enough.

### Content QA

```bash
python -m markitdown output.pptx
```

Check for missing content, typos, wrong order.

**When using templates, check for leftover placeholder text:**

```bash
python -m markitdown output.pptx | grep -iE "xxxx|lorem|ipsum|this.*(page|slide).*layout"
```

If grep returns results, fix them before declaring success.

### Visual QA

**⚠️ USE SUBAGENTS** — even for 2-3 slides. You've been staring at the code and will see what you expect, not what's there. Subagents have fresh eyes.

Convert slides to images (see [Converting to Images](#converting-to-images)), then use this prompt:

```
Visually inspect these slides. Assume there are issues — find them.

Look for:
- Overlapping elements (text through shapes, lines through words, stacked elements)
- Text overflow or cut off at edges/box boundaries
- Decorative lines positioned for single-line text but title wrapped to two lines
- Source citations or footers colliding with content above
- Elements too close (< 0.3" gaps) or cards/sections nearly touching
- Uneven gaps (large empty area in one place, cramped in another)
- Insufficient margin from slide edges (< 0.5")
- Columns or similar elements not aligned consistently
- Low-contrast text (e.g., light gray text on cream-colored background)
- Low-contrast icons (e.g., dark icons on dark backgrounds without a contrasting circle)
- Text boxes too narrow causing excessive wrapping
- Leftover placeholder content

For each slide, list issues or areas of concern, even if minor.

Read and analyze these images:
1. /path/to/slide-01.jpg (Expected: [brief description])
2. /path/to/slide-02.jpg (Expected: [brief description])

Report ALL issues found, including minor ones.
```

### Verification Loop

1. Generate slides → Convert to images → Inspect
2. **List issues found** (if none found, look again more critically)
3. Fix issues
4. **Re-verify affected slides** — one fix often creates another problem
5. Repeat until a full pass reveals no new issues

**Do not declare success until you've completed at least one fix-and-verify cycle.**

---

## Converting to Images

Convert presentations to individual slide images for visual inspection:

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
pdftoppm -jpeg -r 150 output.pdf slide
```

This creates `slide-01.jpg`, `slide-02.jpg`, etc.

To re-render specific slides after fixes:

```bash
pdftoppm -jpeg -r 150 -f N -l N output.pdf slide-fixed
```
