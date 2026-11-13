import asyncio

from app.agents.chief_editor import ChiefPlanningAgent
from app.agents.contracts import ChiefPlanningInput
from app.core.llm import LLMError
from app.schemas.enums import AgentStatus
from tests.fakes import FakeLLM, make_requirements

PLAN_RESPONSE = {
    "topic_analysis": "选题聚焦人工智能在高校教学中的应用现状，具有公共讨论价值。",
    "reporting_angles": ["应用案例", "教学效果", " 应用案例 "],
    "research_tasks": ["搜集高校案例", "查找公开统计数据"],
    "article_outline": ["背景", "应用现状", "典型案例"],
    "verification_points": ["案例真实性", "统计数据准确性"],
}


def run_agent(agent: ChiefPlanningAgent, payload: ChiefPlanningInput):
    return asyncio.run(agent.run(payload))


def make_input() -> ChiefPlanningInput:
    return ChiefPlanningInput(
        task_id="TASK_001",
        topic="人工智能在高校教育中的应用",
        description="关注教学实践与效果",
        requirements=make_requirements(),
    )


def test_planning_outputs_structured_plan_and_dedupes_angles():
    llm = FakeLLM([PLAN_RESPONSE])
    output = run_agent(ChiefPlanningAgent(llm=llm), make_input())

    assert output.status == AgentStatus.COMPLETED
    plan = output.editorial_plan
    assert plan is not None
    assert plan.reporting_angles == ["应用案例", "教学效果"]
    assert plan.article_outline == ["背景", "应用现状", "典型案例"]
    assert "采编计划" in llm.calls[0]["user"]


def test_planning_retries_on_invalid_json():
    llm = FakeLLM(
        [
            LLMError("LLM_INVALID_JSON", "not json", retryable=True),
            PLAN_RESPONSE,
        ]
    )
    output = run_agent(ChiefPlanningAgent(llm=llm), make_input())

    assert output.status == AgentStatus.COMPLETED
    assert len(llm.calls) == 2
    assert "合法 JSON" in llm.calls[1]["user"]


def test_planning_retries_when_required_field_missing():
    incomplete = {"topic_analysis": "只有分析", "reporting_angles": ["角度"]}
    llm = FakeLLM([incomplete, incomplete])
    output = run_agent(ChiefPlanningAgent(llm=llm), make_input())

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "LLM_OUTPUT_INVALID"


def test_planning_rejects_empty_angle_list():
    empty = dict(PLAN_RESPONSE, reporting_angles=["   "])
    llm = FakeLLM([empty, empty])
    output = run_agent(ChiefPlanningAgent(llm=llm), make_input())

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "LLM_OUTPUT_INVALID"


def test_planning_returns_llm_failure():
    llm = FakeLLM([LLMError("LLM_REQUEST_FAILED", "模型请求失败")])
    output = run_agent(ChiefPlanningAgent(llm=llm), make_input())

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "LLM_REQUEST_FAILED"
