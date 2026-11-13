from app.core.config import Settings


def test_blank_secret_values_are_not_configured():
    settings = Settings(_env_file=None, llm_api_key="", search_api_key="   ")

    assert settings.llm_api_key is None
    assert settings.search_api_key is None


def test_configured_secret_values_are_kept():
    settings = Settings(
        _env_file=None,
        llm_api_key="sk-test",
        search_api_key="tvly-test",
    )

    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "sk-test"
    assert settings.search_api_key is not None
    assert settings.search_api_key.get_secret_value() == "tvly-test"
