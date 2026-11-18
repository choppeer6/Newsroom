import pytest
from jinja2 import UndefinedError

from app.prompts.loader import load_prompt

PROMPT_CONTEXTS = {
    ("chief_editor", "planning"): {
        "topic": "选题",
        "description": "",
        "requirements_json": "{}",
    },
    ("chief_editor", "review"): {
        "topic": "选题",
        "description": "",
        "requirements_json": "{}",
        "plan_json": "{}",
        "article_json": "{}",
        "article_version": 2,
        "sources_json": "[]",
        "fact_check_json": "{}",
        "retry_count": 0,
        "max_retry": 2,
    },
    ("reporter", "search_queries"): {
        "plan_json": "{}",
        "revision_json": "",
        "existing_sources_json": "",
    },
    ("reporter", "write_draft"): {
        "requirements_json": "{}",
        "plan_json": "{}",
        "sources_json": "[]",
        "revision_json": "",
        "previous_draft_json": "",
    },
    ("editor", "edit_article"): {
        "requirements_json": "{}",
        "draft_json": "{}",
        "revision_json": "",
        "review_comments": "",
        "fact_check_json": "",
    },
    ("fact_checker", "extract_claims"): {"title": "标题", "content": "正文"},
    ("fact_checker", "verify_claims"): {
        "claims_json": "[]",
        "evidence_json": "[]",
        "title": "标题",
        "content": "正文",
    },
}


@pytest.mark.parametrize(("agent", "name"), PROMPT_CONTEXTS)
def test_agent_prompt_loads_and_renders(agent, name):
    spec = load_prompt(agent, name)

    rendered = spec.render(**PROMPT_CONTEXTS[(agent, name)])

    assert spec.version == "v1"
    assert spec.system
    assert "输出规则" in spec.system
    assert "安全规则" in spec.system
    assert rendered


def test_prompt_requires_all_template_variables():
    spec = load_prompt("reporter", "search_queries")

    with pytest.raises(UndefinedError):
        spec.render(plan_json="{}")
