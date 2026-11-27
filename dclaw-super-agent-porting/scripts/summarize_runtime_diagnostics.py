#!/usr/bin/env python3
"""Summarize a saved, authorized DClaw runtime diagnostics receipt offline."""

import argparse
import hashlib
from itertools import groupby
import json
from pathlib import Path
import re
import sys


CONTRACT = "developer.runtime.diagnostics.read/1"
REFERENCE_CONTRACT = "developer.runtime.diagnostics.by-reference/1"
REFERENCE_CONTRACT_V2 = "developer.runtime.diagnostics.by-reference/2"
REFERENCE_CONTRACT_V3 = "developer.runtime.diagnostics.by-reference/3"
REFERENCE_CONTRACT_V4 = "developer.runtime.diagnostics.by-reference/4"
REFERENCE_CONTRACT_V5 = "developer.runtime.diagnostics.by-reference/5"
REFERENCE_CONTRACT_V6 = "developer.runtime.diagnostics.by-reference/6"
SEARCH_CONTRACT = "developer.runtime.diagnostics.search/1"
SAFE_TOKEN = re.compile(r"[A-Za-z0-9._:+/-]{1,128}\Z")
SUMMARY_FIELDS = {
    "contract", "status", "retention_days", "failures", "history_readback",
}
FAILURE_FIELDS = {
    "invocation_id", "installation_id", "release_id", "started_at", "failed_at",
    "first_failure", "first_failure_source", "error_code", "transaction_status",
    "message_status",
}


def _validate(value, definition, location):
    types = definition.get("type")
    if types:
        allowed = types if isinstance(types, list) else [types]
        matches = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: type(item) is int,
            "boolean": lambda item: type(item) is bool,
            "null": lambda item: item is None,
        }
        if not any(matches[kind](value) for kind in allowed):
            raise ValueError(f"{location} has the wrong type")
    if "const" in definition and value != definition["const"]:
        raise ValueError(f"{location} has the wrong constant")
    if "enum" in definition and value not in definition["enum"]:
        raise ValueError(f"{location} has an unknown value")
    if isinstance(value, dict):
        properties = definition.get("properties", {})
        for key in definition.get("required", []):
            if key not in value:
                raise ValueError(f"{location}.{key} is missing")
        if definition.get("additionalProperties") is False and value.keys() - properties.keys():
            raise ValueError(f"{location} has unexpected fields")
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], f"{location}.{key}")
    if isinstance(value, list):
        if "maxItems" in definition and len(value) > definition["maxItems"]:
            raise ValueError(f"{location} exceeds the official array limit")
        if definition.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise ValueError(f"{location} contains duplicate items")
        for index, item in enumerate(value):
            _validate(item, definition.get("items", {}), f"{location}[{index}]")
    if type(value) is int and "minimum" in definition and value < definition["minimum"]:
        raise ValueError(f"{location} is below the official minimum")


def validate_full_schema(value, schema):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError, ValidationError
    except ImportError as exc:
        raise ValueError(
            "local Python is missing jsonschema[format]>=4.20,<5; "
            "use the project-isolated environment described in references/python-environment.md "
            f"(interpreter: {sys.executable}); this is not a platform-contract error"
        ) from exc
    checker = FormatChecker()
    if checker.conforms("not-a-date", "date-time"):
        raise ValueError(
            "local jsonschema date-time validation is unavailable; "
            "check the project-isolated environment per references/python-environment.md "
            f"(interpreter: {sys.executable})"
        )
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=checker).validate(value)
    except (SchemaError, ValidationError) as exc:
        raise ValueError("diagnostics do not match the official Draft 2020-12 Schema") from exc


def validate_response(response, schema):
    properties = schema.get("properties", {})
    failures = properties.get("failures", {}).get("items", {})
    first_failure = failures.get("properties", {}).get("first_failure", {})
    history = properties.get("history_readback", {})
    if (properties.get("contract", {}).get("const") != CONTRACT
            or not SUMMARY_FIELDS <= set(schema.get("required", []))
            or not FAILURE_FIELDS <= set(failures.get("required", []))
            or not {"phase", "category", "attempt"} <= set(first_failure.get("required", []))
            or not {"messages_table_count", "agent_memory_count"} <= set(history.get("required", []))):
        raise ValueError("official DevKit schema does not describe developer diagnostics v1")
    _validate(response, schema, "diagnostics")


