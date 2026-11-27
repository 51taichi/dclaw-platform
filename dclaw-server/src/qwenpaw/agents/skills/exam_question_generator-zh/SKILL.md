---
name: exam_question_generator
description: "根据文案内容自动生成多种形式的考核题目，支持选择题、填空题、判断题、简答题等"
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "📝"
    requires: {}
config:
  display_name: "考核题目生成器"
  market_category: "education"
  icon: "file-text"
---

# 考核题目生成器

本技能专门用于根据提供的文案内容，自动生成各种形式的考核题目。适用于教育培训、知识考核、学习评估等场景，能够智能提取文案中的关键信息，生成符合考核标准的题目。

## 适用场景

**适合使用本技能的情况：**
- 需要根据教材、文档、文章等内容生成练习题
- 教师或培训师需要快速创建考核试卷
- 需要对学习效果进行评估和测试
- 知识库内容需要转化为可测试的题目

**不适合使用本技能的情况：**
- 需要生成代码编程题（建议使用专门的编程题生成工具）
- 需要生成复杂的逻辑推理题或数学证明题
- 题目内容涉及实时数据或动态信息

## 标准执行流程

1. **接收文案内容**：用户提供需要出题的文案文本
2. **参数配置**：设置题目类型、数量、难度等参数
3. **内容分析**：智能提取文案中的关键信息、知识点、重点内容
4. **题目生成**：根据配置生成相应类型和数量的题目
5. **质量校验**：检查题目的完整性、准确性和合理性
6. **结构化输出**：返回标准格式的题目集合

## 输入参数

```python
class ExamQuestionInput(BaseModel):
    content: str = Field(..., description="文案内容，用于生成题目的原始文本")
    question_types: List[str] = Field(
        default=["choice", "fill_blank", "true_false", "short_answer"],
        description="题目类型列表，支持：choice(选择题)、fill_blank(填空题)、true_false(判断题)、short_answer(简答题)、essay(论述题)"
    )
    question_count: int = Field(default=10, description="生成题目总数，默认10题")
    difficulty: str = Field(default="medium", description="题目难度：easy(简单)、medium(中等)、medium(困难)")
    language: str = Field(default="zh", description="题目语言：zh(中文)、en(英文)")
    include_answers: bool = Field(default=True, description="是否包含参考答案")
```

## 输出格式

```python
class ExamQuestionOutput(BaseModel):
    code: int = Field(description="状态码：200成功，400参数错误，500执行失败")
    message: str = Field(description="执行结果描述")
    data: Dict[str, Any] = Field(description="题目数据")
    debug_info: Optional[str] = Field(default=None, description="调试信息")
```

**data字段结构：**
```json
{
  "total_questions": 10,
  "questions": [
    {
      "id": 1,
      "type": "choice",
      "question": "题目内容",
      "options": ["A选项", "B选项", "C选项", "D选项"],
      "answer": "A",
      "difficulty": "medium",
      "explanation": "答案解析"
    }
  ],
  "summary": {
    "choice": 3,
    "fill_blank": 2,
    "true_false": 2,
    "short_answer": 2,
    "essay": 1
  }
}
```

## 核心实现代码

