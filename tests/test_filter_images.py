"""验证带点号的仓库名不会导致候选图片文件互相覆盖。"""

import sys
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from graph.nodes.filter_images import _download_one  # noqa: E402
from graph.state import ImageCandidate  # noqa: E402


class FilterImagesTests(unittest.TestCase):
    def test_dotted_repo_keeps_distinct_image_paths_and_contents(self) -> None:
        images: dict[str, bytes] = {}
        for index, color in enumerate(("red", "blue")):
            content = BytesIO()
            Image.new("RGB", (64, 64), color).save(content, format="BMP")
            images[f"/{index}.bmp"] = content.getvalue()

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/bmp"},
                content=images[request.url.path],
            )

        with (
            TemporaryDirectory() as temp_dir,
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
        ):
            for index in (0, 1):
                candidate: ImageCandidate = {
                    "url": f"https://images.test/{index}.bmp",
                    "alt": "demo",
                    "context": "",
                    "index": index + 1,
                }
                result = _download_one(
                    client,
                    (0, candidate, Path(temp_dir) / f"acme__next.js__{index}"),
                )
                assert result is not None
                self.assertEqual(result.path.name, f"acme__next.js__{index}.bmp")
            for index in (0, 1):
                self.assertEqual(
                    (Path(temp_dir) / f"acme__next.js__{index}.bmp").read_bytes(),
                    images[f"/{index}.bmp"],
                )


if __name__ == "__main__":
    unittest.main()