def validate_reference_response(response, schema):
    branches = schema.get("oneOf", [])
    if not isinstance(response, dict) or len(branches) != 2:
        raise ValueError("official DevKit schema does not describe reference diagnostics v1")
    status = response.get("status")
    matching = [branch for branch in branches
                if branch.get("properties", {}).get("status", {}).get("const") == status]
    if len(matching) != 1 or status not in ("found", "no_record"):
        raise ValueError("reference diagnostics has an unknown status")
    branch = matching[0]
    contract = branch.get("properties", {}).get("contract", {}).get("const")
    is_v6 = contract == REFERENCE_CONTRACT_V6
    if (contract not in (REFERENCE_CONTRACT, REFERENCE_CONTRACT_V2,
                         REFERENCE_CONTRACT_V3, REFERENCE_CONTRACT_V4,
                         REFERENCE_CONTRACT_V5, REFERENCE_CONTRACT_V6)
            or (is_v6 and status == "found" and not {
                "invocation_id", "runtime_evidence", "local_task_evidence",
                "release_id", "installation_id", "runtime_outcome",
                "transaction_status", "task_acceptance", "local_tasks",
                "diagnosis_status", "findings",
            } <= set(branch.get("required", [])))
            or (not is_v6 and status == "found" and not {
                "task_id", "invocation_id", "installation_id", "release_id",
                "transaction_status",
            } <= set(branch.get("required", [])))
            or (contract not in (REFERENCE_CONTRACT_V3, REFERENCE_CONTRACT_V6)
                and status == "found" and not {
                "first_failure", "first_failure_source", "stages",
            } <= set(branch.get("required", [])))
            or (contract == REFERENCE_CONTRACT_V2 and status == "found" and not {
                "failure_events", "final_blocker", "unrecorded_fields",
            } <= set(branch.get("required", [])))
            or (contract == REFERENCE_CONTRACT_V3 and status == "found" and not {
                "final_blocker", "host_failure_detail",
            } <= set(branch.get("required", [])))
            or (contract in (REFERENCE_CONTRACT_V4, REFERENCE_CONTRACT_V5)
                and status == "found" and not {
                "ended_at", "runtime_outcome", "task_acceptance", "task_evidence",
                "tasks", "host_operations", "stages",
            } <= set(branch.get("required", [])))
            or (contract == REFERENCE_CONTRACT_V5 and status == "found" and
                "blocker" not in branch.get("required", []))):
        raise ValueError("official DevKit schema does not describe reference diagnostics")
    _validate(response, branch, "reference diagnostics")
    if contract in (REFERENCE_CONTRACT_V3, REFERENCE_CONTRACT_V4,
                    REFERENCE_CONTRACT_V5, REFERENCE_CONTRACT_V6):
        validate_full_schema(response, schema)


def validate_search_response(response, schema):
    if (schema.get("properties", {}).get("contract", {}).get("const") != SEARCH_CONTRACT
            or not {"status", "retention_days", "failures", "has_more", "next_cursor"}
            <= set(schema.get("required", []))):
        raise ValueError("official DevKit schema does not describe diagnostic search")
    _validate(response, schema, "diagnostic search")
    validate_full_schema(response, schema)


def _token(value):
    if value is None:
        return "未记录"
    if isinstance(value, str) and SAFE_TOKEN.fullmatch(value):
        return value
    return "未展示（非安全标识）"


def _field_details(record):
    return "".join(
        f"；{label} `{_token(record[key])}`"
        for key, label in (("field_path", "field_path"),
                           ("constraint", "constraint"), ("contract", "contract"))
        if record.get(key) is not None
    )


def _array_limit_note(lines, name, count, definition):
    limit = definition.get("maxItems")
    if limit is not None and count == limit:
        lines.append(
            f"- {name}已达到正式 Schema 的 {limit} 条上限；回执可能截断，"
            "不能由此推断实际总次数。"
        )


