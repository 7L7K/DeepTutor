"""Per-user tool and exec access resolution (grant v2).

Optional built-in tools are deny-by-default for real non-admin users: an
absent, null, or empty grant means no optional tools, while a set is an
explicit administrator-managed whitelist. Administrators remain unrestricted.
Synthetic scopes (partners) are handled by the chat pipeline,
where their owner-scoped whitelist travels through context metadata
(``mcp_tools_filter`` / ``enabled_tools``).

Enforcement points:

* ``allowed_optional_tools`` — turn_runtime filters every turn's ``tools``
  payload (single choke point for all capabilities), and the tools router
  filters the /settings/tools listing so the UI matches.
* ``allowed_builtin_tools`` — turn_runtime owns the server-side allowlist for
  auto-mounted built-ins such as ``web_fetch``; a client payload cannot widen
  this surface.
* ``allowed_mcp_tools`` — the chat pipeline intersects this with any
  caller-scoped ``mcp_tools_filter`` before building the deferred-tool
  loader, so a granted-away MCP tool can be neither listed nor loaded. For
  real non-admin users, missing ``mcp_tools`` means no MCP tools are listed
  or loadable until an admin grants specific names.
* ``allowed_cli_apps`` — the provider that turns installed CLI apps into
  deferred tools intersects this with the account's own enable/disable
  preference. Same deny-by-default posture as MCP, for the same reason: an
  installed app runs third-party code inside the sandbox.
* ``exec_override`` — resolves execution permission for a real user. An
  administrator remains unrestricted; every other account is deny-by-default
  until an administrator explicitly grants execution.
"""

from __future__ import annotations

from .context import get_current_user
from .grants import load_grant


def _current_grant() -> dict | None:
    """The current user's grant, or ``None`` when unrestricted (admin)."""
    user = get_current_user()
    if user.is_admin:
        return None
    return load_grant(user.id)


def allowed_optional_tools() -> set[str] | None:
    """Whitelist of user-toggleable tools; only admins are unrestricted."""
    grant = _current_grant()
    if grant is None:
        return None
    value = grant.get("enabled_tools")
    if value is None:
        return set()
    return {str(name) for name in value}


def allowed_builtin_tools() -> set[str] | None:
    """Whitelist of auto-mounted built-in tools.

    ``None`` means unrestricted and is reserved for administrators. Every
    real non-admin account fails closed when its grant omits ``builtin_tools``;
    this is intentionally separate from ``enabled_tools`` because an optional
    composer setting must not authorize a server-mounted network or workspace
    tool.
    """
    grant = _current_grant()
    if grant is None:
        return None
    value = grant.get("builtin_tools")
    if value is None:
        return set()
    return {str(name) for name in value}


def allowed_mcp_tools() -> set[str] | None:
    """Whitelist of MCP (deferred) tool names.

    ``None`` means unrestricted and is reserved for administrators. Real
    non-admin users fail closed when the grant omits ``mcp_tools`` so a chat
    turn cannot discover or load deployment-wide MCP host tools until an admin
    explicitly grants the tool names.
    """
    grant = _current_grant()
    if grant is None:
        return None
    value = grant.get("mcp_tools")
    if value is None:
        return set()
    return {str(name) for name in value}


def allowed_cli_apps() -> set[str] | None:
    """Whitelist of installed CLI app ids this caller may invoke.

    ``None`` means unrestricted and is reserved for administrators. Every other
    account fails closed when the grant omits ``cli_apps``: an installed app is
    third-party code, and the deployment installing one is not the same decision
    as every account being able to run it.
    """
    grant = _current_grant()
    if grant is None:
        return None
    value = grant.get("cli_apps")
    if value is None:
        return set()
    return {str(name) for name in value}


def exec_override() -> bool | None:
    """Effective per-user execution permission.

    ``None`` remains reserved for administrators (unrestricted subject to
    backend isolation). A non-admin must carry an explicit
    ``exec_enabled=True`` grant; absent, malformed, and false values all deny.
    This prevents a deployment-wide sandbox from implicitly granting shell or
    code execution to every learner.
    """
    grant = _current_grant()
    if grant is None:
        return None
    value = grant.get("exec_enabled")
    return value if isinstance(value, bool) else False


def combine_whitelists(caller: set[str] | None, user: set[str] | None) -> set[str] | None:
    """Intersect two optional whitelists; ``None`` = unrestricted."""
    if caller is None:
        return user
    if user is None:
        return caller
    return caller & user


__all__ = [
    "allowed_cli_apps",
    "allowed_builtin_tools",
    "allowed_mcp_tools",
    "allowed_optional_tools",
    "combine_whitelists",
    "exec_override",
]
