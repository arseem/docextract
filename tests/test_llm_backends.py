from __future__ import annotations

import httpx
import pytest
import respx

from docextract.config import OllamaConfig, OpenAICompatConfig
from docextract.llm.base import LLMError, LLMTimeoutError, LLMUnavailableError
from docextract.llm.ollama import OllamaBackend
from docextract.llm.openai_compat import OpenAICompatBackend


@pytest.fixture
def ollama_backend():
    config = OllamaConfig(
        base_url="http://testhost:11434", model_tag="test-model", model_digest="abc123"
    )
    return OllamaBackend(config)


@respx.mock
def test_ollama_generate_parses_response_and_tokens(ollama_backend):
    respx.post("http://testhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"content": '{"doc_type": "other"}'},
                "prompt_eval_count": 42,
                "eval_count": 7,
            },
        )
    )
    resp = ollama_backend.generate("some prompt", max_tokens=100)
    assert resp.text == '{"doc_type": "other"}'
    assert resp.tokens_in == 42
    assert resp.tokens_out == 7


@respx.mock
def test_ollama_generate_sends_explicit_options(ollama_backend):
    route = respx.post("http://testhost:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "{}"}})
    )
    ollama_backend.generate("prompt", max_tokens=50)
    sent = route.calls[0].request
    import json

    body = json.loads(sent.content)
    assert body["model"] == "test-model"
    assert body["options"]["num_ctx"] == ollama_backend.config.num_ctx
    assert body["options"]["temperature"] == 0.0
    assert body["options"]["seed"] == ollama_backend.config.seed
    assert body["stream"] is False
    assert "format" in body  # structured-output JSON schema


@respx.mock
def test_ollama_timeout_maps_to_llm_timeout_error(ollama_backend):
    respx.post("http://testhost:11434/api/chat").mock(side_effect=httpx.TimeoutException("slow"))
    with pytest.raises(LLMTimeoutError):
        ollama_backend.generate("prompt", max_tokens=10)


@respx.mock
def test_ollama_connection_error_maps_to_unavailable(ollama_backend):
    respx.post("http://testhost:11434/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMUnavailableError):
        ollama_backend.generate("prompt", max_tokens=10)


@respx.mock
def test_ollama_5xx_maps_to_unavailable(ollama_backend):
    respx.post("http://testhost:11434/api/chat").mock(return_value=httpx.Response(503))
    with pytest.raises(LLMUnavailableError):
        ollama_backend.generate("prompt", max_tokens=10)


@respx.mock
def test_ollama_verify_model_digest_mismatch_raises(ollama_backend):
    respx.get("http://testhost:11434/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "test-model", "digest": "sha256:different"}]}
        )
    )
    with pytest.raises(LLMError, match="digest mismatch"):
        ollama_backend.verify_model_available()


@respx.mock
def test_ollama_verify_model_matching_digest_ok(ollama_backend):
    respx.get("http://testhost:11434/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "test-model", "digest": "sha256:abc123"}]}
        )
    )
    ollama_backend.verify_model_available()  # must not raise


@respx.mock
def test_ollama_verify_model_missing_raises_helpful_error(ollama_backend):
    respx.get("http://testhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    with pytest.raises(LLMError, match="not found"):
        ollama_backend.verify_model_available()


@respx.mock
def test_ollama_verify_unreachable_raises_unavailable(ollama_backend):
    respx.get("http://testhost:11434/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMUnavailableError):
        ollama_backend.verify_model_available()


@pytest.fixture
def openai_backend():
    config = OpenAICompatConfig(base_url="http://testhost:8080/v1", model_tag="local-model")
    return OpenAICompatBackend(config)


@respx.mock
def test_openai_compat_generate_parses_response(openai_backend):
    respx.post("http://testhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"doc_type": "invoice"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        )
    )
    resp = openai_backend.generate("prompt", max_tokens=100)
    assert resp.text == '{"doc_type": "invoice"}'
    assert resp.tokens_in == 10
    assert resp.tokens_out == 3


@respx.mock
def test_openai_compat_sends_json_schema_response_format(openai_backend):
    route = respx.post("http://testhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}}
        )
    )
    openai_backend.generate("prompt", max_tokens=50)
    import json

    body = json.loads(route.calls[0].request.content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["temperature"] == 0.0
    assert "seed" in body


@respx.mock
def test_openai_compat_timeout_maps_to_llm_timeout_error(openai_backend):
    respx.post("http://testhost:8080/v1/chat/completions").mock(
        side_effect=httpx.TimeoutException("slow")
    )
    with pytest.raises(LLMTimeoutError):
        openai_backend.generate("prompt", max_tokens=10)