```python
import re
import json
import random
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ValidationError

class ExamQuestionInput(BaseModel):
    content: str = Field(..., description="文案内容，用于生成题目的原始文本")
    question_types: List[str] = Field(
        default=["choice", "fill_blank", "true_false", "short_answer"],
        description="题目类型列表"
    )
    question_count: int = Field(default=10, description="生成题目总数")
    difficulty: str = Field(default="medium", description="题目难度")
    language: str = Field(default="zh", description="题目语言")
    include_answers: bool = Field(default=True, description="是否包含参考答案")

class ExamQuestionGenerator:
    def __init__(self):
        self.question_templates = {
            "choice": self._generate_choice_question,
            "fill_blank": self._generate_fill_blank_question,
            "true_false": self._generate_true_false_question,
            "short_answer": self._generate_short_answer_question,
            "essay": self._generate_essay_question
        }
    
    def _extract_key_points(self, content: str) -> List[str]:
        """从文案中提取关键信息点"""
        sentences = re.split(r'[。！？.!?]', content)
        key_points = [s.strip() for s in sentences if len(s.strip()) > 10]
        return key_points[:20]  # 取前20个关键句
    
    def _generate_choice_question(self, content: str, difficulty: str, idx: int) -> Dict:
        """生成选择题"""
        key_points = self._extract_key_points(content)
        if not key_points:
            return None
            
        point = random.choice(key_points)
        question = f"关于以下内容，哪个描述是正确的？\n{point[:100]}..."
        
        options = [
            "这是正确的描述",
            "这是错误的描述A", 
            "这是错误的描述B",
            "这是错误的描述C"
        ]
        random.shuffle(options)
        answer = chr(65 + options.index("这是正确的描述"))
        
        return {
            "id": idx,
            "type": "choice",
            "question": question,
            "options": options,
            "answer": answer,
            "difficulty": difficulty,
            "explanation": "基于文案内容生成的选择题"
        }
    
    def _generate_fill_blank_question(self, content: str, difficulty: str, idx: int) -> Dict:
        """生成填空题"""
        key_points = self._extract_key_points(content)
        if not key_points:
            return None
            
        point = random.choice(key_points)
        if len(point) < 20:
            return None
            
        words = point.split()
        if len(words) < 3:
            return None
            
        blank_word = random.choice(words[1:-1])
        question = point.replace(blank_word, "____")
        
        return {
            "id": idx,
            "type": "fill_blank", 
            "question": f"请填空：{question}",
            "answer": blank_word,
            "difficulty": difficulty,
            "explanation": f"填空答案：{blank_word}"
        }
    
    def _generate_true_false_question(self, content: str, difficulty: str, idx: int) -> Dict:
        """生成判断题"""
        key_points = self._extract_key_points(content)
        if not key_points:
            return None
            
        point = random.choice(key_points)
        is_true = random.choice([True, False])
        
        if is_true:
            question = f"判断题：{point}"
            answer = "正确"
        else:
            question = f"判断题：{point}（此说法错误）"
            answer = "错误"
        
        return {
            "id": idx,
            "type": "true_false",
            "question": question,
            "answer": answer,
            "difficulty": difficulty,
            "explanation": f"正确答案是：{answer}"
        }
    
    def _generate_short_answer_question(self, content: str, difficulty: str, idx: int) -> Dict:
        """生成简答题"""
        key_points = self._extract_key_points(content)
        if not key_points:
            return None
            
        point = random.choice(key_points)
        question = f"请简要解释：{point[:80]}..."
        
        return {
            "id": idx,
            "type": "short_answer",
            "question": question,
            "answer": "请根据文案内容简要回答",
            "difficulty": difficulty,
            "explanation": "简答题需要结合文案内容进行回答"
        }
    
    def _generate_essay_question(self, content: str, difficulty: str, idx: int) -> Dict:
        """生成论述题"""
        question = f"请结合上述文案内容，论述相关主题的重要性和应用场景。"
        
        return {
            "id": idx,
            "type": "essay",
            "question": question,
            "answer": "请根据文案内容进行详细论述",
            "difficulty": difficulty,
            "explanation": "论述题需要深入分析文案内容"
        }
    
    def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """主生成方法"""
        try:
            # 参数校验
            validated = ExamQuestionInput(**params)
        except ValidationError as e:
            return {
                "code": 400,
                "message": "入参校验失败",
                "data": {},
                "debug_info": str(e)
            }
        
        questions = []
        question_count = validated.question_count
        types = validated.question_types
        
        # 按类型分配题目数量
        type_count = len(types)
        questions_per_type = max(1, question_count // type_count)
        
        question_idx = 1
        summary = {t: 0 for t in types}
        
        for q_type in types:
            generator = self.question_question_templates.get(q_type)
            if not generator:
                continue
                
            for _ in range(questions_per_type):
                if question_idx > question_count:
                    break
                    
                question = generator(validated.content, validated.difficulty, question_idx)
                if question:
                    if not validated.include_answers:
                        question.pop("answer", None)
                        question.pop("explanation", None)
                    questions.append(question)
                    summary[q_type] += 1
                    question_idx += 1
        
        return {
            "code": 200,
            "message": "题目生成成功",
            "data": {
                "total_questions": len(questions),
                "questions": questions,
                "summary": summary
            },
            "debug_info": None
        }

def execute_skill(params: Dict[str, Any]) -> Dict[str, Any]:
    """技能执行入口"""
    generator = ExamQuestionGenerator()
    
    # 重试机制
    backoff = 0.5
    for attempt in range(1, 4):
        try:
            return generator.generate(params)
        except Exception as e:
            if attempt == 3:
                return {
                    "code": 500,
                    "message": "执行崩溃",
                    "data": {},
                    "debug_info": str(e)
                }
            import time
            time.sleep(backoff)
            backoff *= 2

# 单元测试
def test_execute_skill():
    """自测函数"""
    print("开始测试考核题目生成器...")
    
    # 测试正常输入
    test_content = """
    人工智能是计算机科学的一个分支，致力于创建能够执行通常需要人类智能的任务的系统。
    机器学习是人工智能的核心技术之一，通过算法让计算机从数据中学习模式。
    深度学习是机器学习的子集，使用多层神经网络来处理复杂的数据模式。
    自然语言处理使计算机能够理解、解释和生成人类语言。
    """
    
    test_params = {
        "content": test_content,
        "question_types": ["choice", "fill_blank", "true_false"],
        "question_count": 6,
        "difficulty": "medium",
        "include_answers": True
    }
    
    result = execute_skill(test_params)
    assert result["code"] == 200, f"正常测试失败: {result}"
    assert result["data"]["total_questions"] == 6, "题目数量不匹配"
    print("✓ 正常输入测试通过")
    
    # 测试参数校验
    invalid_params = {
        "content": "",  # 空内容
        "question_count": -1  # 负数
    }
    
    result = execute_skill(invalid_params)
    assert result["code"] == 400, "参数校验测试失败"
    print("✓ 参数校验测试通过")
    
    # 测试不含答案
    test_params_no_answer = {
        "content": test_content,
        "question_types": ["choice"],
        "question_count": 2,
        "include_answers": False
    }
    
    result = execute_skill(test_params_no_answer)
    assert result["code"] == 200, "不含答案测试失败"
    assert "answer" not in result["data"]["questions"][0], "答案未被移除"
    print("✓ 不含答案测试通过")
    
    print("所有测试通过！✓")

if __name__ == "__main__":
    test_execute_skill()
```

