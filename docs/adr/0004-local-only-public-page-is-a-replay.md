# 0004 — Processing is local; the public page is a replay

Date: 2026-08-28
Status: accepted

## Context

The brief asked for a website. There are two different things that could mean,
and they pull in opposite directions.

A receipt is not a neutral document. It carries the last four digits of a card,
a name, a billing address, a location, a timestamp, and sometimes a pharmacy
line item that reveals a medical condition. Uploading a folder of them to a
server is a meaningful act, and most people who would use this tool have not
thought about that at the moment they drag the folder in.

At the same time, the portfolio needs a page. A hiring reader has thirty seconds
and will not install a Python package to find out whether this works.

## Options

- **A hosted web app with an uploader.** Best demo, one URL, works on a phone.
  It also means every user receipt lands on a server, which contradicts the
  privacy claim that is half the reason this project is interesting. It adds
  hosting cost, and it puts the author in custody of other people financial
  records.
- **Local app only, no public page.** Honest and invisible. The project would be
  judged by its README.
- **Local app as the product; a static replay as the public page.**

## Decision

**Two surfaces, and only one of them touches a receipt.**

The **product** is a local web app: FastAPI bound to `127.0.0.1`, serving one
page, talking to a local model through Ollama. It works with the network cable
out. Nothing is uploaded because there is nowhere for it to go.

The **public page** is static. It replays one real run from committed logs — a
receipt appears, a row builds, one field lights up as flagged — and shows the
scoreboard underneath. It contains no model, no uploader, and no receipt that
did not come from the authored evaluation set.

## Consequences

- The privacy claim is structural rather than a promise. There is no server to
  trust, which is a much stronger statement than a policy saying the server can
  be trusted.
- **The public page cannot disagree with the study**, because it renders the same
  committed logs and the same generated scoreboard JSON that the evaluation
  produces. A hand-edited number on that page is a bug, not a typo.
- The demo is less impressive than a live uploader, and that is the accepted
  cost. This is the same trade ABIDE made in its own
  ADR 0004 — a replay that cannot lie beats a live demo that can.
- Anything that ever sends data outward — a Google Sheets export, a cloud
  extraction route — is opt-in, off by default, and announced in words at the
  moment it is switched on, not in a settings page nobody opens.
- Screenshots for the portfolio come from the local app, which means they show
  real behaviour rather than a mock.
