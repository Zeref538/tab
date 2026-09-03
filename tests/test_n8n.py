"""The n8n workflow shipped in n8n/.

A workflow file is easy to write and easy to get subtly wrong: a connection that
names a node which was renamed, a Switch whose second output nothing is wired to,
a node type with a typo. n8n only complains about those at import time, on
somebody else's machine, which is a bad place to find out.

What this does NOT check: that the Gmail, Sheets and Slack nodes work. They need
credentials nobody should put in a repo. Their shape is checked; their behaviour
is not, and the README says so.

Run: pytest tests/test_n8n.py -q      (or: python tests/test_n8n.py)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORKFLOW = ROOT / "n8n" / "tab-receipt-check.json"
SMOKE = ROOT / "n8n" / "tab-smoke-test.json"


def flow() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def test_it_is_the_shape_n8n_imports():
    data = flow()
    for key in ("name", "nodes", "connections"):
        assert key in data, f"a workflow needs {key!r}"
    assert data["nodes"], "a workflow with no nodes imports as an empty canvas"
    for node in data["nodes"]:
        for key in ("name", "type", "typeVersion", "position", "parameters"):
            assert key in node, f"{node.get('name', '?')} is missing {key!r}"
        assert node["type"].startswith("n8n-nodes-base."), node["type"]
        assert len(node["position"]) == 2


def test_every_connection_names_a_node_that_exists():
    """The failure this catches: renaming a node and leaving the wiring behind.
    n8n imports it happily and the branch silently never runs."""
    data = flow()
    names = {n["name"] for n in data["nodes"]}
    for source, outputs in data["connections"].items():
        assert source in names, f"connection from unknown node {source!r}"
        for branch in outputs.get("main", []):
            for link in branch:
                assert link["node"] in names, f"{source} wires to unknown {link['node']!r}"


def test_the_http_node_posts_a_file_to_the_check_endpoint():
    node = next(n for n in flow()["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    p = node["parameters"]
    assert p["method"] == "POST"
    assert "/api/check" in p["url"], p["url"]
    # Raw bytes, not a form. This is the shape tab.demo documents and the shape
    # tests/test_demo.py exercises over a socket.
    assert p["contentType"] == "binaryData"
    assert p["inputDataFieldName"], "the binary field to send has to be named"
    headers = p["headerParameters"]["parameters"]
    assert any(h["name"].lower() == "x-filename" for h in headers), (
        "TAB routes on the file extension, so the filename has to travel with it")
    # One unreadable attachment must not kill the whole run.
    assert p["options"]["response"]["response"]["neverError"] is True


def test_it_branches_on_the_verdict_and_never_on_a_confidence_score():
    """The heart of it. Routing on a model's self-reported certainty is exactly
    the thing ADR 0003 exists to prevent, and a workflow that did it would
    quietly undo the whole design."""
    data = flow()
    switch = next(n for n in data["nodes"] if n["type"] == "n8n-nodes-base.switch")
    rules = switch["parameters"]["rules"]["values"]
    assert len(rules) == 2, "one branch that files, one that asks a person"

    tested = set()
    for rule in rules:
        for cond in rule["conditions"]["conditions"]:
            tested.add(cond["leftValue"])
    assert tested == {"={{ $json.verdict }}"}, tested

    # Only the executable half. The notes on these nodes explain *why* not to
    # route on confidence, so scanning the whole file flags its own explanation.
    logic = json.dumps([n["parameters"] for n in data["nodes"]]).lower()
    for forbidden in ("confidence", "score", "probability", "certainty"):
        assert forbidden not in logic, (
            f"{forbidden!r} is used in the workflow logic; branch on verdict instead")


def test_both_switch_outputs_are_wired_to_something():
    """A Switch with a dead second output looks fine on the canvas and silently
    drops every receipt that needed a person - the exact failure TAB exists to
    prevent, reintroduced one layer up."""
    data = flow()
    switch = next(n for n in data["nodes"] if n["type"] == "n8n-nodes-base.switch")
    outputs = data["connections"][switch["name"]]["main"]
    assert len(outputs) == 2, f"{len(outputs)} branches wired, expected 2"
    for i, branch in enumerate(outputs):
        assert branch, f"switch output {i} goes nowhere"


def test_money_is_divided_by_100_exactly_where_a_person_reads_it():
    """Amounts cross the wire as whole centavos. Every place the workflow shows
    one to a human has to convert, and nowhere else should do arithmetic on it."""
    data = flow()
    sheets = next(n for n in data["nodes"] if n["type"] == "n8n-nodes-base.googleSheets")
    mapped = sheets["parameters"]["columns"]["value"]
    assert "/ 100" in mapped["total"], mapped["total"]
    assert "/ 100" in mapped["vat"], mapped["vat"]


def test_the_url_is_a_plain_one_that_works_on_import():
    """This started as `{{ $env.TAB_URL }}`, which reads nicely and does not run.

    n8n blocks environment access inside nodes unless
    N8N_BLOCK_ENV_ACCESS_IN_NODE=false, so an imported workflow using $env fails
    with "access to env vars denied" on a default install. Found by executing
    it, not by reading it.
    """
    for path in (WORKFLOW, SMOKE):
        node = next(n for n in json.loads(path.read_text(encoding="utf-8"))["nodes"]
                    if n["type"] == "n8n-nodes-base.httpRequest")
        url = node["parameters"]["url"]
        assert "$env" not in url, f"{path.name}: $env is blocked by default in n8n"
        assert url.startswith("http"), url
        assert url.endswith("/api/check"), url


def test_both_workflows_carry_an_id_so_n8n_will_import_them():
    """Without a top-level id the CLI importer dies on
    `NOT NULL constraint failed: workflow_entity.id`. A workflow exported from
    n8n has one; a hand-written file does not unless you remember."""
    for path in (WORKFLOW, SMOKE):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("id"), f"{path.name} has no id"


def test_the_smoke_test_needs_no_credentials():
    """It exists so somebody can prove their TAB is reachable before wiring up
    Gmail. A node needing credentials in it would defeat that."""
    data = json.loads(SMOKE.read_text(encoding="utf-8"))
    types = {n["type"] for n in data["nodes"]}
    for needs_auth in ("gmailTrigger", "googleSheets", "slack"):
        assert f"n8n-nodes-base.{needs_auth}" not in types, needs_auth
    assert "n8n-nodes-base.manualTrigger" in types


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and name != "flow":
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
