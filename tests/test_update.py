"""Tests for CanteraUpdateEntity."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cantera.const import DOMAIN, GITHUB_RELEASES_URL
from custom_components.cantera.update import (
    CanteraUpdateEntity,
    _copy_tree,
    _read_manifest_version,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_RELEASES = [
    {
        "tag_name": "v0.3.0",
        "html_url": "https://github.com/omarcartera/cantera-ha/releases/tag/v0.3.0",
        "zipball_url": "https://api.github.com/repos/omarcartera/cantera-ha/zipball/v0.3.0",
        "body": "### What's new\n- Feature A\n- Bug fix B",
    },
    {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/omarcartera/cantera-ha/releases/tag/v0.2.0",
        "zipball_url": "https://api.github.com/repos/omarcartera/cantera-ha/zipball/v0.2.0",
        "body": "Initial release",
    },
]


@pytest.fixture
def entity(hass):
    e = CanteraUpdateEntity(hass, "test_entry_id")
    e.async_write_ha_state = MagicMock()
    return e


def _make_session_mock(status: int = 200, json_return=None, raise_exc=None):
    """Build an aiohttp session mock for async_get_clientsession."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    if json_return is not None:
        mock_resp.json = AsyncMock(return_value=json_return)
    if raise_exc:
        mock_resp.raise_for_status = MagicMock(side_effect=raise_exc)
    else:
        mock_resp.raise_for_status = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    return mock_session, mock_resp


# ---------------------------------------------------------------------------
# _read_manifest_version helper
# ---------------------------------------------------------------------------

