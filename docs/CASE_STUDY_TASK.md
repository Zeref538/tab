# Task: add a case-study page - TAB - Tally All Bills

Paste this file's path into a fresh Claude Code session opened in this folder,
or say "follow docs/CASE_STUDY_TASK.md". It adds a case-study page in John's
shared design, then cleans up the project.

## Where the page goes

**TAB already has a page: `docs/index.html` ("TAB - receipts that
check their own arithmetic"), served by GitHub Pages from `docs/`.** Read it
first. If it is already a case study, this task becomes a RESTYLE of that page
onto the LiitLLM template, not a second page. Do not ship two competing
write-ups. If it is only a landing page, add `docs/case-study.html` and link
both ways.

## The story this page tells

**The idea is that TAB never trusts the model's confidence, it checks the
arithmetic.** Show one real receipt where the model misread a number and the
arithmetic caught it. Then the evaluation on 100 real Philippine receipts.

## Where the facts are

`README.md`, the commit "What 100 real Philippine receipts say about TAB" (`git log --grep "100 real"`), `results/`, `docs/PRD.md`, `docs/TDD.md`, `docs/adr/`.

## Traps specific to this project

- **The README is stale:** it says the folder watcher is not built, but
  `tab/watch.py` exists and its 10 tests pass. Fix the README in the same commit.
- Receipts can carry names, card digits and addresses. Any receipt image on the
  page must be one you are allowed to publish, with personal details covered.
- `build/` and `tab_agent.egg-info/` are build output. They are junk, not source.

## Read these first, fully, before changing anything

1. `C:\Users\johna\OneDrive\Documents\Portfolio\BRAND.md` - the spec, including
   the "Tried and rejected" list.
2. `C:\Users\johna\OneDrive\Documents\Portfolio\LiitLLM\docs\template.html` -
   the reference build.
3. Live reference: https://zeref538.github.io/liitllm/
4. This project's README and every file named under "Where the facts are" above.

## Part 1: the page

- Copy LiitLLM's `template.html` structure, CSS and scripts, then fill it with
  THIS project's content. Do not redesign from scratch and do not bring back
  anything on the rejected list.
- Copy the `fonts` folder (Schibsted Grotesk, Newsreader, Sora and the OFL
  licence files) and `docs/img/john.jpg` from LiitLLM, into the folder the
  page is served from.
- **Every number, chart and claim must come from this project's own files.**
  Do not invent results. If a LiitLLM section has no match here, drop it. If
  this project has something LiitLLM lacks, fit it into the same card style.
- **Charts are generated, not typed.** Build each figure with a committed script
  that reads committed result files, so re-running the script rebuilds it.
- Pick ONE project colour (not clay, and not a colour another project's page
  already uses - check BRAND.md). Use it wherever LiitLLM uses `--clay`, and run
  the dataviz palette validator on light and dark before using it. Add it to
  BRAND.md's colour table.
- The hero card fits one laptop screen (1366x768). The contents rail numbers
  match the number of sections.
- Keep the Simple / Technical toggle, and write both versions of every text.
- No em dashes anywhere in the copy.
- Link the page from the README (near the top) and from the live app if the app
  has a footer or about area.

## Part 2: clean up what is no longer used

- **Tracked files:** find scripts, configs, notes, old results and assets that
  nothing references any more. Grep for every file name before calling it
  unused. Remove them with `git rm` in their own commit, so they stay
  recoverable from history. Keep anything the README, tests, notebooks or
  pipeline still point to.
- **Page code:** remove CSS rules and JS for classes and ids that no longer
  appear in the HTML. Check `git diff` afterwards to confirm only dead rules went.
- **Junk:** `__pycache__`, `.pytest_cache`, old logs, your own screenshots and
  preview pages.
- **Big untracked files** (checkpoints, datasets, staging or upload folders): do
  NOT delete them yourself. List each one with its size, say whether it is safe
  to delete and why (rebuildable? a backup copy? the only copy?), and give John
  the exact PowerShell commands to delete the safe ones. He runs them.
- After cleanup, run the tests and rebuild the app and the page to prove
  nothing broke.

## Before saying it is done

- Screenshots at 1440x900, 1366x768, 768px and 390px, in light and dark.
- No sideways scroll (`scrollWidth` equals window width) and no console errors.
- **The live app still works** - load it locally and use its main feature once.
- Give John a localhost link to preview.
- Commit locally. Do NOT push until John says "push".
- Then run the `audit-site` skill; its model case-study list (items 75-86)
  applies to this page even though no language model is involved.
