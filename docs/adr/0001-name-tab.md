# 0001 — The name is TAB

Date: 2026-08-28
Status: accepted

## Context

The project needed a name that survives being said out loud, typed as a command,
and read on a portfolio card by someone who has thirty seconds and no context.

Eight earlier candidates were rejected across previous rounds: Bantay, Ayos,
Ulat, Tally, Sundo, Kasama, Tindera, Repaso. Most were Filipino words that read
well locally but told an international reader nothing, and several collide with
existing products.

The tool also needs a command name and a place to be published. Checked on
2026-08-28, not assumed:

```
curl -s -o /dev/null -w "%{http_code}" https://pypi.org/pypi/tab/json        # 200 — taken
curl -s -o /dev/null -w "%{http_code}" https://pypi.org/pypi/tab-agent/json  # 404 — free
gh repo view Zeref538/tab                                                    # does not exist — free
```

So `tab` on PyPI is not available. `tab-agent` is, and it matches the
`yoda-agent` convention already used in this portfolio.

## Options

- **A Filipino word.** Warm and specific to the audience, and the source of every
  rejected candidate so far. The recurring problem is that a hiring reader in
  another country cannot pronounce it, guess it, or remember it.
- **A descriptive name** — ReceiptAgent, BillReader. Instantly clear and
  instantly forgettable, and it competes with a dozen products using the same
  two words.
- **TAB**, as a backronym with an idiom underneath it.

## Decision

**TAB — Tally All Bills.**

*Picking up the tab* is what you do at the end of a meal. This picks up the pile
of receipts instead. The idiom does the work: the expansion is a label, the
phrase is the memory.

Two alternate expansions are held in reserve if the plain one ever reads thin:
**T**ranscribe **A**nd **B**alance, which names the checking step and is the part
that actually makes this different, or **T**otals **A**utomatically **B**ooked.

## Consequences

- The GitHub repo is `tab`. The import package is `tab`. The CLI command is
  `tab`. Only the **distribution** name differs: `tab-agent` on PyPI, because
  `tab` is taken there. Users type `pip install tab-agent` once and `tab` from
  then on, which is the same split `yoda-agent` already lives with.
- The idiom is only obvious to English speakers. That is an accepted trade: the
  secondary audience — a hiring reader — is the one who needs the name to stick,
  and the primary user reaches the tool through a link, not by recalling a pun.
- The rejected list stays written down here so a future round does not
  rediscover Bantay and think it is new.
- If the name is ever changed, that is a new ADR superseding this one, not an
  edit to it.