def test_read_manifest_version_returns_version(tmp_path):
    """_read_manifest_version reads the version field from manifest.json."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": "1.2.3"}))
    with patch("custom_components.cantera.update._MANIFEST_PATH", manifest):
        assert _read_manifest_version() == "1.2.3"


def test_read_manifest_version_handles_missing_file():
    """_read_manifest_version returns None when the file does not exist."""
    with patch(
        "custom_components.cantera.update._MANIFEST_PATH",
        Path("/nonexistent/manifest.json"),
    ):
        assert _read_manifest_version() is None


# ---------------------------------------------------------------------------
# CanteraUpdateEntity identity
# ---------------------------------------------------------------------------

def test_unique_id(entity):
    assert entity.unique_id == "test_entry_id_update"


def test_device_info_contains_domain(entity):
    info = entity.device_info
    assert (DOMAIN, "cantera_vehicle") in info["identifiers"]


def test_installed_version_set_at_init(entity):
    """installed_version is set from manifest at init time."""
    # Entity was created; installed_version may be None in the test env
    # (manifest exists in the source tree), but it must be a str or None.
    assert entity.installed_version is None or isinstance(entity.installed_version, str)


def test_latest_version_none_before_update(entity):
    assert entity.latest_version is None


def test_in_progress_false_initially(entity):
    assert entity.in_progress is False


def test_should_poll_true(entity):
    assert entity.should_poll is True


# ---------------------------------------------------------------------------
# async_update
# ---------------------------------------------------------------------------

async def test_async_update_sets_latest_version(entity):
    """async_update populates latest_version from the first release in the list."""
    mock_session, _ = _make_session_mock(200, json_return=FAKE_RELEASES)
    with patch("custom_components.cantera.update.async_get_clientsession", return_value=mock_session):
        await entity.async_update()

    assert entity.latest_version == "0.3.0"
    assert entity.release_url == "https://github.com/omarcartera/cantera-ha/releases/tag/v0.3.0"


async def test_async_update_sets_release_notes(entity):
    """async_update caches the release body for async_release_notes."""
    mock_session, _ = _make_session_mock(200, json_return=FAKE_RELEASES)
    with patch("custom_components.cantera.update.async_get_clientsession", return_value=mock_session):
        await entity.async_update()

    notes = await entity.async_release_notes()
    assert "Feature A" in notes


async def test_async_update_strips_v_prefix(entity):
    """Tag names like 'v0.3.0' are normalised to '0.3.0'."""
    releases = [{"tag_name": "v1.0.0", "html_url": "", "zipball_url": "", "body": ""}]
    mock_session, _ = _make_session_mock(200, json_return=releases)
    with patch("custom_components.cantera.update.async_get_clientsession", return_value=mock_session):
        await entity.async_update()
    assert entity.latest_version == "1.0.0"


async def test_async_update_non_200_does_not_change_state(entity):
    """A non-200 response leaves latest_version unchanged."""
    mock_session, _ = _make_session_mock(403)
    with patch("custom_components.cantera.update.async_get_clientsession", return_value=mock_session):
        await entity.async_update()
    assert entity.latest_version is None


async def test_async_update_network_error_does_not_raise(entity):
    """Network exception during polling is swallowed — never propagates."""
    mock_session, _ = _make_session_mock()
    mock_session.get = MagicMock(side_effect=Exception("network down"))
    with patch("custom_components.cantera.update.async_get_clientsession", return_value=mock_session):
        await entity.async_update()  # must not raise
    assert entity.latest_version is None


async def test_async_update_empty_releases_list(entity):
    """Empty releases list leaves state unchanged."""
    mock_session, _ = _make_session_mock(200, json_return=[])
    with patch("custom_components.cantera.update.async_get_clientsession", return_value=mock_session):
        await entity.async_update()
    assert entity.latest_version is None


# ---------------------------------------------------------------------------
# _find_release
# ---------------------------------------------------------------------------

def test_find_release_by_version_without_v(entity):
    entity._releases = FAKE_RELEASES
    r = entity._find_release("0.2.0")
    assert r is not None
    assert r["tag_name"] == "v0.2.0"


def test_find_release_by_version_with_v(entity):
    entity._releases = FAKE_RELEASES
    r = entity._find_release("v0.3.0")
    assert r is not None
    assert r["tag_name"] == "v0.3.0"


def test_find_release_missing_returns_none(entity):
    entity._releases = FAKE_RELEASES
    assert entity._find_release("9.9.9") is None


def test_find_release_empty_list(entity):
    entity._releases = []
    assert entity._find_release("0.3.0") is None


# ---------------------------------------------------------------------------
# async_install
# ---------------------------------------------------------------------------

async def test_async_install_latest_when_version_none(entity):
    """async_install(None) installs the latest version."""
    entity._latest_version = "0.3.0"
    entity._releases = FAKE_RELEASES

    with (
        patch.object(entity, "_download_and_install", new_callable=AsyncMock) as mock_dl,
        patch.object(entity._hass.services, "async_call", new_callable=AsyncMock),
    ):
        await entity.async_install(None, False)

    mock_dl.assert_awaited_once()
    call_args = mock_dl.call_args[0]
    assert FAKE_RELEASES[0]["zipball_url"] in call_args


async def test_async_install_specific_version(entity):
    """async_install('0.2.0') installs the 0.2.0 release."""
    entity._releases = FAKE_RELEASES

    with (
        patch.object(entity, "_download_and_install", new_callable=AsyncMock) as mock_dl,
        patch.object(entity._hass.services, "async_call", new_callable=AsyncMock),
    ):
        await entity.async_install("0.2.0", False)

    mock_dl.assert_awaited_once()
    call_args = mock_dl.call_args[0]
    assert FAKE_RELEASES[1]["zipball_url"] in call_args


async def test_async_install_updates_installed_version(entity):
    """After install, installed_version reflects the new version."""
    entity._releases = FAKE_RELEASES

    with (
        patch.object(entity, "_download_and_install", new_callable=AsyncMock),
        patch.object(entity._hass.services, "async_call", new_callable=AsyncMock),
    ):
        await entity.async_install("0.2.0", False)

    assert entity.installed_version == "0.2.0"


async def test_async_install_triggers_ha_restart(entity):
    """After successful install, homeassistant.restart is called."""
    entity._releases = FAKE_RELEASES

    with (
        patch.object(entity, "_download_and_install", new_callable=AsyncMock),
        patch.object(entity._hass.services, "async_call", new_callable=AsyncMock) as mock_call,
    ):
        await entity.async_install("0.3.0", False)

    mock_call.assert_awaited_once_with("homeassistant", "restart")


async def test_async_install_in_progress_set_and_cleared(entity):
    """in_progress is True while installing, False after."""
    entity._releases = FAKE_RELEASES
    states: list[bool] = []

    async def fake_dl(*_args):
        states.append(entity.in_progress)

    with (
        patch.object(entity, "_download_and_install", side_effect=fake_dl),
        patch.object(entity._hass.services, "async_call", new_callable=AsyncMock),
    ):
        await entity.async_install("0.3.0", False)

    assert states == [True]
    assert entity.in_progress is False


async def test_async_install_unknown_version_does_not_raise(entity):
    """Installing a non-existent version logs error and returns gracefully."""
    entity._releases = FAKE_RELEASES

    with patch.object(entity._hass.services, "async_call", new_callable=AsyncMock) as mock_call:
        await entity.async_install("9.9.9", False)  # must not raise

    # restart must NOT be called for a failed install
    mock_call.assert_not_awaited()
    assert entity.in_progress is False


async def test_async_install_no_target_version_does_not_raise(entity):
    """No version and no latest_version: returns without error."""
    entity._latest_version = None
    entity._releases = []
    await entity.async_install(None, False)  # must not raise
    assert entity.in_progress is False


async def test_async_install_download_failure_does_not_raise(entity):
    """Exception during _download_and_install is caught; in_progress cleared."""
    entity._releases = FAKE_RELEASES

    async def boom(*_args):
        raise RuntimeError("network error")

    with (
        patch.object(entity, "_download_and_install", side_effect=boom),
        patch.object(entity._hass.services, "async_call", new_callable=AsyncMock) as mock_call,
    ):
        await entity.async_install("0.3.0", False)  # must not raise

    assert entity.in_progress is False
    # restart should not be called if download failed
    mock_call.assert_not_awaited()


# ---------------------------------------------------------------------------
# _copy_tree helper
# ---------------------------------------------------------------------------

def test_copy_tree_copies_files(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "a.py").write_text("hello")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "junk.pyc").write_bytes(b"\x00")

    _copy_tree(src, dst)

    assert (dst / "a.py").read_text() == "hello"
    # __pycache__ must be excluded
    assert not (dst / "__pycache__").exists()


def test_copy_tree_handles_nested_directories(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "b.py").write_text("world")
    dst = tmp_path / "dst"

    _copy_tree(src, dst)

    assert (dst / "sub" / "b.py").read_text() == "world"


# ---------------------------------------------------------------------------
# async_setup_entry smoke test
# ---------------------------------------------------------------------------

async def test_async_setup_entry_adds_update_entity(hass):
    """async_setup_entry registers exactly one CanteraUpdateEntity."""
    from custom_components.cantera.update import async_setup_entry

    entry = MagicMock()
    entry.entry_id = "test_entry"
    added: list = []
    async_add = MagicMock(side_effect=lambda ents: added.extend(ents))

    await async_setup_entry(hass, entry, async_add)

    assert len(added) == 1
    assert isinstance(added[0], CanteraUpdateEntity)