def _next_step(failure):
    source = failure["first_failure_source"]
    first = failure["first_failure"]
    phase, category = first["phase"], first["category"]
    if source == "not_recorded" or phase is None or category is None:
        return "首错细分未记录。核对任务、Release 与诊断保留期；需要定位时由平台按 invocation 核查脱敏 trace，不能猜根因。"
    if source == "platform_preflight":
        return "先核对发布包声明、安装授权及目标正式合同；预检内部首错由平台按 invocation 核查并给出可复核回执。"
    if phase == "model_validation" and category == "json_parse":
        return "检查该 Release 的候选解析入口、agent_loop 输出合同和失败分支；用受控输入做本地复现。模型或工具原文不在本回执中，不能仅凭类别判定上游根因。"
    if phase == "model_validation" and category == "model_response_shape":
        return "检查该 Release 对模型可见内容块、空回复和输出形状的校验；核对正式可得的模型结束状态并做本地回归。缺模型回执时不要推定截断或 Host 故障。"
    return ("在该 Release 的代码和 trace 定义中定位记录的 phase/category，"
            "检查相应输入、校验与失败关闭路径；本回执不足以单独判定责任。")


def render_summary(response, schema, agent_id, task_id):
    validate_response(response, schema)
    lines = [
        "# DClaw 运行诊断摘要",
        "",
        f"- Agent：`{_token(agent_id)}`",
        f"- 任务：`{_token(task_id)}`",
        f"- 查询结果：`{response['status']}`；返回失败 {len(response['failures'])} 条；保留窗口 {response['retention_days']} 天，单次最多 {schema['properties']['failures']['maxItems']} 条。",
        "- 边界：这是当前授权查询返回的失败记录和历史计数，不含模型原文、完整 trace 或逐条消息状态。",
        "",
        "## 失败记录与下一步",
        "",
    ]
    if not response["failures"]:
        lines.append("未返回失败记录；这不能证明任务从未失败。先核对 Agent、任务、时间与保留窗口。")
    for index, failure in enumerate(response["failures"], 1):
        first = failure["first_failure"]
        lines += [
            f"### {index}. Invocation `{_token(failure['invocation_id'])}`",
            "",
            f"- Release：`{_token(failure['release_id'])}`；installation：`{_token(failure['installation_id'])}`。",
            f"- 时间：开始 `{_token(failure['started_at'])}`；失败 `{_token(failure['failed_at'])}`。",
            f"- 首错：来源 `{failure['first_failure_source']}`；phase `{_token(first['phase'])}`；category `{_token(first['category'])}`；attempt `{first['attempt'] if first['attempt'] is not None else '未记录'}`；error_code `{_token(failure['error_code'])}`。",
            f"- 事务：`{failure['transaction_status']}`；本次失败消息：`{failure['message_status']}`。",
            f"- 首错检查线索：{_next_step(failure)}",
            "- 归因边界：首错可能已被后续重试恢复；本回执未单列最终阻断阶段和类别，不能仅凭首错判定事务为何终止。",
            "",
        ]
    history = response["history_readback"]
    lines += [
        "## 历史与移交证据",
        "",
        f"- 查询时计数：messages table `{history['messages_table_count']}`；Agent memory `{history['agent_memory_count'] if history['agent_memory_count'] is not None else '未记录'}`。",
    ]
    if response["failures"]:
        lines += [
            "- `message_status=persisted` 仅描述对应失败提示；当前计数不能证明任何旧消息已恢复或永久丢失。若客户端显示异常，分别核对服务端写入、历史接口回读和客户端渲染。",
            "- 已有证据：上述 invocation、installation、Release、时间、首错来源与分类、事务和失败提示状态；保留原始 JSON 回执及其摘要。",
            "- 仅在证据指向平台合同或实现，或开发侧无法取得必要 trace 时，再由项目方决定是否移交。平台侧核查同一 invocation 的工具/Host 首错和消息链路；本摘要不是平台已接单或业务验收。",
        ]
    else:
        lines += [
            "- 未取得 invocation、installation、Release、首错、事务或失败提示状态；当前计数不能证明客户端历史是否完整。",
            "- 若客户端确有失败，先核对查询的 Agent、任务、发生时间和保留窗口；仍无法定位时，由项目方决定是否请平台核查。此摘要不是平台已接单或业务验收。",
        ]
    lines += [
        "- 项目需补充：目标实例、签名包 SHA-256、上传与列表回读、所选模型、操作步骤、预期与实际、脱敏客户端观察，以及开发侧本地复现和修复结果；缺项标“未取得”。",
        "",
    ]
    return "\n".join(lines)


