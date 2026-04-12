from __future__ import annotations


def build_no_evidence_message() -> str:
    return (
        "我在当前知识库中未检索到足够相关且可验证的内容，"
        "暂时无法确认该问题。请补充关键词或上传相关文档后再试。"
    )


def build_tool_failure_message() -> str:
    return "我尝试查询真实数据，但本次工具调用失败或超时，暂时无法给出可验证结论。"

