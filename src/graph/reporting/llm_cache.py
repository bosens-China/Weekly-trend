"""报告工作流的 LLM 输出缓存与失效规则。"""

import json
from typing import Literal, TypedDict, cast

from cache import JsonCache, make_key
from llm import get_llm_settings

CacheStage = Literal["analyze_project", "organize_report", "generate_overview"]

# Prompt 已参与 key；此版本用于输出契约或缓存记录结构发生变化时强制整体失效。
LLM_CACHE_SCHEMA_VERSION = "report-llm:v1"


class CacheWrite(TypedDict):
    """一条待批量写入的 LLM 缓存记录。"""

    stage: CacheStage
    system_prompt: str
    user_content: str
    temperature: float
    output: dict


class ProjectCacheRef(TypedDict):
    """一个项目在当前 Prompt、模型和输入下的唯一缓存引用。"""

    key: str
    repo: str
    part_total: int
    model: str
    prompt_hash: str
    input_hash: str


class ProjectPartsWrite(TypedDict):
    """一个 LLM 批次对某项目新增的分片分析结果。"""

    ref: ProjectCacheRef
    parts: list[dict]


def build_llm_cache_key(
    stage: CacheStage,
    system_prompt: str,
    user_content: str,
    temperature: float,
) -> str:
    """生成会随阶段、Prompt、模型参数和输入自动变化的缓存 key。"""
    settings = get_llm_settings(temperature)
    model_identity = json.dumps(
        settings,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return make_key(
        LLM_CACHE_SCHEMA_VERSION,
        stage,
        model_identity,
        make_key(system_prompt),
        make_key(user_content),
    )


class LlmOutputCache:
    """只保存解析成功的报告 LLM JSON 输出。"""

    def __init__(self, store: JsonCache | None = None):
        self._store = store or JsonCache("llm_outputs")

    def get(
        self,
        stage: CacheStage,
        system_prompt: str,
        user_content: str,
        temperature: float,
    ) -> dict | None:
        key = build_llm_cache_key(
            stage,
            system_prompt,
            user_content,
            temperature,
        )
        record = self._store.get(key)
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != LLM_CACHE_SCHEMA_VERSION
            or record.get("stage") != stage
            or not isinstance(record.get("output"), dict)
        ):
            return None
        return cast(dict, record["output"])

    def set(
        self,
        stage: CacheStage,
        system_prompt: str,
        user_content: str,
        temperature: float,
        output: dict,
    ) -> None:
        self.set_many(
            [
                {
                    "stage": stage,
                    "system_prompt": system_prompt,
                    "user_content": user_content,
                    "temperature": temperature,
                    "output": output,
                }
            ]
        )

    def set_many(self, writes: list[CacheWrite]) -> None:
        """批量更新后只落盘一次，适合并发批次中的多项目结果。"""
        if not writes:
            return
        values: dict[str, dict] = {}
        for write in writes:
            settings = get_llm_settings(write["temperature"])
            key = build_llm_cache_key(
                write["stage"],
                write["system_prompt"],
                write["user_content"],
                write["temperature"],
            )
            values[key] = {
                "schema_version": LLM_CACHE_SCHEMA_VERSION,
                "stage": write["stage"],
                "model": settings["model"],
                "prompt_hash": make_key(write["system_prompt"]),
                "input_hash": make_key(write["user_content"]),
                "output": write["output"],
            }
        # 每批成功调用后立即持久化，避免后续节点失败导致本次 LLM 成本无法复用。
        self._store.set_many_and_save(values)

    def project_ref(
        self,
        repo: str,
        system_prompt: str,
        project_content: str,
        temperature: float,
        part_total: int,
    ) -> ProjectCacheRef:
        """创建项目级缓存引用；同一项目只对应一个顶层缓存 key。"""
        settings = get_llm_settings(temperature)
        return {
            "key": build_llm_cache_key(
                "analyze_project",
                system_prompt,
                project_content,
                temperature,
            ),
            "repo": repo,
            "part_total": part_total,
            "model": settings["model"],
            "prompt_hash": make_key(system_prompt),
            "input_hash": make_key(project_content),
        }

    def get_project_parts(self, ref: ProjectCacheRef) -> dict[int, dict]:
        """读取项目记录中已完成的分片；完整项目可直接跳过 LLM。"""
        record = self._store.get(ref["key"])
        if not _same_project_record(record, ref):
            return {}
        assert isinstance(record, dict)
        output = record.get("output", {})
        if not isinstance(output, dict):
            return {}
        raw_parts = output.get("parts", {})
        if not isinstance(raw_parts, dict):
            return {}
        parts: dict[int, dict] = {}
        for raw_index, part in raw_parts.items():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 1 <= index <= ref["part_total"] and isinstance(part, dict):
                parts[index] = cast(dict, part)
        return parts

    def merge_project_parts(self, writes: list[ProjectPartsWrite]) -> None:
        """一批 LLM 结束后，将涉及项目的分片合并并只原子落盘一次。"""
        updates: dict[str, dict] = {}
        for write in writes:
            ref = write["ref"]
            parts = {
                str(part["part_index"]): part
                for part in write["parts"]
                if isinstance(part.get("part_index"), int)
            }
            if not parts:
                continue
            existing = updates.get(ref["key"])
            if existing:
                existing["output"]["parts"].update(parts)
                continue
            updates[ref["key"]] = _project_record(ref, parts)
        self._store.merge_many_and_save(updates, _merge_project_record)


