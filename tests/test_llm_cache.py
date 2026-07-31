import json
import os
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cache import JsonCache  # noqa: E402
from graph.reporting.llm_cache import (  # noqa: E402
    LlmOutputCache,
    build_llm_cache_key,
)


class LlmOutputCacheTests(unittest.TestCase):
    def test_same_factors_hit_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = JsonCache("llm_outputs", directory=Path(temp_dir))
            cache = LlmOutputCache(store)
            output = {"items": [{"repo": "acme/tool"}]}

            cache.set("organize_report", "system", "input", 0.2, output)

            reloaded = LlmOutputCache(
                JsonCache("llm_outputs", directory=Path(temp_dir))
            )
            self.assertEqual(
                reloaded.get("organize_report", "system", "input", 0.2),
                output,
            )

    def test_project_uses_one_key_and_persists_after_each_batch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            cache = LlmOutputCache(JsonCache("llm_outputs", directory=directory))
            ref = cache.project_ref(
                "acme/tool",
                "system",
                "full project input",
                0.2,
                part_total=2,
            )
            first = {
                "repo": "acme/tool",
                "part_index": 1,
                "part_total": 2,
                "summary": "第一部分",
            }
            second = {
                "repo": "acme/tool",
                "part_index": 2,
                "part_total": 2,
                "summary": "第二部分",
            }

            cache.merge_project_parts([{"ref": ref, "parts": [first]}])
            after_first = json.loads(
                (directory / "llm_outputs.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(after_first), 1)
            self.assertEqual(set(cache.get_project_parts(ref)), {1})

            cache.merge_project_parts([{"ref": ref, "parts": [second]}])
            after_second = json.loads(
                (directory / "llm_outputs.json").read_text(encoding="utf-8")
            )

            self.assertEqual(len(after_second), 1)
            self.assertEqual(set(cache.get_project_parts(ref)), {1, 2})
            record = next(iter(after_second.values()))["value"]
            self.assertTrue(record["output"]["complete"])

    def test_concurrent_batches_merge_parts_into_one_project_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            cache = LlmOutputCache(JsonCache("llm_outputs", directory=directory))
            ref = cache.project_ref(
                "acme/large",
                "system",
                "full large project input",
                0.2,
                part_total=2,
            )
            parts = [
                {
                    "repo": "acme/large",
                    "part_index": index,
                    "part_total": 2,
                    "summary": f"第 {index} 部分",
                }
                for index in (1, 2)
            ]

            with ThreadPoolExecutor(max_workers=2) as pool:
                list(
                    pool.map(
                        lambda part: cache.merge_project_parts(
                            [{"ref": ref, "parts": [part]}]
                        ),
                        parts,
                    )
                )

            raw = json.loads(
                (directory / "llm_outputs.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(raw), 1)
            self.assertEqual(set(cache.get_project_parts(ref)), {1, 2})

    def test_prompt_model_input_and_temperature_invalidate_cache(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_MODEL": "model-a", "OPENAI_BASE_URL": "https://api-a.test"},
        ):
            original = build_llm_cache_key(
                "organize_report",
                "prompt-a",
                "input-a",
                0.2,
            )
            changed_prompt = build_llm_cache_key(
                "organize_report",
                "prompt-b",
                "input-a",
                0.2,
            )
            changed_input = build_llm_cache_key(
                "organize_report",
                "prompt-a",
                "input-b",
                0.2,
            )
            changed_temperature = build_llm_cache_key(
                "organize_report",
                "prompt-a",
                "input-a",
                0.3,
            )
        with patch.dict(
            os.environ,
            {"OPENAI_MODEL": "model-b", "OPENAI_BASE_URL": "https://api-a.test"},
        ):
            changed_model = build_llm_cache_key(
                "organize_report",
                "prompt-a",
                "input-a",
                0.2,
            )
        with patch.dict(
            os.environ,
            {"OPENAI_MODEL": "model-a", "OPENAI_BASE_URL": "https://api-b.test"},
        ):
            changed_base_url = build_llm_cache_key(
                "organize_report",
                "prompt-a",
                "input-a",
                0.2,
            )

        self.assertEqual(
            len(
                {
                    original,
                    changed_prompt,
                    changed_input,
                    changed_temperature,
                    changed_model,
                    changed_base_url,
                }
            ),
            6,
        )

    def test_entry_expires_after_30_days(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            cache = LlmOutputCache(JsonCache("llm_outputs", directory=directory))
            cache.set(
                "generate_overview",
                "system",
                "input",
                0.2,
                {"overview": "测试导语"},
            )

            path = directory / "llm_outputs.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            for entry in raw.values():
                entry["ts"] = time.time() - 31 * 86400
            path.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"CACHE_TTL_DAYS": "30"}):
                expired = LlmOutputCache(JsonCache("llm_outputs", directory=directory))

            self.assertIsNone(expired.get("generate_overview", "system", "input", 0.2))


if __name__ == "__main__":
    unittest.main()
