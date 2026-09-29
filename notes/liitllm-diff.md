# TAB's case study against LiitLLM's

LiitLLM is the reference build named in `BRAND.md`. The live page was used as
the source (`https://zeref538.github.io/liitllm/`, fetched 2026-09-29) because
the working folder is archived in `LiitLLM.rar`.

Notes live here and not in `docs/`, because `docs/` is the GitHub Pages source
and everything in it is published on push.

## How the comparison was made

Not by eye. Both pages were parsed for the classes their stylesheets define and
the classes their markup and scripts actually use, then the two sets were
subtracted from each other. That is what turned up the bars that were never
styled — they were in the "used, never defined" column.

```bash
grep -c 'class="[^"]*meter' tools/site_template.html   # markup says yes
grep -c '\.meter '          tools/site_template.html   # stylesheet says no
```

A class that appears in the markup and not in the stylesheet renders as
nothing, silently. The browser has no warning for it. A class that appears in
the stylesheet and not in the markup is the reverse problem: the file describes
a component that does not exist, and the next reader trusts it.

## Skeleton: identical, measured

| thing | LiitLLM | TAB |
|---|---|---|
| console max-width | 1360px | 1360px |
| console radius | 16px | 16px |
| console-main padding | 32px | 32px |
| h1 size | `clamp(56px, 7vw, 80px)` | same |
| rail column | `200px minmax(0, 1fr)` | same |
| footer padding | `40px 0 64px` | same |
| body size | 16.5px | same |

## Difference table

| element | LiitLLM | TAB | fix or keep | why |
|---|---|---|---|---|
| accent tint | `--clay-w`, same hue as the accent pushed to L 0.92 light / 0.19 dark | was `#d7ece5`, a green inherited from another project | **fixed** | the tint was not related to TAB's accent at all; now `#faddf1` / `#481739`, derived by the same rule |
| live-app link | plain `href` in the HTML | `href="#"` plus `hidden`, corrected by script | **fixed** | with JavaScript off the link was invisible and dead; now substituted at build time |
| footer corpus and date | written into the HTML | filled by script | **fixed** | both rendered blank without JavaScript |
| footer author line | two sentences | second sentence missing | **fixed** | the missing line is the one telling a stranger what they are looking at |
| charts | 3 figures, generated | 1 figure, and a bar column that was invisible | **fixed** | `.meter` had no CSS anywhere; added, plus a second figure splitting all 100 receipts by outcome |
| `worst` card | n/a | set by the script, no CSS | **fixed** | the card the page calls "the one that matters" looked like the other three |
| verdict badge | `.drop` / `.keep` | script sets `.ok` / `.bad`, CSS knows `.probe` / `.move` | **fixed** | FILED and NEEDS A PERSON wore the same grey |
| `.kicker` | one rule, used | three conflicting rules, used nowhere | **fixed** | two deleted, survivor now labels the notes |
| `.note.warn` | used for the caveat | styled, never used | **fixed** | now carries the corpus-scope limit |
| dead rules | — | `.bar-track`, `.bar-fill`, `.verdict.move`, `.linkbtn`, `td.hit` | **fixed** | five rules appearing only in the stylesheet, deleted |
| section count | 10 | 9 | **keep** | LiitLLM has a training-run section TAB has no equivalent of |
| interactive widget | live code-switch scorer, typed into | recorded replay of a real run | **keep** | ADR 0004: receipts never leave the machine, so the page shows a recording rather than an upload box |
| "This project" links | 3 | 4 | **keep** | TAB has a live app *and* ADRs worth linking |
| `.meter` internals | `.bar-track` + `.bar-fill` | `.meter` + a span | **keep** | one element fewer for the same picture; the old pair are the deleted dead rules |
| palette | two accents, clay and tide | one accent plus greys | **keep** | TAB's portfolio row is a single colour; the stacked chart separates on lightness instead of hue because of it |
| `readout` / `m-tl` / `m-en` | scorer meters | absent | **keep** | those belong to LiitLLM's widget, which TAB has no counterpart for |
