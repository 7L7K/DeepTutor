"""
CLI apps API
============

Mounted at ``/api/v1/space/cli-apps``. This is an administrator-only
deployment-management surface:

* **administrators only** — reading the catalog, installing or removing an app,
  and changing the deployment's installed-app state.

The whole router is admin-gated because CLI Apps are an advanced deployment
surface, not a learner-facing preference. This prevents a regular account from
discovering the catalog or reaching the page through a direct API call. The
chat runtime still resolves any explicitly granted app through
``cli_apps.provider``; this change only closes the management surface.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deeptutor.api.routers.auth import require_admin
from deeptutor.core.i18n import t
from deeptutor.multi_user.paths import current_owner_id
from deeptutor.multi_user.tool_access import allowed_cli_apps, exec_override
from deeptutor.services.cli_apps import (
    CliAppEntry,
    catalog_pin,
    category_counts,
    get_entry,
    search_catalog,
)
from deeptutor.services.cli_apps.models import TOOL_PREFIX
from deeptutor.services.cli_apps.state import (
    InstalledApp,
    disabled_apps,
    load_installed,
    set_app_enabled,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_admin)])


class EnabledPayload(BaseModel):
    enabled: bool


@router.get("/apps")
async def list_apps() -> dict[str, Any]:
    """Installed apps as *this* caller sees them."""
    owner = current_owner_id()
    installed = load_installed()
    granted = allowed_cli_apps()
    off = disabled_apps(owner)
    exec_allowed = exec_override()

    rows = [
        _app_row(app, granted=granted, disabled=off)
        for app in (installed[app_id] for app_id in sorted(installed))
    ]
    return {
        "apps": rows,
        # Why the list may be unusable even though it is not empty. Reported as a
        # field rather than left for the reader to infer from every row being
        # `granted: false`.
        "access": {
            "unrestricted": granted is None,
            "exec_denied": exec_allowed is False,
        },
        "catalog_pin": catalog_pin(),
    }


@router.put("/apps/{app_id}/enabled")
async def set_enabled(app_id: str, payload: EnabledPayload) -> dict[str, Any]:
    """Switch one app on or off for the calling account.

    Refused for an app the caller has not been granted: the preference file must
    not become a way to record interest in something the grant denies, because a
    later grant would then silently switch it on.
    """
    owner = current_owner_id()
    installed = load_installed()
    if app_id not in installed:
        raise HTTPException(status_code=404, detail=t("cli_apps.not_installed", app=app_id))
    granted = allowed_cli_apps()
    if granted is not None and app_id not in granted:
        raise HTTPException(
            status_code=403,
            detail={"code": "cli.not_granted", "message": t("cli_apps.entry_admin_only")},
        )
    set_app_enabled(owner, app_id, payload.enabled)
    return await list_apps()


@router.get("/catalog")
async def get_catalog(
    q: str = "",
    category: str = "",
    installable_only: bool = True,
    cursor: str = "",
    limit: int = 24,
) -> dict[str, Any]:
    """The store. Readable by anyone; installing is admin-only."""
    installed = load_installed()
    page = search_catalog(
        q=q,
        category=category,
        installable_only=installable_only,
        cursor=cursor,
        limit=limit,
    )
    return {
        "entries": [_catalog_row(entry, installed) for entry in page.entries],
        "next_cursor": page.next_cursor,
        "total": page.total,
        "categories": category_counts(q=q, installable_only=installable_only),
        "catalog_pin": catalog_pin(),
    }


@router.post("/catalog/{app_id}/install")
async def install(app_id: str) -> dict[str, Any]:
    """Install one app for the deployment. Administrator only."""
    entry = get_entry(app_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=t("cli_apps.not_in_catalog", id=app_id))

    from deeptutor.services.cli_apps.installer import install_app

    outcome = await install_app(entry)
    if not outcome.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "code": outcome.code or "cli.install_failed",
                "message": outcome.message,
                # The install output is the only actionable thing about a failed
                # install, so it travels with the refusal instead of only landing
                # in a log file on the server.
                "log": outcome.log,
            },
        )
    state = await list_apps()
    state["log"] = outcome.log
    return state


@router.delete("/apps/{app_id}")
async def uninstall(app_id: str) -> dict[str, Any]:
    """Remove one app from the deployment. Administrator only."""
    from deeptutor.services.cli_apps.installer import uninstall_app

    await uninstall_app(app_id)
    return await list_apps()


def _app_row(app: InstalledApp, *, granted: set[str] | None, disabled: set[str]) -> dict[str, Any]:
    entry = get_entry(app.id)
    is_granted = granted is None or app.id in granted
    return {
        "id": app.id,
        "display_name": entry.display_name if entry else app.id,
        "description": entry.description if entry else "",
        "category": entry.category if entry else "",
        "tool_name": f"{TOOL_PREFIX}{app.id}",
        "entry_point": app.entry_point,
        "runtime": app.runtime.value,
        "installed_at": app.installed_at,
        "version": app.version,
        "pin": app.pin,
        "trust": entry.trust.value if entry else "third-party",
        "granted": is_granted,
        # Only meaningful when granted; a denied app reports enabled=false so the
        # UI never shows an "on" switch for something that cannot run.
        "enabled": is_granted and app.id not in disabled,
        # An app still installed but no longer in the snapshot: an admin can
        # remove it, and the chat agent is not offered it.
        "in_catalog": entry is not None,
    }


def _catalog_row(entry: CliAppEntry, installed: dict[str, InstalledApp]) -> dict[str, Any]:
    return {
        "id": entry.id,
        "display_name": entry.display_name,
        "description": entry.description,
        "category": entry.category,
        "origin": entry.origin,
        "trust": entry.trust.value,
        "requires": entry.requires,
        "homepage": entry.homepage,
        "source_url": entry.source_url,
        "entry_point": entry.entry_point,
        "runtime": entry.install.runtime.value,
        "install_kind": entry.install.kind.value,
        "install_target": entry.install.target,
        "installable": entry.install.installable,
        "pinned": entry.install.pinned,
        # Present only when it is not installable, and written for a person: it
        # is the difference between "we did not get to this one" and "its
        # published install command is a shell script we will not run".
        "unsupported_reason": entry.install.reason,
        "install_notes": entry.install_notes,
        "installed": entry.id in installed,
    }


__all__ = ["router"]
