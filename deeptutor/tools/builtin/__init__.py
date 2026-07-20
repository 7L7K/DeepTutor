"""Built-in tool registry exports.

This checkout currently lacks the concrete built-in tool implementations. The
question generator only needs the registry to exist when Practice tools are
disabled, so keep the export contract intact with an empty built-in set.
"""

BUILTIN_TOOL_TYPES = []
TOOL_ALIASES = {}

__all__ = ["BUILTIN_TOOL_TYPES", "TOOL_ALIASES"]
