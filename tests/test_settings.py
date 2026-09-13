"""T-C3 — the preprod network guard (NFR-7)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from batcher.config.settings import Settings, SettingsError, load_settings


def test_preprod_loads():
    settings = load_settings({"CARDANO_NETWORK": "preprod", "BLOCKFROST_PROJECT_ID": "x"})
    assert settings.cardano_network == "preprod"


def test_load_settings_reads_the_process_environment(monkeypatch):
    """The default path: no explicit mapping, so .env and os.environ are consulted."""
    monkeypatch.setenv("CARDANO_NETWORK", "preprod")
    monkeypatch.setenv("BLOCKFROST_PROJECT_ID", "token")

    settings = load_settings()

    assert settings.cardano_network == "preprod"
    assert settings.blockfrost_project_id == "token"


def test_the_guard_applies_to_the_process_environment_too(monkeypatch):
    monkeypatch.setenv("CARDANO_NETWORK", "mainnet")
    with pytest.raises(SettingsError):
        load_settings()


def test_network_defaults_to_preprod_when_unset():
    assert load_settings({}).cardano_network == "preprod"


@pytest.mark.parametrize("network", ["mainnet", "preview", "PREPROD", "", "testnet"])
def test_any_other_network_raises(network):
    """T-C3 — loading settings with any other network raises."""
    with pytest.raises(SettingsError):
        load_settings({"CARDANO_NETWORK": network})


def test_the_guard_cannot_be_bypassed_by_constructing_settings_directly():
    with pytest.raises(SettingsError):
        Settings(
            cardano_network="mainnet",
            blockfrost_project_id=None,
            batcher_key_dir=Path("."),
        )


def test_settings_are_immutable_after_construction():
    settings = load_settings({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.cardano_network = "mainnet"


def test_replacing_the_network_on_a_valid_instance_raises():
    settings = load_settings({})
    with pytest.raises(SettingsError):
        dataclasses.replace(settings, cardano_network="mainnet")


def test_key_dir_is_expanded_and_outside_the_repository():
    settings = load_settings({"BATCHER_KEY_DIR": "~/.cardano-batcher"})
    assert "~" not in str(settings.batcher_key_dir)
    assert settings.batcher_key_dir.is_absolute()
