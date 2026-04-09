"""Update entity for the CANtera integration.

Polls the GitHub releases API every hour, surfaces a standard HA
"Update Available" notification, and allows the user to install any
published release (including choosing a specific version) directly from
the HA UI.

Installation flow
-----------------
1. Download the release zipball from GitHub.
2. Overwrite the running ``custom_components/cantera/`` directory with the
   new files (skipping ``__pycache__``).
3. Reload the config entry so the new code is loaded without a full HA restart.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re as _re
import shutil
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path

import aiohttp
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    GITHUB_API_HEADERS,
    GITHUB_RELEASES_URL,
    GITHUB_TAGS_URL,
)

_LOGGER = logging.getLogger(__name__)

# Check GitHub once per hour — well within their 60 req/h unauthenticated limit.
SCAN_INTERVAL = timedelta(hours=1)

_SEMVER_RE = _re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')


def _is_semver(tag: str) -> bool:
    """Return True if *tag* is a plain semver string (vX.Y.Z or X.Y.Z)."""
    return bool(_SEMVER_RE.match(tag))


def _semver_key(tag: str) -> tuple[int, int, int]:
    """Return a comparable tuple for a semver tag string."""
    m = _SEMVER_RE.match(tag)
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

_MANIFEST_PATH = Path(__file__).parent / "manifest.json"


def _read_manifest_version() -> str | None:
    """Read the ``version`` field from this integration's manifest.json."""
    try:
        with _MANIFEST_PATH.open() as fh:
            return json.load(fh).get("version")
    except Exception:
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the CANtera update entity for this config entry."""
    entity = CanteraUpdateEntity(hass, entry.entry_id)
    # update_before_add=True forces an immediate GitHub poll so the entity
    # shows the correct version on first load instead of "Unknown" for the
    # first hour of the polling interval.
    async_add_entities([entity], update_before_add=True)

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if "current_unique_ids" in entry_data and entity.unique_id:
        entry_data["current_unique_ids"].add(entity.unique_id)


class CanteraUpdateEntity(UpdateEntity):
    """Tracks available releases of the CANtera integration on GitHub.

    Features
    --------
    * **INSTALL** — the "Install" button triggers :meth:`async_install`.
    * **SPECIFIC_VERSION** — the user can type any release tag (e.g. ``0.2.1``)
      to install that exact version instead of the latest.
    * **RELEASE_NOTES** — HA fetches the GitHub release body and displays it
      in the "What's new" panel.
    """

    _attr_name = "CANtera Integration"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.SPECIFIC_VERSION
        | UpdateEntityFeature.RELEASE_NOTES
    )
    should_poll = True

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._installed_version: str | None = _read_manifest_version()
        self._latest_version: str | None = None
        self._releases: list[dict] = []
        self._release_notes_cache: str | None = None
        self._release_url_cache: str | None = None
        self._in_progress: bool = False

    # ------------------------------------------------------------------ #
    # Entity identity                                                       #
    # ------------------------------------------------------------------ #

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_update"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"cantera_vehicle_{self._entry_id}")},
            name="CANtera OBD-II",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    # ------------------------------------------------------------------ #
    # UpdateEntity required properties                                      #
    # ------------------------------------------------------------------ #

    @property
    def installed_version(self) -> str | None:
        return self._installed_version

    @property
    def latest_version(self) -> str | None:
        return self._latest_version

    @property
    def release_url(self) -> str | None:
        return self._release_url_cache

    @property
    def in_progress(self) -> bool:
        return self._in_progress

    # ------------------------------------------------------------------ #
    # Polling                                                               #
    # ------------------------------------------------------------------ #

    async def async_update(self) -> None:
        """Fetch releases (or tags as fallback) from GitHub and update state.

        Tries the releases API first.  When no releases are published yet,
        falls back to the tags API so the version is never stuck at Unknown.
        Failures are logged but never propagate.
        """
        session = async_get_clientsession(self._hass)
        try:
            async with session.get(
                GITHUB_RELEASES_URL,
                headers=GITHUB_API_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "GitHub releases API returned HTTP %d", resp.status
                    )
                    return
                self._releases = await resp.json()
        except Exception:
            _LOGGER.exception("Failed to fetch CANtera releases from GitHub")
            return

        if self._releases:
            latest = self._releases[0]
            tag = latest.get("tag_name", "").lstrip("v")
            self._latest_version = tag or None
            self._release_notes_cache = latest.get("body") or None
            self._release_url_cache = latest.get("html_url") or None
            return

        # No GitHub releases published yet — fall back to the tags API so
        # latest_version is still resolved (avoids "Unknown" in the UI).
        _LOGGER.debug("No GitHub releases found; falling back to tags API")
        try:
            async with session.get(
                GITHUB_TAGS_URL,
                headers=GITHUB_API_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "GitHub tags API returned HTTP %d", resp.status
                    )
                    return
                tags: list[dict] = await resp.json()
        except Exception:
            _LOGGER.exception("Failed to fetch CANtera tags from GitHub")
            return

        semver_tags = [t for t in tags if _is_semver(t.get("name", ""))]
        if not semver_tags:
            return

        semver_tags.sort(key=lambda t: _semver_key(t["name"]), reverse=True)
        latest_tag = semver_tags[0]
        tag_name = latest_tag["name"]
        version = tag_name.lstrip("v")
        self._latest_version = version
        self._release_notes_cache = None
        self._release_url_cache = (
            f"https://github.com/omarcartera/cantera-ha/releases/tag/{tag_name}"
        )
        # Normalise tag entries into release-shaped dicts so _find_release
        # and async_install work without changes.
        self._releases = [
            {
                "tag_name": t["name"],
                "zipball_url": t.get("zipball_url"),
                "body": None,
                "html_url": (
                    f"https://github.com/omarcartera/cantera-ha/releases/tag/{t['name']}"
                ),
            }
            for t in semver_tags
        ]

    # ------------------------------------------------------------------ #
    # Release notes (called by HA when user opens "What's new")            #
    # ------------------------------------------------------------------ #

    async def async_release_notes(self) -> str | None:
        """Return the GitHub release body for the latest release."""
        return self._release_notes_cache

    # ------------------------------------------------------------------ #
    # Installation                                                          #
    # ------------------------------------------------------------------ #

    async def async_install(
        self, version: str | None, backup: bool, **kwargs
    ) -> None:
        """Download and install a specific (or the latest) integration version.

        Parameters
        ----------
        version:
            Release tag to install (without leading ``v``). When *None* the
            latest release is installed.
        backup:
            Ignored — there is no meaningful backup to take for a custom
            component.
        """
        self._in_progress = True
        self.async_write_ha_state()
        try:
            target = (version or self._latest_version or "").lstrip("v")
            if not target:
                _LOGGER.error("No target version available to install")
                return

            release = self._find_release(target)
            if release is None:
                _LOGGER.error(
                    "CANtera release '%s' not found in GitHub release list", target
                )
                return

            zipball_url = release.get("zipball_url")
            if not zipball_url:
                _LOGGER.error("Release '%s' has no zipball_url", target)
                return

            _LOGGER.info("Installing CANtera integration version %s …", target)
            install_dir = Path(__file__).parent
            await self._download_and_install(zipball_url, install_dir)

            # Update in-memory version so the entity reflects the change
            # immediately. The config-entry reload below recreates all entities
            # — no full HA restart is required or triggered.
            self._installed_version = target
            _LOGGER.info("CANtera integration version %s installed; reloading config entry", target)
            await self._hass.config_entries.async_reload(self._entry_id)

        except Exception:
            _LOGGER.exception("CANtera update installation failed")
        finally:
            self._in_progress = False
            self.async_write_ha_state()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _find_release(self, version: str) -> dict | None:
        """Return the release dict matching *version* (with or without ``v`` prefix)."""
        normalised = version.lstrip("v")
        for release in self._releases:
            tag = release.get("tag_name", "").lstrip("v")
            if tag == normalised:
                return release
        return None

    async def _download_and_install(
        self, zipball_url: str, install_dir: Path
    ) -> None:
        """Download the release zipball and atomically replace the integration directory.

        The install is two-phase:

        1. Download → extract → copy into a *staging* directory that lives
           alongside the real install directory (same filesystem → rename is
           instant and atomic on Linux/macOS).
        2. Rename current install dir to ``<name>.bak``, rename staging to the
           real name, then delete the backup.

        If anything fails before step 2, the live integration is untouched.
        If anything fails after step 2, the backup remains for manual recovery.
        """
        staging = install_dir.parent / f"{install_dir.name}.install_staging"
        backup = install_dir.parent / f"{install_dir.name}.install_backup"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "release.zip"

            # Download with redirect support (GitHub redirects to S3).
            session = async_get_clientsession(self._hass)
            async with session.get(
                zipball_url,
                headers=GITHUB_API_HEADERS,
                timeout=aiohttp.ClientTimeout(total=120),
                allow_redirects=True,
            ) as resp:
                resp.raise_for_status()
                zip_path.write_bytes(await resp.read())

            extracted = tmp_path / "extracted"
            extracted.mkdir()
            extraction_root = extracted.resolve()
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.namelist():
                    member_path = (extracted / member).resolve()
                    if not str(member_path).startswith(str(extraction_root)):
                        raise ValueError(
                            f"Zip-slip detected: {member!r} would escape extraction dir"
                        )
                zf.extractall(extracted)

            # GitHub archives wrap everything in a top-level directory
            # (e.g. ``omarcartera-cantera-ha-abc1234/``).  Find the
            # ``cantera/`` subdirectory anywhere inside the tree.
            src = None
            for candidate in extracted.rglob("manifest.json"):
                if candidate.parent.name == "cantera":
                    src = candidate.parent
                    break

            if src is None:
                raise FileNotFoundError(
                    "Cannot locate custom_components/cantera/ inside the release archive"
                )

            # Phase 1: copy into staging (any failure here leaves live dir intact).
            if staging.exists():
                await asyncio.get_running_loop().run_in_executor(
                    None, shutil.rmtree, staging
                )
            await asyncio.get_running_loop().run_in_executor(
                None, _copy_tree, src, staging
            )

        # Phase 2: atomic swap (rename within same parent directory).
        # Both renames are near-instantaneous; the window where neither copy
        # exists is essentially zero on Linux.
        if backup.exists():
            await asyncio.get_running_loop().run_in_executor(
                None, shutil.rmtree, backup
            )
        if install_dir.exists():
            install_dir.rename(backup)
        staging.rename(install_dir)
        # Remove backup asynchronously — failure here is non-fatal.
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, shutil.rmtree, backup
            )
        except Exception:
            _LOGGER.warning(
                "Could not remove install backup at %s — safe to delete manually", backup
            )


def _copy_tree(src: Path, dst: Path) -> None:
    """Recursively copy *src* into *dst*, skipping ``__pycache__``."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name == "__pycache__":
            continue
        target = dst / item.name
        if item.is_dir():
            _copy_tree(item, target)
        else:
            shutil.copy2(item, target)
