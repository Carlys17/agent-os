"""The X Search onboarding descriptor and the catalog shape the WebUI consumes."""

from __future__ import annotations

from typing import Any, get_args

from agentos.gateway.config import XSearchConfig
from agentos.onboarding.setup_engine import setup_catalog_payload
from agentos.onboarding.x_search_specs import (
    X_SEARCH_ENV_KEY,
    get_x_search_setup_spec,
    x_search_catalog_payload,
)


def _fields_by_name() -> dict[str, Any]:
    return {field.name: field for field in get_x_search_setup_spec().fields}


def test_the_spec_advertises_the_api_key_env_the_runtime_reads() -> None:
    spec = get_x_search_setup_spec()
    assert spec.env_key == X_SEARCH_ENV_KEY == XSearchConfig().api_key_env
    assert spec.requires_api_key is True


def test_every_field_default_matches_the_config_model() -> None:
    """The form must not advertise a default the gateway would not apply."""
    defaults = XSearchConfig()
    fields = _fields_by_name()
    assert fields["model"].default == defaults.model
    assert fields["base_url"].default == defaults.base_url
    assert fields["retries"].default == defaults.retries
    assert fields["timeout_seconds"].default == int(defaults.timeout_seconds)
    assert fields["total_timeout_seconds"].default == int(defaults.total_timeout_seconds)


def test_the_effort_choices_come_from_the_validating_literal() -> None:
    allowed = set(get_args(XSearchConfig.model_fields["reasoning_effort"].annotation))
    assert set(_fields_by_name()["reasoning_effort"].choices) == allowed


def test_the_api_key_field_is_marked_secret() -> None:
    api_key = _fields_by_name()["api_key"]
    assert api_key.secret is True
    assert api_key.field_type == "password"


def test_the_catalog_section_is_a_list_like_every_other_section() -> None:
    """The WebUI and the CLI renderer both walk catalog sections as rows."""
    payload = setup_catalog_payload()
    rows = payload["xSearch"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]
    assert row["providerId"] == "x_search"
    assert row["envKey"] == X_SEARCH_ENV_KEY
    assert row["requiresApiKey"] is True
    assert isinstance(row["fields"], list)
    assert {"name", "type", "default", "choices", "secret"} <= set(row["fields"][0])


def test_the_section_is_reachable_by_each_alias() -> None:
    for alias in ("x-search", "x_search", "xsearch"):
        assert setup_catalog_payload(alias) == {"xSearch": x_search_catalog_payload()}


def test_oauth_is_called_out_as_unsupported() -> None:
    """Hermes Agent accepts SuperGrok OAuth; arriving from its docs should not confuse."""
    assert any("OAuth" in line for line in get_x_search_setup_spec().what_you_need)
