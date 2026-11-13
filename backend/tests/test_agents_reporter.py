import asyncio

from app.agents.contracts import ReporterInput
from app.agents.reporter import ReporterAgent
from app.core.llm import LLMError
from app.schemas.domain import RevisionRequest
from app.schemas.enums import AgentStatus, RevisionTarget
from app.tools.search import SearchError, SearchNotConfiguredError
from tests.fakes import (
    FakeLLM,
    FakeSearch,
    make_article,
    make_hit,
    make_plan,
    make_requirements,
    make_source,
)

DRAFT_RESPONSE = {
    "title": "人工智能正在改变高校课堂",
    "content": "新闻正文，引用检索到的资料。",
    "research_summary": "检索发现多所高校已开展人工智能教学实践。",
    "unverified_claims": ["部分统计数据尚待核实", "部分统计数据尚待核实"],
}


def run_agent(agent: ReporterAgent, payload: ReporterInput):
    return asyncio.run(agent.run(payload))


def test_reporter_collects_deduplicates_and_writes_draft():
    llm = FakeLLM(
        [
            {"queries": ["高校人工智能教学案例", "高校人工智能教学效果"]},
            DRAFT_RESPONSE,
        ]
    )
    search = FakeSearch(
        {
            "高校人工智能教学案例": [
                make_hit("案例 A", url="https://a.example.com/case"),
                make_hit("案例 B", url="https://b.example.com/case"),
            ],
            "高校人工智能教学效果": [
                make_hit("案例 A 重复", url="https://a.example.com/case/"),
                make_hit("效果 C", url="https://c.example.com/effect"),
            ],
        }
    )
    agent = ReporterAgent(llm=llm, search=search)

    output = run_agent(
        agent,
        ReporterInput(
            task_id="TASK_001",
            editorial_plan=make_plan(),
            requirements=make_requirements(),
        ),
    )

    assert output.status == AgentStatus.COMPLETED
    assert [source.source_id for source in output.sources] == [
        "SRC_0001",
        "SRC_0002",
        "SRC_0003",
    ]
    assert {source.url for source in output.sources} == {
        "https://a.example.com/case",
        "https://b.example.com/case",
        "https://c.example.com/effect",
    }
    assert output.draft is not None
    assert output.draft.title == DRAFT_RESPONSE["title"]
    assert output.research_summary == DRAFT_RESPONSE["research_summary"]
    assert output.unverified_claims == ["部分统计数据尚待核实"]
    assert set(search.queries) == {"高校人工智能教学案例", "高校人工智能教学效果"}

    draft_prompt = llm.calls[1]["user"]
    assert "<available_sources>" in draft_prompt
    assert "https://a.example.com/case" in draft_prompt
    assert "客观新闻报道" in draft_prompt


def test_reporter_revision_reuses_existing_sources_and_previous_draft():
    llm = FakeLLM(
        [
            {"queries": ["补充高校案例"]},
            DRAFT_RESPONSE,
        ]
    )
    search = FakeSearch(default=[])
    existing = make_source("SRC_0009", url="https://old.example.com/a")
    revision = RevisionRequest(
        target=RevisionTarget.REPORTER,
        reason="资料不足",
        requirements=["补充另一所高校的案例"],
    )
    agent = ReporterAgent(llm=llm, search=search)

    output = run_agent(
        agent,
        ReporterInput(
            task_id="TASK_001",
            editorial_plan=make_plan(),
            revision_request=revision,
            existing_sources=[existing],
            previous_draft=make_article("旧标题", "旧正文内容"),
        ),
    )

    assert output.status == AgentStatus.COMPLETED
    assert [source.source_id for source in output.sources] == ["SRC_0009"]
    assert "补充另一所高校的案例" in llm.calls[0]["user"]
    assert "旧正文内容" in llm.calls[1]["user"]
    assert "https://old.example.com/a" in llm.calls[1]["user"]


def test_reporter_fails_when_first_search_returns_nothing():
    llm = FakeLLM([{"queries": ["查询"]}])
    agent = ReporterAgent(llm=llm, search=FakeSearch(default=[]))

    output = run_agent(
        agent,
        ReporterInput(task_id="TASK_001", editorial_plan=make_plan()),
    )

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "SEARCH_EMPTY"
    assert output.error.retryable is True
    assert len(llm.calls) == 1


def test_reporter_maps_search_configuration_error():
    llm = FakeLLM([{"queries": ["查询"]}])
    agent = ReporterAgent(
        llm=llm,
        search=FakeSearch(error=SearchNotConfiguredError()),
    )

    output = run_agent(
        agent,
        ReporterInput(task_id="TASK_001", editorial_plan=make_plan()),
    )

    assert output.error is not None
    assert output.error.code == "SEARCH_NOT_CONFIGURED"
    assert output.error.retryable is False


def test_reporter_maps_search_failure():
    llm = FakeLLM([{"queries": ["查询"]}])
    agent = ReporterAgent(
        llm=llm,
        search=FakeSearch(error=SearchError("搜索服务不可用", retryable=True)),
    )

    output = run_agent(
        agent,
        ReporterInput(task_id="TASK_001", editorial_plan=make_plan()),
    )

    assert output.error is not None
    assert output.error.code == "SEARCH_FAILED"
    assert output.error.retryable is True


def test_reporter_retries_invalid_query_output_once():
    llm = FakeLLM(
        [
            {"queries": []},
            {"queries": ["有效查询"]},
            DRAFT_RESPONSE,
        ]
    )
    agent = ReporterAgent(
        llm=llm,
        search=FakeSearch(default=[make_hit()]),
    )

    output = run_agent(
        agent,
        ReporterInput(task_id="TASK_001", editorial_plan=make_plan()),
    )

    assert output.status == AgentStatus.COMPLETED
    assert "未通过校验" in llm.calls[1]["user"]


def test_reporter_retries_invalid_json_once():
    llm = FakeLLM(
        [
            LLMError("LLM_INVALID_JSON", "模型未返回合法 JSON", retryable=True),
            {"queries": ["有效查询"]},
            DRAFT_RESPONSE,
        ]
    )
    agent = ReporterAgent(
        llm=llm,
        search=FakeSearch(default=[make_hit()]),
    )

    output = run_agent(
        agent,
        ReporterInput(task_id="TASK_001", editorial_plan=make_plan()),
    )

    assert output.status == AgentStatus.COMPLETED
    assert "不是合法 JSON" in llm.calls[1]["user"]


def test_reporter_returns_failed_after_invalid_draft_retry():
    llm = FakeLLM(
        [
            {"queries": ["查询"]},
            {"title": "", "content": "正文", "research_summary": "总结"},
            {"title": "", "content": "正文", "research_summary": "总结"},
        ]
    )
    agent = ReporterAgent(
        llm=llm,
        search=FakeSearch(default=[make_hit()]),
    )

    output = run_agent(
        agent,
        ReporterInput(task_id="TASK_001", editorial_plan=make_plan()),
    )

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "LLM_OUTPUT_INVALID"
    assert len(llm.calls) == 3


def test_reporter_maps_llm_configuration_error():
    llm = FakeLLM([LLMError("LLM_NOT_CONFIGURED", "尚未配置 LLM_API_KEY")])
    agent = ReporterAgent(llm=llm, search=FakeSearch(default=[]))

    output = run_agent(
        agent,
        ReporterInput(task_id="TASK_001", editorial_plan=make_plan()),
    )

    assert output.error is not None
    assert output.error.code == "LLM_NOT_CONFIGURED"
    assert output.error.retryable is False