def _project_record(ref: ProjectCacheRef, parts: dict[str, dict]) -> dict:
    """构造单个项目的缓存记录。"""
    return {
        "schema_version": LLM_CACHE_SCHEMA_VERSION,
        "stage": "analyze_project",
        "model": ref["model"],
        "prompt_hash": ref["prompt_hash"],
        "input_hash": ref["input_hash"],
        "output": {
            "repo": ref["repo"],
            "part_total": ref["part_total"],
            "complete": len(parts) >= ref["part_total"],
            "parts": parts,
        },
    }


def _same_project_record(record: object, ref: ProjectCacheRef) -> bool:
    """判断已有记录是否确实属于同一个项目输入。"""
    if not isinstance(record, dict):
        return False
    output = record.get("output")
    return (
        record.get("schema_version") == LLM_CACHE_SCHEMA_VERSION
        and record.get("stage") == "analyze_project"
        and record.get("model") == ref["model"]
        and record.get("prompt_hash") == ref["prompt_hash"]
        and record.get("input_hash") == ref["input_hash"]
        and isinstance(output, dict)
        and output.get("repo") == ref["repo"]
        and output.get("part_total") == ref["part_total"]
    )


def _merge_project_record(current: object, incoming: object) -> dict:
    """在 JsonCache 锁内合并同一项目由并发批次写入的不同分片。"""
    if not isinstance(incoming, dict):
        return {}
    incoming_output = incoming.get("output")
    if not isinstance(incoming_output, dict):
        return incoming
    if not isinstance(current, dict):
        return incoming
    same_identity = all(
        current.get(field) == incoming.get(field)
        for field in (
            "schema_version",
            "stage",
            "model",
            "prompt_hash",
            "input_hash",
        )
    )
    current_output = current.get("output")
    if (
        not same_identity
        or not isinstance(current_output, dict)
        or current_output.get("repo") != incoming_output.get("repo")
        or current_output.get("part_total") != incoming_output.get("part_total")
    ):
        return incoming
    current_parts = current_output.get("parts", {})
    incoming_parts = incoming_output.get("parts", {})
    merged_parts = {
        **(current_parts if isinstance(current_parts, dict) else {}),
        **(incoming_parts if isinstance(incoming_parts, dict) else {}),
    }
    part_total = int(incoming_output.get("part_total") or 0)
    return {
        **incoming,
        "output": {
            **incoming_output,
            "complete": len(merged_parts) >= part_total,
            "parts": merged_parts,
        },
    }
