"""老项目：隔离工作区、索引、Project Analyst、安全导出。"""
from legacy.analyst import (
    build_analyst_report,
    collect_code_samples,
    format_report_for_planner,
    merge_llm_analysis,
)
from legacy.indexer import build_project_index
from legacy.files import (
    apply_requirement_on_baseline,
    coalesce_with_baseline,
    format_existing_files_block,
    infer_touch_paths,
    load_source_files,
    parse_existing_files_from_prompt,
    preserves_baseline,
    wants_modify_existing,
)
from legacy.repair import repair_nested_merge_dirs
from legacy.workspace import (
    build_export_package,
    export_to_legacy,
    format_legacy_context,
    prepare_legacy_workspace,
)

__all__ = [
    "prepare_legacy_workspace",
    "build_project_index",
    "build_analyst_report",
    "collect_code_samples",
    "merge_llm_analysis",
    "format_report_for_planner",
    "format_legacy_context",
    "build_export_package",
    "export_to_legacy",
    "repair_nested_merge_dirs",
    "infer_touch_paths",
    "load_source_files",
    "wants_modify_existing",
    "format_existing_files_block",
    "coalesce_with_baseline",
    "apply_requirement_on_baseline",
    "preserves_baseline",
    "parse_existing_files_from_prompt",
]