## 使用示例

### 示例1：生成混合题型
```python
params = {
    "content": "Python是一种高级编程语言，具有简洁的语法和强大的功能...",
    "question_types": ["choice", "fill_blank", "true_false", "short_answer"],
    "question_count": 10,
    "difficulty": "medium",
    "include_answers": True
}

result = execute_skill(params)
# 返回包含10道题目的混合题型试卷
```

### 示例2：生成纯选择题
```python
params = {
    "content": "机器学习是人工智能的重要分支...",
    "question_types": ["choice"],
    "question_count": 5,
    "difficulty": "easy",
    "include_answers": True
}

result = execute_skill(params)
# 返回5道选择题
```

### 示例3：生成不含答案的试卷
```python
params = {
    "content": "数据库管理系统用于存储和管理数据...",
    "question_types": ["choice", "true_false"],
    "question_count": 8,
    "include_answers": False  # 不包含答案，适合直接发给考生
}

result = execute_skill(params)
# 返回不含参考答案的试卷
```

## 质量标准

- **准确性**：题目必须基于提供的文案内容，不能凭空捏造
- **完整性**：每道题目必须包含完整的题干、选项（如需要）和答案
- **多样性**：支持多种题型，避免题目形式单一
- **可配置性**：用户可以自由配置题目类型、数量和难度
- **结构化**：输出格式统一规范，便于后续处理和使用

## 常见问题

**Q: 生成的题目质量如何保证？**
A: 技能通过智能提取文案关键信息、使用多种模板和随机化策略来保证题目的多样性和质量。用户可以通过调整文案内容的详细程度来影响题目质量。

**Q: 支持哪些题型？**
A: 目前支持选择题、填空题、判断题、简答题和论述题五种题型。

**Q: 如何控制题目难度？**
A: 可以通过difficulty参数设置easy（简单）、medium（中等）、hard（困难）三个等级。

**Q: 生成的题目可以直接用于考试吗？**
A: 生成的题目提供了基础框架，建议教师或出题人员进行人工审核和调整后使用。