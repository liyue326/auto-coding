"""修复经验向量库（Chroma）：仅积累成功修复案例，供 BugFix RAG 检索。"""
from memory.ingest import ingest_successful_run
from memory.retrieve import format_hints_for_prompt, retrieve_similar_fixes

__all__ = [
    "ingest_successful_run",
    "retrieve_similar_fixes",
    "format_hints_for_prompt",
]
