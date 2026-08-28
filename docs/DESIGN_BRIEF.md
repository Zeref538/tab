# Design brief — TAB

The interface is a review screen and a ledger. It is looked at by someone who
would rather not be looking at it, clearing a queue at the end of a long day.
Everything below serves that.

---

## 1. Tone

**Quiet. Exact. Unfussy.**

For a freelancer with forty receipts and no patience. The screen should feel like
a well-kept ledger, not a dashboard — no gradient cards, no sparklines, no
celebration animation when a row commits. The reward for using this is that there
is nothing to look at.

The one place with visual force is a flagged field. If everything shouts, the
flag is invisible, which defeats the entire product.

## 2. Colour

Paper and ink, with exactly three states that mean something: committed,
flagged, discarded. Every value below is a token, defined once.

```css
:root {
  --paper:        #FAF9F6;   /* page background — warm, not clinical white */
  --card:         #FFFFFF;
  --ink:          #1A1A18;   /* body text — 16.55:1 on --paper */
  --ink-soft:     #5C5A54;   /* secondary text — 6.55:1 on --paper */
  --rule:         #E3E0D8;   /* decorative hairlines only — 1.25:1 */
  --rule-strong:  #8A867C;   /* borders of real controls — 3.45:1 */

  --flag:         #B45309;   /* a field needing review — 4.77:1 on --paper */
  --flag-wash:    #FDF3E3;   /* the row behind a flagged field */
  --ok:           #2F6F4F;   /* committed — 5.69:1 on --paper */
  --ok-wash:      #EDF5F0;
  --stop:         #A32F2F;   /* discard, delete, hard error — 6.64:1 */

  --focus:        #1D4ED8;   /* focus ring only, never a fill — 6.37:1 */
}

:root[data-theme="dark"] {
  --paper:        #161614;
  --card:         #1F1F1C;
  --ink:          #F2F0EA;   /* 15.90:1 on --paper */
  --ink-soft:     #A8A49A;   /* 7.28:1 */
  --rule:         #34332E;   /* decorative only — 1.43:1 */
  --rule-strong:  #6E6B62;   /* control borders — 3.40:1 */

  --flag:         #F0A85C;   /* 9.03:1 on --paper */
  --flag-wash:    #2C2318;
  --ok:           #6FBF95;   /* 8.25:1 */
  --ok-wash:      #17251E;
  --stop:         #E8837E;   /* 6.88:1 */

  --focus:        #7FA5FF;   /* 7.53:1 */
}
```

The review page follows the system setting with
`@media (prefers-color-scheme: dark)` and offers no toggle of its own — one less
control on a screen whose whole job is to be got through quickly. The token
values are identical either way, and `tests/test_design_tokens.py` fails if the
page and this document ever disagree.

Colour never carries a meaning alone. A flagged field has the wash **and** a
left border **and** the sentence explaining the failing sum. Someone who cannot
distinguish the amber still sees all three.

## 3. Type

Money is the content, so figures get a font where digits line up in a column and
a `1` cannot be read as a `7`.

```css
--font-ui:   ui-sans-serif, "Inter", "Segoe UI", system-ui, sans-serif;
--font-num:  ui-monospace, "JetBrains Mono", "Cascadia Mono", monospace;
```

Every amount, date, TIN and OR number renders in `--font-num` with
`font-variant-numeric: tabular-nums`. Amounts are right-aligned, always, so a
column of pesos reads as a column.

| step | size | use |
|---|---|---|
| xs | 12px / 1.4 | table meta, timestamps |
| sm | 14px / 1.5 | form labels, secondary text |
| base | 16px / 1.6 | body, field values |
| lg | 20px / 1.4 | the failing-check sentence |
| xl | 28px / 1.2 | the receipt total |
| 2xl | 36px / 1.1 | the scoreboard numbers on the public page |

Nothing is set below 12px, and the failing-check sentence is deliberately larger
than the fields around it — it is the reason the screen exists.

## 4. Space, radius, shadow

A 4px base scale: `4 8 12 16 24 32 48 64`. Nothing between steps.

Radius: `4px` on inputs and buttons, `8px` on cards, `0` on table rows. Receipts
are rectangles; the interface does not need to be softer than the thing it shows.

Shadow: one, and only on an element that floats over another —
`0 1px 3px rgb(0 0 0 / 0.08), 0 8px 24px rgb(0 0 0 / 0.06)`. Cards sitting in the
page get a `--rule` border instead. A shadow on something that is not floating is
a lie about depth.

## 5. Component states

Every interactive element defines all six. A state that is not designed gets
designed by the browser, badly.

| state | treatment |
|---|---|
| rest | `--card` fill, `--rule-strong` border |
| hover | border darkens one step; **no** movement, no scale, no shadow change |
| focus | `2px` `--focus` ring, `2px` offset — visible on every background, never removed |
| active | fill shifts one step toward the ink; no transform |
| disabled | 50% opacity, `cursor: not-allowed`, and a `title` saying why it is disabled |
| loading | the label is replaced by its progress text, and the width is held so nothing jumps |
| error | `--stop` border, message directly below in `--stop`, and `aria-describedby` pointing at it |

The flagged field is its own state: `--flag-wash` fill, `3px` `--flag` left
border, and it receives focus on page load.

## 6. Accessibility floor

Not aspirational. These are pass/fail.

- **Contrast:** 4.5:1 for text, 3:1 for the visible boundary of any control.
  Every ratio above was computed, not estimated, by the WCAG relative-luminance
  formula against its own background — a new token without a measured ratio is
  not finished. `--rule` is the one token below 3:1, and it is therefore allowed
  on decorative hairlines only, never on the edge of something you can click.
- **Keyboard:** the entire review flow — open, edit, approve, next — works with
  no mouse. Tab order follows reading order. Enter approves. Escape cancels an
  edit rather than the whole document.
- **Focus visible:** always. If a focus ring is ever removed, that is a bug.
- **Labels:** every input has a real `<label>`, not a placeholder pretending.
- **Announcements:** the failing-check sentence is in an `aria-live="polite"`
  region so it is read when the next queue item loads.
- **Reduced motion:** `prefers-reduced-motion: reduce` removes the queue
  transition entirely. Nothing in this interface depends on animation to be
  understood.
- **Target size:** 44×44px minimum for anything clickable.
- **Zoom:** usable at 200% without horizontal scrolling.

## 7. The one image that matters

The receipt itself. It is shown at the largest size the viewport allows, never
cropped, and zoomable — someone is trying to read a faded thermal total, and a
thumbnail makes the whole screen pointless. The extracted value sits beside the
image, never on top of it.

## 8. The public page

Same tokens, different job: it has ten seconds. One receipt, one row building,
one field lighting up amber. Then the scoreboard, where straight-through rate
and silent error rate are the same size, in the same weight, side by side.

Making the good number bigger than the honest one would be a design decision
about truth, and the answer is no.
