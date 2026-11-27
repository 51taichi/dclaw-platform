"""Resolve text bindings against connected nodes in an authorized canvas."""

import re


class PromptBindingError(ValueError):
    pass


def resolve_prompt(canvas: dict, node_id: str, prompt: str) -> str:
    nodes = canvas.get("nodes", [])
    edges = canvas.get("edges", [])

    def expand(target, text, visited):
        if "${" not in text:
            return text
        if len(visited) > len(nodes):
            raise PromptBindingError("提示词引用存在循环，请检查节点连线。")

        def replace(match):
            expression = match.group(1)
            if not expression.endswith(".text"):
                raise PromptBindingError("提示词引用仅支持已连接节点的 text 字段。")
            name = expression[:-5]
            sources = {
                e.get("source")
                for e in edges
                if e.get("target") == target
                and (e.get("data") or {}).get("role", "prompt") == "prompt"
            }
            found = [
                n
                for n in nodes
                if n.get("id") in sources
                and (
                    n.get("id") == name
                    or n.get("data", {}).get("workflowLogicalNodeId") == name
                )
            ]
            if len(found) != 1:
                raise PromptBindingError(
                    f"提示词引用 {name} 无法唯一对应已连接的上游文本节点。"
                )
            source = found[0]
            data = source.get("data", {})
            if source["id"] in visited:
                raise PromptBindingError("提示词引用存在循环，请检查节点连线。")
            if source.get("type") != "prompt" or data.get("job_status") in {
                "queued",
                "running",
                "failed",
                "cancelled",
            }:
                raise PromptBindingError(f"上游文本节点 {name} 尚未就绪。")
            value = data.get("text")
            if not isinstance(value, str) or not value.strip():
                raise PromptBindingError(f"上游文本节点 {name} 没有可用文本。")
            return expand(source["id"], value, visited | {source["id"]})

        result = re.sub(r"\$\{([^{}]+)\}", replace, text)
        if "${" in result:
            raise PromptBindingError("提示词中仍有未解析的节点引用，请检查引用格式。")
        return result

    return expand(node_id, prompt, {node_id})