def _render_v6_reference(response, schema):
    def observed(value):
        return "是" if value is True else "否" if value is False else "未记录"

    lines = [
        f"- 运行证据：`{response['runtime_evidence']}`；本地任务证据：`{response['local_task_evidence']}`。",
        f"- Release：`{_token(response['release_id'])}`；installation：`{_token(response['installation_id'])}`。",
        f"- 回合：`{response['runtime_outcome']}`；事务：`{response['transaction_status']}`；任务受理：`{response['task_acceptance']}`。",
        f"- 诊断状态：`{response['diagnosis_status']}`；发现 {len(response['findings'])} 条；本地任务 {len(response['local_tasks'])} 条。",
    ]
    found_schema = next(branch for branch in schema["oneOf"]
                        if branch["properties"]["status"]["const"] == "found")
    for field, label in (("findings", "发现"), ("local_tasks", "本地任务")):
        _array_limit_note(lines, label, len(response[field]), found_schema["properties"][field])
    for index, finding in enumerate(response["findings"], 1):
        lines.append(
            f"- 发现 #{index}：层 `{finding['layer']}`；任务 `{_token(finding['task_id'])}`；"
            f"能力 `{_token(finding['capability'])}`；phase `{_token(finding['phase'])}`；"
            f"category `{_token(finding['category'])}`；error_code `{_token(finding['error_code'])}`；"
            f"field_path `{_token(finding['field_path'])}`；constraint `{_token(finding['constraint'])}`；"
            f"责任线 `{finding['responsibility']}`；recovery_action `{_token(finding['recovery_action'])}`；"
            f"证据 `{finding['evidence']}`；观察时间 `{_token(finding['observed_at'])}`。"
        )
        if finding["error_code"] == "HOST_INTERNAL_ERROR" and finding["evidence"] == "first_observed_only":
            lines.append("  - 仅记录了 Host 首个可见异常阶段；内部异常类型与具体根因未留存，不能由平台责任线猜请求或实现细节。")
        elif finding["evidence"] == "historical_detail_not_recorded":
            lines.append("  - 历史具体失败细节未留存；不能补造首错或把该项当作已定位根因。")
    for index, task in enumerate(response["local_tasks"], 1):
        terminal = task["task_status"] in ("succeeded", "failed", "cancelled")
        lines.append(
            f"- 本地任务 #{index}：ID `{_token(task['task_id'])}`；能力 `{_token(task['capability'])}`；"
            f"状态 `{task['task_status']}`（{'终态' if terminal else '尚非终态'}）；"
            f"Release `{_token(task['release_id'])}`；installation `{_token(task['installation_id'])}`；"
            f"Host 派发 `{observed(task['host_dispatched'])}`；Helper 接收 `{observed(task['helper_received'])}`；"
            f"Helper 版本 `{_token(task['helper_version'])}`；首错 phase `{_token(task['first_failure_phase'])}`"
            f"（{task['phase_evidence']}）；异常类别 `{_token(task['exception_category'])}`"
            f"（{task['category_evidence']}）；error_code `{_token(task['error_code'])}`；"
            f"责任线 `{task['responsibility']}`；recovery_action `{_token(task['recovery_action'])}`。"
        )
    if response["runtime_evidence"] == "no_record":
        lines.append("- 运行 trace 未取得；本地任务证据须独立判断，不能将缺失运行证据当作成功。")
    if response["local_task_evidence"] == "unavailable":
        lines.append("- 本地任务证据不可用；不能推定任务未受理或已完成。")
    if response["diagnosis_status"] == "no_failure_recorded":
        lines.append("- 当前留存证据未记录失败；不证明客户业务结果、设备产物或其他未留存环节成功。")
    elif response["diagnosis_status"] == "first_observed_only":
        lines.append("- 仅有首个可观察失败阶段，内部具体异常未留存；不能据此推断唯一根因。")
    elif response["diagnosis_status"] == "historical_detail_not_recorded":
        lines.append("- 历史失败细节未记录；保持具体首错未知，不靠新客户回合补历史证据。")
    if response["runtime_outcome"] == "completed" and any(
        task["task_status"] == "failed" for task in response["local_tasks"]
    ):
        lines.append("- 专家回合完成后本地任务仍可能失败；分别核对任务终态和设备产物，不把回合完成当作任务成功。")
    lines.append("- 多条发现须逐项对照正式合同和任务终态；数组第一项不是唯一根因。受理或终态未核实时不重复派发。")
    return lines


