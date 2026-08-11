import json
from pathlib import Path

from deeptutor.services.config import model_catalog as model_catalog_module
from deeptutor.services.config.env_store import EnvStore
from deeptutor.services.config.model_catalog import ModelCatalogService


def test_load_hydrates_empty_catalog_from_env(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LLM_BINDING=google",
                "LLM_MODEL=gemini-3-flash-preview",
                "LLM_API_KEY=test-llm-key",
                "LLM_HOST=https://example-llm.test/v1",
                "EMBEDDING_BINDING=openai",
                "EMBEDDING_MODEL=text-embedding-3-large",
                "EMBEDDING_API_KEY=test-emb-key",
                "EMBEDDING_HOST=https://example-emb.test/v1",
                "EMBEDDING_DIMENSION=3072",
                "SEARCH_PROVIDER=perplexity",
                "SEARCH_API_KEY=test-search-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "model_catalog.json"
    catalog_path.write_text(
        """{
  "version": 1,
  "services": {
    "llm": {"active_profile_id": null, "active_model_id": null, "profiles": []},
    "embedding": {"active_profile_id": null, "active_model_id": null, "profiles": []},
    "search": {"active_profile_id": null, "profiles": []}
  }
}
""",
        encoding="utf-8",
    )

    env_store = EnvStore(path=env_path)
    monkeypatch.setattr(model_catalog_module, "get_env_store", lambda: env_store)

    service = ModelCatalogService(path=catalog_path)
    catalog = service.load()

    assert catalog["services"]["llm"]["profiles"][0]["binding"] == "google"
    assert catalog["services"]["llm"]["profiles"][0]["extra_headers"] == {}
    assert (
        catalog["services"]["llm"]["profiles"][0]["models"][0]["model"] == "gemini-3-flash-preview"
    )
    assert catalog["services"]["embedding"]["profiles"][0]["models"][0]["dimension"] == "3072"
    assert catalog["services"]["search"]["profiles"][0]["provider"] == "perplexity"
    assert catalog["services"]["search"]["profiles"][0]["proxy"] == ""
    assert catalog["services"]["llm"]["profiles"][0]["api_key"] == ""
    assert catalog["services"]["embedding"]["profiles"][0]["api_key"] == ""
    assert catalog["services"]["search"]["profiles"][0]["api_key"] == ""
    assert "test-llm-key" not in catalog_path.read_text(encoding="utf-8")
    assert "test-emb-key" not in catalog_path.read_text(encoding="utf-8")
    assert "test-search-key" not in catalog_path.read_text(encoding="utf-8")


def test_load_syncs_existing_active_profiles_from_env(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LLM_BINDING=dashscope",
                "LLM_MODEL=qwen3.5-plus",
                "LLM_API_KEY=new-llm-key",
                "LLM_HOST=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "EMBEDDING_BINDING=dashscope",
                "EMBEDDING_MODEL=text-embedding-v4",
                "EMBEDDING_API_KEY=new-emb-key",
                "EMBEDDING_HOST=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "EMBEDDING_DIMENSION=2048",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "model_catalog.json"
    catalog_path.write_text(
        """{
  "version": 1,
  "services": {
    "llm": {
      "active_profile_id": "llm-profile-default",
      "active_model_id": "llm-model-default",
      "profiles": [
        {
          "id": "llm-profile-default",
          "name": "Default LLM Endpoint",
          "binding": "openai",
          "base_url": "https://old-llm.example/v1",
          "api_key": "old-llm-key",
          "api_version": "",
          "extra_headers": {},
          "models": [
            {"id": "llm-model-default", "name": "old-model", "model": "old-model"}
          ]
        }
      ]
    },
    "embedding": {
      "active_profile_id": "embedding-profile-default",
      "active_model_id": "embedding-model-default",
      "profiles": [
        {
          "id": "embedding-profile-default",
          "name": "Default Embedding Endpoint",
          "binding": "openai",
          "base_url": "https://old-emb.example/v1",
          "api_key": "old-emb-key",
          "api_version": "",
          "extra_headers": {},
          "models": [
            {
              "id": "embedding-model-default",
              "name": "old-embedding",
              "model": "old-embedding",
              "dimension": "3072"
            }
          ]
        }
      ]
    },
    "search": {"active_profile_id": null, "profiles": []}
  }
}
""",
        encoding="utf-8",
    )

    env_store = EnvStore(path=env_path)
    monkeypatch.setattr(model_catalog_module, "get_env_store", lambda: env_store)

    service = ModelCatalogService(path=catalog_path)
    catalog = service.load()

    llm_profile = catalog["services"]["llm"]["profiles"][0]
    llm_model = llm_profile["models"][0]
    emb_profile = catalog["services"]["embedding"]["profiles"][0]
    emb_model = emb_profile["models"][0]

    assert llm_profile["binding"] == "dashscope"
    assert llm_profile["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert llm_profile["api_key"] == ""
    assert llm_model["model"] == "qwen3.5-plus"
    assert llm_model["name"] == "qwen3.5-plus"
    assert emb_profile["binding"] == "dashscope"
    assert emb_profile["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert emb_profile["api_key"] == ""
    assert emb_model["model"] == "text-embedding-v4"
    assert emb_model["name"] == "text-embedding-v4"
    assert emb_model["dimension"] == "2048"


def test_save_strips_provider_credentials_from_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "model_catalog.json"
    service = ModelCatalogService(path=catalog_path)
    catalog = {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-profile",
                "active_model_id": "llm-model",
                "profiles": [
                    {
                        "id": "llm-profile",
                        "name": "LLM",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "llm-secret",
                        "models": [
                            {"id": "llm-model", "name": "GPT", "model": "gpt-test"}
                        ],
                    }
                ],
            },
            "embedding": {
                "active_profile_id": "embedding-profile",
                "active_model_id": "embedding-model",
                "profiles": [
                    {
                        "id": "embedding-profile",
                        "name": "Embedding",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1/embeddings",
                        "api_key": "embedding-secret",
                        "models": [
                            {
                                "id": "embedding-model",
                                "name": "Embedding",
                                "model": "embedding-test",
                            }
                        ],
                    }
                ],
            },
            "search": {
                "active_profile_id": "search-profile",
                "profiles": [
                    {
                        "id": "search-profile",
                        "name": "Search",
                        "provider": "brave",
                        "api_key": "search-secret",
                        "models": [],
                    }
                ],
            },
        },
    }

    saved = service.save(catalog)
    persisted = json.loads(catalog_path.read_text(encoding="utf-8"))

    for result in (saved, persisted):
        assert result["services"]["llm"]["profiles"][0]["api_key"] == ""
        assert result["services"]["embedding"]["profiles"][0]["api_key"] == ""
        assert result["services"]["search"]["profiles"][0]["api_key"] == ""


def test_apply_writes_secret_to_env_but_not_catalog(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_API_KEY=existing-key\n", encoding="utf-8")
    env_store = EnvStore(path=env_path)
    monkeypatch.setattr(model_catalog_module, "get_env_store", lambda: env_store)
    catalog_path = tmp_path / "model_catalog.json"
    service = ModelCatalogService(path=catalog_path)
    catalog = {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-profile",
                "active_model_id": "llm-model",
                "profiles": [
                    {
                        "id": "llm-profile",
                        "name": "LLM",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "replacement-key",
                        "models": [
                            {"id": "llm-model", "name": "GPT", "model": "gpt-test"}
                        ],
                    }
                ],
            },
            "embedding": {"active_profile_id": None, "profiles": []},
            "search": {"active_profile_id": None, "profiles": []},
        },
    }

    rendered = service.apply(catalog)
    persisted = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert rendered["LLM_API_KEY"] == "replacement-key"
    assert "LLM_API_KEY=replacement-key" in env_path.read_text(encoding="utf-8")
    assert persisted["services"]["llm"]["profiles"][0]["api_key"] == ""
    assert "replacement-key" not in catalog_path.read_text(encoding="utf-8")


def test_apply_preserves_existing_env_secret_when_catalog_is_redacted(
    tmp_path: Path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_API_KEY=existing-key\n", encoding="utf-8")
    env_store = EnvStore(path=env_path)
    monkeypatch.setattr(model_catalog_module, "get_env_store", lambda: env_store)
    catalog_path = tmp_path / "model_catalog.json"
    service = ModelCatalogService(path=catalog_path)
    catalog = {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-profile",
                "active_model_id": "llm-model",
                "profiles": [
                    {
                        "id": "llm-profile",
                        "name": "LLM",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                        "models": [
                            {"id": "llm-model", "name": "GPT", "model": "gpt-test"}
                        ],
                    }
                ],
            },
            "embedding": {"active_profile_id": None, "profiles": []},
            "search": {"active_profile_id": None, "profiles": []},
        },
    }

    rendered = service.apply(catalog)

    assert rendered["LLM_API_KEY"] == "existing-key"
    assert "LLM_API_KEY=existing-key" in env_path.read_text(encoding="utf-8")
    assert "existing-key" not in catalog_path.read_text(encoding="utf-8")


def test_apply_does_not_restore_stale_process_secret_over_explicit_blank_env(
    tmp_path: Path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_API_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "stale-process-key")
    env_store = EnvStore(path=env_path)
    monkeypatch.setattr(model_catalog_module, "get_env_store", lambda: env_store)
    catalog_path = tmp_path / "model_catalog.json"
    service = ModelCatalogService(path=catalog_path)
    catalog = {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-profile",
                "active_model_id": "llm-model",
                "profiles": [
                    {
                        "id": "llm-profile",
                        "name": "LLM",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                        "models": [
                            {"id": "llm-model", "name": "GPT", "model": "gpt-test"}
                        ],
                    }
                ],
            },
            "embedding": {"active_profile_id": None, "profiles": []},
            "search": {"active_profile_id": None, "profiles": []},
        },
    }

    rendered = service.apply(catalog)

    assert rendered["LLM_API_KEY"] == ""
    assert "LLM_API_KEY=\n" in env_path.read_text(encoding="utf-8")
    assert "stale-process-key" not in catalog_path.read_text(encoding="utf-8")
