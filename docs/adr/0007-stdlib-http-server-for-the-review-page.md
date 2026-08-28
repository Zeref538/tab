# 0007 — The review page is served by the standard library

Date: 2026-08-28
Status: accepted

Supersedes the component note in [TDD §3](../TDD.md) that said to copy
`YODA/yoda/web.py`.

## Context

The review screen is the one place a person touches TAB. It needs to list the
queue, show one receipt with its image, take an edit, and commit a row. Five
endpoints, one page, one user, bound to `127.0.0.1`.

The TDD said to reuse the FastAPI setup already working in YODA. That is a
reasonable default — it is proven and familiar. But it was written before
anyone counted what it costs here:

```
pip install --dry-run --ignore-installed fastapi uvicorn python-multipart
# Would install annotated-doc annotated-types anyio click fastapi h11 idna
#   pydantic pydantic_core python-multipart starlette typing-inspection
#   typing_extensions uvicorn
```

Fourteen packages. TAB currently has two.

Against that, `http.server` has been in the standard library forever,
`ThreadingHTTPServer` handles a browser fetching a page and a few JSON calls,
and `json` parses a request body in one line.

## Options

- **FastAPI and uvicorn**, as the TDD said. Async, automatic validation,
  generated API docs, and a familiar shape. None of which this page needs, and
  fourteen packages is a permanent supply-chain surface for a local tool whose
  selling point is that it costs nothing and sends nothing anywhere.
- **A framework somewhere in between** — Flask, Bottle. Fewer packages, same
  question: what does it do that ninety lines of `http.server` does not.
- **`http.server` from the standard library.**

## Decision

**`http.server.ThreadingHTTPServer` with a small hand-written router.**

Bound to `127.0.0.1` only. One static HTML file, served from `tab/static/`. A
handful of JSON endpoints. Requests are parsed with `json.loads`, and every
field that reaches the database goes through the same `normalise()` the
extractor output goes through, so a hand-typed amount is parsed by exactly the
code that parses a model-read one.

## Consequences

- TAB keeps a two-package dependency list, which is part of the story rather
  than an accident: a tool that claims to run for nothing should not pull in
  fourteen packages to draw one page.
- **No automatic request validation**, which FastAPI would have given free. So
  input handling is explicit: unknown fields are ignored rather than written,
  amounts are re-parsed rather than trusted, and the receipt id is looked up
  before anything is changed. That is a trust boundary and it does not get
  simplified away.
- **No async.** `ThreadingHTTPServer` gives a thread per request, which is
  ample for one person clicking through a queue and would not be for anything
  public. This page is never public — see
  [0004](0004-local-only-public-page-is-a-replay.md).
- Testing gets simpler, not harder: the handler is exercised over a real socket
  against a real server on an ephemeral port, with `urllib` from the same
  standard library.
- **If the review screen ever needs authentication, file uploads through the
  browser, or more than one concurrent user, this decision should be revisited**
  with a new ADR. Those are the three things that would make a framework worth
  its weight. Wanting nicer route decorators is not.