def render_reference_summary(response, schema, agent_id, invocation_id):
    validate_reference_response(response, schema)
    lines = [
        "# DClaw 关联 ID 诊断摘要", "",
        f"- Agent：`{_token(agent_id)}`；关联 ID：`{_token(invocation_id)}`。",
        f"- 查询结果：`{response['status']}`；保留窗口 {response['retention_days']} 天。",
        "- 边界：仅为当前授权查询的脱敏诊断；不含模型正文、客户内容或完整消息历史。", "",
    ]
    if response["status"] == "no_record":
        lines.append("未取得任务、Release、Host 或事务回执；先核对关联 ID、专家归属和保留窗口，不能推定从未失败、未调用或未创建任务。")
    elif response["contract"] == REFERENCE_CONTRACT_V6:
        lines += _render_v6_reference(response, schema)
    elif response["contract"] in (REFERENCE_CONTRACT_V4, REFERENCE_CONTRACT_V5):
        lines += [
            f"- 任务：`{_token(response['task_id'])}`；Release：`{_token(response['release_id'])}`；installation：`{_token(response['installation_id'])}`。",
            f"- 时间：开始 `{_token(response['started_at'])}`；结束 `{_token(response['ended_at'])}`。",
            f"- 回合结果：`{response['runtime_outcome']}`；事务：`{response['transaction_status']}`；任务受理：`{response['task_acceptance']}`。",
            f"- 首错线索：来源 `{response['first_failure_source']}`；phase `{_token(response['first_failure']['phase'])}`；category `{_token(response['first_failure']['category'])}`。首错不等于已定位 Host 拒绝原因。",
            f"- Host 操作记录：{len(response['host_operations'])} 条；本地任务表证据：`{response['task_evidence']}`，匹配任务 {len(response['tasks'])} 条。",
        ]
        found_schema = next(branch for branch in schema["oneOf"]
                            if branch["properties"]["status"]["const"] == "found")
        for field, label in (("host_operations", "Host 操作记录"), ("tasks", "任务表记录"),
                             ("stages", "阶段记录")):
            _array_limit_note(lines, label, len(response[field]),
                              found_schema["properties"][field])
        if not response["host_operations"]:
            lines.append("- Host 事件为空；历史未留存时不能据此断言能力未调用。")
        for operation in response["host_operations"]:
            lines.append(
                f"- Host：`{operation['event']}`；能力 `{_token(operation['capability'])}`；"
                f"状态 `{_token(operation.get('status'))}`；错误 `{_token(operation.get('error_code'))}`；"
                f"任务受理回执 `{'是' if operation.get('task_accepted') is True else '否' if operation.get('task_accepted') is False else '未记录'}`。"
            )
        if response["task_evidence"] == "available":
            if not response["tasks"]:
                lines.append("- 本次关联回合的本地任务表无新任务受理记录；不否定此前已受理任务，历史 Host trace 是否完整另行判断。")
            for task in response["tasks"]:
                lines.append(
                    f"- 本地任务：能力 `{_token(task['capability'])}`；状态 `{_token(task['status'])}`；"
                    f"错误 `{_token(task['error_code'])}`；结果摘要 {'已记录' if task['result_sha256'] else '未记录'}。"
                )
        else:
            lines.append("- 本地任务表不可读；不能从 Host 事件推断任务终态或设备产物。")
        if response["contract"] == REFERENCE_CONTRACT_V5:
            blocker = response["blocker"]
            lines.append(
                f"- 诊断 blocker 字段：阶段 `{_token(blocker['phase'])}`；错误码 `{_token(blocker['error_code'])}`；"
                f"责任线 `{blocker['responsibility']}`；证据 `{blocker['evidence']}`；"
                f"field_path `{_token(blocker['field_path'])}`；constraint `{_token(blocker['constraint'])}`；"
                f"recovery_action `{_token(blocker['recovery_action'])}`。"
            )
            if blocker["evidence"] == "historical_detail_not_recorded":
                no_recorded_failure = (
                    response["runtime_outcome"] == "completed"
                    and response["transaction_status"] == "committed"
                    and response["first_failure_source"] == "not_recorded"
                    and blocker["phase"] == "not_recorded"
                    and not any(op["event"] == "host.operation.failed" or op.get("error_code")
                                for op in response["host_operations"])
                    and not any(task["status"] in ("failed", "cancelled")
                                for task in response["tasks"])
                )
                if no_recorded_failure:
                    lines.append("- 本回合未记录运行失败；blocker 的历史细节占位不证明平台故障。若业务结果未满足，先核对专家验收条件与正式 Host 回执；本诊断不含 Host 原始结果字段。")
                else:
                    lines.append("- 历史失败细节未留存；不能从泛化 Host 异常推断请求字段、设备状态或平台实现根因，也不能据此修改 Agent 或重复派发。按获授权的项目渠道凭关联 ID 请平台核查。")
            else:
                lines.append("- 按已记录的安全错误码、字段约束和正式合同核对责任线；任务是否受理仍以独立任务表为准。开发方改输入须使用新幂等键，同一输入重试沿用原键。")
        lines.append("- 归因边界：`runtime.complete` 只说明回合已完成，不能证明业务成功；历史 Host 事件为 `not_recorded` 时不能断言任务未创建。任务表与 Host 记录分别核对，受理或终态未确认前不重复派发。")
    elif response["contract"] == REFERENCE_CONTRACT_V3:
        blocker = response["final_blocker"]
        detail = response["host_failure_detail"]
        lines += [
            f"- 任务：`{_token(response['task_id'])}`；Release：`{_token(response['release_id'])}`；installation：`{_token(response['installation_id'])}`。",
            f"- 时间：开始 `{_token(response['started_at'])}`；失败 `{_token(response['failed_at'])}`；事务 `{response['transaction_status']}`。",
            f"- 最终阻断：`{_token(blocker['phase'])}/{_token(blocker['category'])}`；责任线索 `{_token(blocker['responsibility'])}`；原因 `{_token(blocker['reason'])}`{_field_details(blocker)}。"
            if blocker["status"] == "recorded" else "- 最终阻断：未记录；不能补造终止原因。",
            f"- Host 拒绝详情：状态 `{detail['status']}`；错误码 `{_token(detail['error_code'])}`；field_path `{_token(detail['field_path'])}`；constraint `{_token(detail['constraint'])}`；recovery_action `{_token(detail['recovery_action'])}`；contract `{_token(detail['contract'])}`。",
        ]
        if detail["status"] != "recorded":
            lines.append("- Host 细节未记录或不适用；不能由泛化错误推断字段、约束或责任。")
        elif detail["error_code"] == "IDEMPOTENCY_CONFLICT":
            lines.append("- 下一步：核对失败时 Release 的幂等键构造和作用域，以及同键请求是否复用不同载荷；回执不含历史请求值，不能仅凭错误码指定碰撞对象。")
        elif detail["recovery_action"] == "contact_platform_with_invocation_id":
            lines.append("- 下一步：以该关联 ID 请平台核对内部异常；脱敏回执不提供异常原文。")
        else:
            lines.append("- 下一步：按安全错误码、约束和正式合同检查失败时 Release 的请求；若证据仍不足，保留未归因并按关联 ID 核查。")
        lines.append("- 归因边界：Host 记录的拒绝不自动证明插件实现有误；须对照失败时 Release 和正式合同判断修复方。")
    else:
        first = response["first_failure"]
        lines += [
            f"- 任务：`{_token(response['task_id'])}`；Release：`{_token(response['release_id'])}`；installation：`{_token(response['installation_id'])}`。",
            f"- 时间：开始 `{_token(response['started_at'])}`；失败 `{_token(response['failed_at'])}`。",
            f"- 首错：来源 `{response['first_failure_source']}`；phase `{_token(first['phase'])}`；category `{_token(first['category'])}`；attempt `{first['attempt'] if first['attempt'] is not None else '未记录'}`；error_code `{_token(response['error_code'])}`。",
            f"- 事务：`{response['transaction_status']}`；脱敏阶段记录 {len(response['stages'])} 条。",
        ]
        is_v2 = response["contract"] == REFERENCE_CONTRACT_V2
        found_schema = next(branch for branch in schema["oneOf"]
                            if branch["properties"]["status"]["const"] == "found")
        schema_fields = found_schema["properties"]
        _array_limit_note(lines, "阶段记录", len(response["stages"]),
                          schema_fields["stages"])
        first_recovered = is_v2 and any(
            event["phase"] == first["phase"]
            and event["category"] == first["category"]
            and event["attempt"] == first["attempt"]
            and event["outcome"] == "recovered"
            for event in response["failure_events"]
        )
        if first_recovered:
            lines.append("- 首错状态：已在本轮恢复；优先核对下方最终阻断，不把首错当作终止原因。")
        else:
            lines.append(f"- 首错检查线索：{_next_step(response)}")
        failed_calls = [stage for stage in response["stages"]
                        if stage["event"].endswith(".safe_failed")]
        if failed_calls:
            stage = failed_calls[-1]
            call_number = stage.get("call_number")
            call_label = f"；call_number `{call_number}`" if call_number is not None else ""
            detail = ("该阶段事件只标记调用失败；终止类别见下方最终阻断。" if is_v2 else
                      "该阶段未提供失败类别，也不能仅凭此事件判定最终根因。")
            lines.append(
                f"- 阶段线索：回执最后列出的调用失败为 `{_token(stage['event'])}`"
                f"（source `{stage['source']}`{call_label}）；{detail}"
            )
        if is_v2:
            events = response["failure_events"]
            signature = lambda event: tuple(
                event.get(key) for key in (
                    "phase", "category", "attempt", "source", "status_code",
                    "provider_code", "provider_param", "outcome", "field_path",
                    "constraint", "contract"
                )
            )
            groups = [list(group) for _, group in groupby(events, signature)]
            lines.append(f"- 失败事件：按回执顺序记录 {len(events)} 条；相邻同类合并为 {len(groups)} 组。")
            _array_limit_note(lines, "失败事件", len(events),
                              schema_fields["failure_events"])
            index = 1
            for group in groups:
                event = group[0]
                last = index + len(group) - 1
                position = f"{index}" if index == last else f"{index}-{last}（{len(group)} 条）"
                time_range = (f"；时间 `{_token(group[0]['at'])}` 至 `{_token(group[-1]['at'])}`"
                              if len(group) > 1 else "")
                lines.append(
                    f"  - #{position} `{_token(event['phase'])}/{_token(event['category'])}`；"
                    f"attempt `{event['attempt'] if event['attempt'] is not None else '未记录'}`；"
                    f"outcome `{event['outcome']}`；source `{event['source']}`；"
                    f"HTTP `{event['status_code'] if event['status_code'] is not None else '未记录'}`；"
                    f"provider code `{_token(event['provider_code'])}`；param `{_token(event['provider_param'])}`"
                    f"{_field_details(event)}{time_range}。"
                )
                index = last + 1
            blocker = response["final_blocker"]
            if blocker["status"] == "recorded":
                lines.append(
                    f"- 最终阻断：`{_token(blocker['phase'])}/{_token(blocker['category'])}`；"
                    f"责任类别 `{blocker['responsibility']}`；原因 `{blocker['reason']}`；"
                    f"attempt `{blocker['attempt'] if blocker['attempt'] is not None else '未记录'}`"
                    f"{_field_details(blocker)}。"
                )
                if (blocker["responsibility"] == "model_provider"
                        and blocker["reason"] == "provider_rejected_request"):
                    lines.append(
                        "- 下一步：核对该 Release 的实际模型请求、执行模式、响应格式与工具 Schema 是否符合目标实例合同；"
                        "提供方拒绝请求不等于已确定请求由 Agent、Host 或模型提供方哪一层构造错误。"
                    )
            else:
                lines.append("- 最终阻断：未记录；不能用首错或阶段事件补造终止原因。")
            if response["unrecorded_fields"]:
                lines.append("- 历史未留存字段：" + "、".join(response["unrecorded_fields"]) + "；不能补造提供方细节。")
            lines.append("- 归因边界：责任类别是诊断线索，仍须结合正式合同和实际 Release 核对修复归属。")
        else:
            lines.append(
                "- 归因边界：首错可能已被后续重试恢复；正式回执未单列最终阻断的阶段和类别。"
                "沿阶段记录核对后续调用与失败关闭；缺少终止类别时标为未取得，不能把首错当作终止原因。"
            )
    lines += ["- 保留原始 JSON 回执；只有证据指向平台职责时才转交，不能用本摘要替代真实客户端复测。", ""]
    return "\n".join(lines)


