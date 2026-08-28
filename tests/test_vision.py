"""Image preparation, tested without calling a model.

The resize rule earned a test the hard way: a 3024x4096 receipt photo produced
more tokens than any context window could hold, and Ollama did not refuse it
politely - the model runner crashed with a dropped connection, three times per
receipt, at roughly 80 seconds a go.

Run: pytest tests/test_vision.py -q      (or: python tests/test_vision.py)
"""

import io
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab.vision import prepare_image  # noqa: E402


def write_jpeg(tmp: Path, name: str, size: tuple[int, int]) -> Path:
    path = tmp / name
    Image.new("RGB", size, (250, 249, 246)).save(path, format="JPEG")
    return path


def test_small_image_is_passed_through_untouched(tmp_path):
    """Most receipts are already a sensible size. Re-encoding them would throw
    away detail for nothing, so they must come back byte-identical."""
    path = write_jpeg(tmp_path, "small.jpg", (864, 1296))
    data, meta = prepare_image(path)
    assert meta["resized"] is False
    assert data == path.read_bytes(), "untouched means untouched"


def test_oversized_image_is_scaled_to_the_cap(tmp_path):
    path = write_jpeg(tmp_path, "huge.jpg", (3024, 4096))
    data, meta = prepare_image(path)
    assert meta["resized"] is True
    assert meta["was"] == [3024, 4096]
    assert max(meta["size"]) == 1600, "long edge lands exactly on the cap"
    with Image.open(io.BytesIO(data)) as img:
        assert max(img.size) == 1600


def test_aspect_ratio_survives(tmp_path):
    """A squashed receipt is an unreadable receipt."""
    path = write_jpeg(tmp_path, "tall.jpg", (2000, 4000))
    _, meta = prepare_image(path)
    width, height = meta["size"]
    assert abs((width / height) - (2000 / 4000)) < 0.01


def test_exactly_at_the_cap_is_not_resized(tmp_path):
    path = write_jpeg(tmp_path, "edge.jpg", (1600, 1200))
    _, meta = prepare_image(path)
    assert meta["resized"] is False, "the cap is a limit, not a target"


def test_cap_is_adjustable(tmp_path):
    """It is a calibration knob. Real paper decides the value, not a guess."""
    path = write_jpeg(tmp_path, "any.jpg", (2000, 1000))
    _, meta = prepare_image(path, max_edge=800)
    assert max(meta["size"]) == 800


if __name__ == "__main__":
    import tempfile

    passed = 0
    with tempfile.TemporaryDirectory() as d:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                sub = Path(d) / name
                sub.mkdir()
                fn(sub)
                passed += 1
                print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
