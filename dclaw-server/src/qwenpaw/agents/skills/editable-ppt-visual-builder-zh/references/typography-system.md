# Typography And Font System Reference

Use this reference after visual scheme selection and before final deck generation. A commercial editable PPT needs a written typography system, not just attractive colors and backgrounds.

## Principle

Fonts affect perceived price, credibility, readability, and editability. Treat fonts as a delivery decision and a design decision.

Do not rely on unspecified PowerPoint defaults. Do not name a font that may be unavailable unless it is verified, provided, or clearly marked as a user dependency.

## Required Font System

Define:

- display font for cover, section dividers, and thesis pages
- primary Chinese font for titles and body
- primary Latin font for English terms
- numeric font for metrics, dashboards, dates, and prices
- caption/label font or role
- optional mono/code font for technical labels
- fallback stack for Windows, macOS, and the render environment when relevant
- availability status: system default, verified installed, provided font file, required user dependency, or assumed fallback
- license and delivery notes

## Font Pairing Rules

- Chinese decks need explicit CJK choices. Latin-only fonts will trigger fallback for Chinese text.
- Numbers often need a different treatment from body text; metric pages should not look accidental.
- Use no more than 2-3 font families unless the brand system requires more.
- Use a small set of weights, usually regular, medium/semibold, bold, and one display weight if needed.
- Match font personality to design DNA: editorial, consulting, technical platform, premium product, or workshop.

## Safe Fallback Thinking

Prefer fonts that are likely to render across the user's target environment, or write clear caveats.

Common fallback families to consider, depending on environment and deck tone:

- Chinese sans: `Microsoft YaHei`, `DengXian`, `PingFang SC`, `Noto Sans CJK SC`, `Source Han Sans SC`
- Chinese serif/editorial: `Noto Serif CJK SC`, `Source Han Serif SC`, `Songti SC`, `SimSun`
- Latin sans: `Aptos`, `Arial`, `Inter`, `Helvetica Neue`, `Segoe UI`
- Numeric/technical: `Aptos`, `Arial`, `DIN` only if provided or verified, `Roboto Condensed` only if provided or verified
- Mono/code: `Cascadia Mono`, `Consolas`, `SF Mono`, `Menlo`

These are candidates, not automatic choices. Verify availability when possible and record fallback.

## Type Scale

Define a type scale in points before building slides:

- cover title
- section title
- slide title
- body
- caption
- label
- metric
- callout
- footnote

For each role, define:

- font role
- size range or exact point size
- weight
- line spacing
- max line count
- usage notes

Use type scale to create hierarchy before adding more shapes or decoration.

## Implementation Rules

- Apply font family, size, weight, and line spacing to every editable text object.
- Apply the numeric font role to metrics, chart annotations, dates, and dashboard figures.
- Keep chart labels, table cells, captions, and diagram labels inside the same system.
- Do not rasterize real text to preserve a font effect.
- Do not let imagegen create readable text that becomes part of the final slide.
- If the user's brand font is missing, use a documented fallback and state the missing input.

## QA Checks

After rendering previews:

- check whether CJK text, English text, and numbers look intentionally paired
- inspect body slides at full size for readability
- check that no text has fallen back to an unintended default font
- check title sizes, line breaks, body sizes, captions, and labels against the type scale
- check that font choice still expresses the selected design DNA beyond color
- record any required fonts the recipient must install

## Failure Patterns

- PowerPoint defaults are used by accident
- Chinese text and English/numbers come from unrelated fallbacks
- expensive visual assets are paired with cheap system typography
- too many weights and fonts create a noisy deck
- body text is too small because thumbnails looked fine
- premium font names are listed but not available in the output environment
- real text is flattened into images to keep a font style