def render_search_summary(response, schema, agent_id, start, end):
    validate_search_response(response, schema)
    lines = [
        "# DClaw 失败引用搜索摘要", "",
        f"- Agent：`{_token(agent_id)}`；窗口：`{_token(start)}` 至 `{_token(end)}`。",
        f"- 结果：`{response['status']}`；本页 {len(response['failures'])} 条；保留 {response['retention_days']} 天。",
        "- 边界：仅列授权范围内的不透明失败引用；具体根因须按关联 ID 再查正式诊断。", "",
    ]
    for failure in response["failures"]:
        lines.append(
            f"- `{_token(failure['failed_at'])}`；invocation `{_token(failure['invocation_id'])}`；"
            f"任务 `{_token(failure['task_id'])}`；Release `{_token(failure['release_id'])}`。"
        )
    if response["has_more"]:
        lines.append(f"- 下一页 cursor：`{_token(response['next_cursor'])}`；仅在同一窗口继续查询。")
    elif not response["failures"]:
        lines.append("- 本页无记录；这不能证明保留期外或其他窗口从未失败。")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path, help="Existing diagnostics JSON receipt")
    parser.add_argument("--devkit-root", required=True, type=Path, help="Verified official DevKit directory")
    parser.add_argument("--agent-id", required=True)
    identifier = parser.add_mutually_exclusive_group(required=True)
    identifier.add_argument("--task-id")
    identifier.add_argument("--invocation-id", help="Customer-visible failure reference from the same Agent")
    identifier.add_argument("--start", help="UTC search window start; requires --end")
    parser.add_argument("--end", help="Exclusive UTC search window end")
    parser.add_argument("--output", required=True, type=Path, help="New Markdown summary in the Agent project")
    args = parser.parse_args()
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end must be supplied together")
    if args.output.exists() or args.output.is_symlink():
        parser.error("output already exists; inspect it before retrying")
    if not args.receipt.is_file() or args.receipt.resolve() == args.output.resolve():
        parser.error("receipt must be an existing file distinct from output")
    response = json.loads(args.receipt.read_text(encoding="utf-8"))
    if not isinstance(response, dict):
        raise ValueError("diagnostics receipt must be a JSON object")
    if args.start:
        if response.get("contract") != SEARCH_CONTRACT:
            parser.error("receipt is not a diagnostic search response")
        schema_path = args.devkit_root / "schemas" / "runtime-diagnostics-search-v1" / "response.schema.json"
    else:
        schema_name = "by-reference-response.schema.json" if args.invocation_id else "response.schema.json"
        version = ({REFERENCE_CONTRACT_V6: "v6", REFERENCE_CONTRACT_V5: "v5",
                    REFERENCE_CONTRACT_V4: "v4",
                    REFERENCE_CONTRACT_V3: "v3",
                    REFERENCE_CONTRACT_V2: "v2"}.get(
            response.get("contract"), "v1") if args.invocation_id else "v1")
        schema_path = args.devkit_root / "schemas" / f"runtime-diagnostics-{version}" / schema_name
    if not schema_path.is_file():
        parser.error("verified official DevKit has no schema for this diagnostics contract")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if args.start:
        summary = render_search_summary(response, schema, args.agent_id, args.start, args.end)
    elif args.invocation_id:
        summary = render_reference_summary(response, schema, args.agent_id, args.invocation_id)
    else:
        summary = render_summary(response, schema, args.agent_id, args.task_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(summary)
    print(f"saved redacted summary: sha256={hashlib.sha256(summary.encode('utf-8')).hexdigest()}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Diagnostics summary failed: {exc}")
