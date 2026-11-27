# QwenPaw 智能体技能 (Skill) 设计规范与开发标准 (2026 版)

## 1. 前言与时代转型 (Preface & Context)

站在 2026 年的技术节点上，大模型的 Tool-Calling（工具调用）和 Function-Calling（函数调用）机制已达到微秒级响应与高精度匹配。

智能体的“技能（Skill/Tool）”是其改造外部世界、操作物理系统的核心媒介。一个优秀的智能体技能，绝不再是“一段简陋的一行式 Python 脚本”或“一个无拦截的裸奔 API”。在今天，**高可用、高工程操守的技能** 必须遵循以下五大金标准。

---

## 2. 智能体技能五大金标准 (Five Golden Standards for Skills)

### 🌟 标准一：自适应防爆与弹性抗震 (Resilient & Defensible)
*   **参数强校验**：技能的入口参数必须使用强类型模型（如 Python 的 Pydantic，JS 的 Zod）进行拦截。对非法的极值、空值（Null）、越界超长 Payload 实施入口即拦截，杜绝脏数据注入。
*   **弹性容错 (Fail-Safe)**：技能内部涉及网络请求、数据库读写、文件 IO 等高危物理操作时，必须内置 **指数退避重试策略 (Exponential Backoff)**、**断路器机制 (Circuit Breaker)** 和 **精确的超时控制 (Timeout Constraints)**，拒绝无限挂起。

### 🌟 标准二：极简且确定性的 API 表达 (Minimalist & Self-Descriptive Schema)
*   **Schema 极精炼**：函数的 JSON Schema（参数名称、描述、类型说明）必须做到简洁明了、字字玑珠。冗余繁杂的描述会导致大模型“参数幻觉 (Parameter Hallucination)”。
*   **输入幂等性 (Idempotency)**：高危及写操作（如写文件、高危命令行操作）必须默认支持 **Dry-Run 模式 (预览模拟)**，并在非幂等操作上内置防重复锁。

### 🌟 标准三：无副作用与纯净沙箱友好性 (Sandbox-Friendly & Secure)
*   **安全沙箱边界**：技能的运行必须限制在明确的安全沙箱边界内，严禁未经人类用户授权的外部网络穿透、无感越权读取敏感密钥等行为。
*   **资源回收闭环 (Resource Closing)**：凡涉及文件流、网络连接连接池、物理端口占用的技能，在执行完毕后必须在 `finally` 块中完成 100% 物理资源回收，严防内存泄露与物理锁死。

### 🌟 标准四：高内聚的统一结构化输出 (Standardized & Structured Output)
*   **统一返回体规范**：拒绝直接返回未处理的 raw-text 或报错堆栈。技能的返回结果必须是强类型 JSON/Markdown，统一包含以下标准化字段：
    ```json
    {
      "code": 200, // 状态码: 200 成功, 400 参数错, 500 逻辑崩溃
      "message": "执行成功说明", // 人机双语友好型简述
      "data": {}, // 供智能体下一步消费的纯净结构化载荷 (Payload)
      "debug_info": "" // 调试错误日志 (仅在报错时携带)
    }
    ```

### 🌟 标准五：自带高内聚单元测试自愈包 (Self-Contained Mock & Test-Suite)
*   **自测可执行**：每一个新技能在编写时，必须在自身目录内或代码底部**强制自带 Mock 驱动的单元测试用例**。
*   **自愈闭环底座**：允许 `skill_creator` 在生成或迭代该技能时，无需人类干预，能够在毫秒级一键运行测试校验其 100% 物理通路，保障技能的开箱即用。

---

## 3. QwenPaw 优秀技能结构模板 (Python 示例)

```python
import time
import logging
from typing import Dict, Any
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("qwenpaw.skills")

# 1. 精确的入参强类型定义 (Minimalist Input Schema)
class SkillInputSchema(BaseModel):
    target_path: str = Field(..., description="要读取的物理绝对路径，必须位于沙箱工作区内。")
    retry_count: int = Field(default=3, ge=1, le=5, description="最大重试次数，限制在 1-5 次。")

# 2. 统一结构化输出定义 (Standard Output Format)
class SkillOutput:
    @staticmethod
    def success(data: Dict[str, Any], message: str = "Success") -> Dict[str, Any]:
        return {"code": 200, "message": message, "data": data}

    @staticmethod
    def error(code: int, message: str, debug_info: str = "") -> Dict[str, Any]:
        return {"code": code, "message": message, "data": {}, "debug_info": debug_info}

# 3. 核心高可用逻辑实现 (Core Tool Core)
def read_workspace_file_skill(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    自适应防爆的高可用工作区文件读取技能。
    """
    # [步骤 A] 入口拦截校验 (Pydantic Validation)
    try:
        validated_data = SkillInputSchema(**params)
    except ValidationError as e:
        return SkillOutput.error(400, "参数强校验失败", debug_info=str(e))

    # [步骤 B] 防御性核心逻辑与重试机制 (Exponential Backoff)
    path = validated_data.target_path
    retries = validated_data.retry_count
    backoff = 0.5

    for attempt in range(1, retries + 1):
        try:
            # 模拟高可用安全拦截
            if ".." in path or "/etc" in path:
                return SkillOutput.error(403, "拒绝访问越界路径 (Path Traversal Blocked)")

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 100% 正常交付，提供干净的 data 载荷
            return SkillOutput.success({"content": content}, message="文件读取成功")

        except FileNotFoundError:
            return SkillOutput.error(404, f"目标文件不存在: {path}")
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            if attempt == retries:
                return SkillOutput.error(500, "系统内部逻辑崩溃，已达最大重试上限", debug_info=str(e))
            time.sleep(backoff)
            backoff *= 2 # 指数退避

# 4. 内聚单元测试校验包 (Self-Contained Mock Test)
def test_read_workspace_file_skill():
    # 正常流测试
    ok_res = read_workspace_file_skill({"target_path": "pyproject.toml"})
    assert ok_res["code"] == 200
    assert "data" in ok_res

    # 路径越界流测试
    block_res = read_workspace_file_skill({"target_path": "../../../etc/passwd"})
    assert block_res["code"] == 403

    # 参数越界测试
    err_res = read_workspace_file_skill({"target_path": "pyproject.toml", "retry_count": 99})
    assert err_res["code"] == 400
    print("All unit tests passed successfully!")
```

---

## 4. 技能编写自检清单 (Skill Quality Checklist)

技能在物理交付前，必须通过以下 5 大指标检验：
1.  **[入参 Zod/Pydantic 化]** 参数定义是否全部由强类型拦截器接管？
2.  **[指数退避重试]** 涉及外部 IO/网络调用时，是否内置了指数退避的重试自愈逻辑？
3.  **[纯净统一返回]** 返回体是否包装了结构化的 `{"code", "message", "data", "debug_info"}`？
4.  **[资源安全闭环]** 文件流和连接句柄是否全部包含在 `finally` 块中，并在异常时能够被安全关闭？
5.  **[测试用例随行]** 是否在代码内/侧附带了至少 3 种边界场景的单元测试用例，允许 `skill_creator` 一键自动运行校验？
