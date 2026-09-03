"""Everything TAB imports has to be declared, and everything it ships has to ship.

This project has now shipped the same bug twice.

`pymupdf` was imported by three modules and missing from `dependencies` for a
week. `onnxruntime` is needed by the OCR route and rapidocr 3.x deliberately
declares no inference engine, so it was missing from the `ocr` extra. Both ran
fine here, because both were already installed on this machine, and both would
have died on the first fresh install.

The pattern is the same every time: it works because of something sitting on
the developer's disk that is not written down anywhere.

Run: pytest tests/test_packaging.py -q     (or: python tests/test_packaging.py)
"""

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PKG = ROOT / "tab"

# Modules that come with Python. Anything imported and not in here has to be
# declared, or it is a dependency somebody has and nobody wrote down.
STDLIB = set(sys.stdlib_module_names)

# What a distribution is called on PyPI is not always what you import.
IMPORT_TO_DISTRIBUTION = {
    "PIL": "pillow",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
}

# Imported behind a try/except with a real message, and installed by an extra
# rather than the core. They are checked against the extras instead.
OPTIONAL = {"rapidocr"}


def declared() -> tuple[set[str], set[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    def names(specs):
        out = set()
        for spec in specs:
            name = spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0]
            out.add(name.strip().lower().replace("_", "-"))
        return out

    core = names(project.get("dependencies", []))
    extra = set()
    for group in project.get("optional-dependencies", {}).values():
        extra |= names(group)
    return core, extra


def imported() -> dict[str, set[str]]:
    """Top-level module name -> the files that import it."""
    found: dict[str, set[str]] = {}
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # `from . import x` has no module; relative imports are ours.
                mods = [node.module] if node.module and node.level == 0 else []
            else:
                continue
            for mod in mods:
                top = mod.split(".")[0]
                if top in STDLIB or top == "tab":
                    continue
                found.setdefault(top, set()).add(path.name)
    return found


def test_every_third_party_import_is_declared():
    core, extra = declared()
    missing = []
    for module, files in sorted(imported().items()):
        dist = IMPORT_TO_DISTRIBUTION.get(module, module).lower().replace("_", "-")
        if dist in core or dist in extra:
            continue
        missing.append(f"{module} (imported by {', '.join(sorted(files))})")
    assert not missing, (
        "imported but not in pyproject.toml — this works here only because it is "
        "already installed:\n  " + "\n  ".join(missing))


def test_the_ocr_extra_names_an_inference_engine():
    """rapidocr 3.x supports onnxruntime, paddle, torch and openvino, and
    declares none of them, so installing rapidocr alone gives you a package that
    imports and then raises `onnxruntime is not installed` at the first
    receipt."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ocr = " ".join(data["project"]["optional-dependencies"]["ocr"]).lower()
    assert "rapidocr" in ocr
    engines = ("onnxruntime", "paddlepaddle", "torch", "openvino")
    assert any(e in ocr for e in engines), (
        f"the ocr extra installs rapidocr with no engine; add one of {engines}")


def test_what_the_demo_serves_is_declared_as_package_data():
    """These are not .py files, so setuptools leaves them out unless told. The
    failure mode is nasty: perfect in an editable install, and a 500 for the
    page plus an empty sample list once it is deployed."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["tab"]
    assert any("static" in p for p in patterns), patterns
    assert any("samples" in p for p in patterns), patterns

    # And the files those patterns are for actually exist.
    assert (PKG / "static" / "demo.html").exists()
    assert list((PKG / "samples").glob("*.pdf")), "no sample receipts on disk"


def test_the_demo_has_a_console_script_for_the_host_to_start():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts.get("tab-demo") == "tab.demo:main", scripts

    # render.yaml has to actually use it, or the blueprint starts nothing.
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "tab-demo" in render
    assert "0.0.0.0" in render, "binding to localhost on a host answers nobody"
    assert "/api/health" in render, "no health check means a dead box looks alive"


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
