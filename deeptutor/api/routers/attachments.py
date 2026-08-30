"""HTTP endpoint for chat attachment downloads / previews.

The chat turn runtime persists every uploaded attachment to the
:class:`~deeptutor.services.storage.AttachmentStore` and records the public
URL on the message. The frontend preview drawer loads files via this
router, which only serves paths the store hands back — every component is
sanitised to defend against directory traversal.

URL shape::

    GET /api/attachments/{session_id}/{attachment_id}/{filename}

The request-local user workspace and its session database are the ACL
boundary. A path alone is never authority: the requested attachment id must
also be referenced by a message or notebook entry in that user's session.
"""

from __future__ import annotations

import logging
import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.storage import (
    LocalDiskAttachmentStore,
    get_attachment_store,
)
from deeptutor.services.storage.attachment_validation import (
    AttachmentValidationError,
    validate_attachment_id,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_ACTIVE_ATTACHMENT_MEDIA_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/xml",
        "application/xml",
        "application/xslt+xml",
        "text/xsl",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/ecmascript",
    }
)


def _content_disposition(filename: str, *, disposition: str = "inline") -> str:
    """Build a Content-Disposition header that survives non-ASCII filenames.

    HTTP/1.1 headers are latin-1, so dropping a Chinese / accented filename
    straight into ``filename="..."`` blows up with UnicodeEncodeError. RFC
    6266 / RFC 5987 cover this: emit ``filename*=UTF-8''<percent-encoded>``
    plus an ASCII fallback on ``filename=`` for legacy clients.
    """
    ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii")
    # Quotes / backslashes break the simple-quoted-string form; collapse them.
    ascii_fallback = ascii_fallback.replace('"', "_").replace("\\", "_")
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


@router.get("/{session_id}/{attachment_id}/{filename:path}")
async def get_attachment(
    session_id: str,
    attachment_id: str,
    filename: str,
):
    """Serve a previously uploaded chat attachment.

    The request-local session store is the ownership authority. A filename
    that merely exists on disk is insufficient: the attachment id must be
    referenced by a message or notebook entry in the caller's session.
    """
    try:
        validate_attachment_id(attachment_id, label="attachment")
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=404, detail="Attachment not found") from exc

    session_store = get_sqlite_session_store()
    if not await session_store.attachment_is_referenced(session_id, attachment_id):
        raise HTTPException(status_code=404, detail="Attachment not found")

    store = get_attachment_store()
    if not isinstance(store, LocalDiskAttachmentStore):
        # Future remote backends should issue a redirect to the signed URL
        # here. Local-disk is the only backend today, so this branch just
        # guards against an unexpected configuration.
        raise HTTPException(status_code=501, detail="Attachment backend not servable")

    target = store.resolve_path(
        session_id=session_id,
        attachment_id=attachment_id,
        filename=filename,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    media_type, _ = mimetypes.guess_type(target.name)
    if not media_type:
        media_type = "application/octet-stream"

    # ``inline`` lets the browser preview the file when possible while still
    # honouring the suggested filename for the drawer's download action.
    headers = {
        "Content-Disposition": _content_disposition(target.name),
        # User-uploaded data; do not let intermediaries cache it.
        "Cache-Control": "private, max-age=0, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }
    if media_type in _ACTIVE_ATTACHMENT_MEDIA_TYPES:
        # User-controlled active documents must never execute under the
        # authenticated application origin, even when previewed from history.
        media_type = "application/octet-stream"
        headers["Content-Disposition"] = _content_disposition(target.name, disposition="attachment")
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return FileResponse(path=str(target), media_type=media_type, headers=headers)
