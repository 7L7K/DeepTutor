"""AI judge WebSocket — grades a learner's quiz answer.

Mounted on its own (without router-level HTTP auth dependencies) because
WebSocket upgrades cannot use FastAPI's HTTP dependency injection, so we
rely on ``ws_require_auth`` inside the handler — mirroring the pattern
used by ``unified_ws``.
"""

from __future__ import annotations

import asyncio
import base64 as _b64
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.llm import stream as llm_stream
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota
from deeptutor.services.settings.interface_settings import get_ui_language

logger = logging.getLogger(__name__)
_config = load_config_with_main("main.yaml", PROJECT_ROOT)

router = APIRouter()

# A judge socket performs exactly one provider-backed request, so clients have
# no legitimate reason to leave it unauthenticated-but-idle indefinitely.
_INITIAL_REQUEST_TIMEOUT_SECONDS = 60.0

# A judge request makes a billable provider call. Keep the admission control
# process-local like the rest of this single-container deployment and hold a
# permit for the whole stream so a learner cannot create parallel calls by
# opening more sockets.
_JUDGE_REQUEST_QUOTA = UserExecQuota(max_concurrent=1, max_per_minute=12)
_JUDGE_GLOBAL_QUOTA = UserExecQuota(max_concurrent=4, max_per_minute=48)
_JUDGE_GLOBAL_QUOTA_KEY = "quiz-judge-global"
_MAX_JUDGE_QUESTION_CHARS = 12_000
_MAX_JUDGE_ANSWER_CHARS = 12_000
_MAX_JUDGE_REFERENCE_CHARS = 12_000
_MAX_JUDGE_EXPLANATION_CHARS = 24_000
_MAX_JUDGE_OPTION_COUNT = 12
_MAX_JUDGE_OPTION_CHARS = 2_000
_MAX_JUDGE_FILENAME_CHARS = 255


_JUDGE_SYSTEM_PROMPTS = {
    "zh": (
        "你是一名严谨且鼓励学习者的助教，正在批改一道测验题。"
        "请基于题目、参考答案与解析，对学习者的作答给出针对性的判定与反馈。\n\n"
        "回答要求：\n"
        "- 先用一行明确结论：✅ 正确 / ⚠️ 部分正确 / ❌ 不正确，并简短点明关键判定依据。\n"
        "- 然后分条列出：哪里做对了、哪里出错或缺漏、应该如何改正。\n"
        "- 若题目本身有多种合理答案，请承认学习者的合理之处。\n"
        "- 直接以学习者的作答为对象，不要泛泛而谈。\n"
        "- 全程使用中文。"
    ),
    "en": (
        "You are a rigorous yet encouraging teaching assistant grading a learner's quiz answer. "
        "Use the question, reference answer, and explanation to deliver a targeted assessment.\n\n"
        "Requirements:\n"
        "- Open with one line that states the verdict: ✅ Correct / ⚠️ Partially correct / ❌ Incorrect, "
        "and the key reason.\n"
        "- Then list: what the learner got right, what is wrong or missing, and how to fix it.\n"
        "- If multiple reasonable answers exist, acknowledge what the learner did well.\n"
        "- Speak directly to the learner's submission — do not give a generic lecture.\n"
        "- Reply in English."
    ),
}


def _build_judge_user_prompt(
    *,
    language: str,
    question: str,
    question_type: str,
    options: dict | None,
    correct_answer: str,
    explanation: str,
    user_answer: str,
    has_image: bool,
    image_count: int = 0,
) -> str:
    options_block = ""
    if options:
        try:
            options_block = "\n".join(f"  {k}. {v}" for k, v in options.items())
        except Exception:
            options_block = ""
    if language == "zh":
        parts = [
            f"题目类型：{question_type or 'unknown'}",
            f"题干：\n{question}",
        ]
        if options_block:
            parts.append(f"选项：\n{options_block}")
        if correct_answer:
            parts.append(f"参考答案：\n{correct_answer}")
        if explanation:
            parts.append(f"参考解析：\n{explanation}")
        parts.append(
            "学习者作答：\n"
            + (
                user_answer.strip()
                if user_answer and user_answer.strip()
                else "（仅提交了图片，无文字作答）"
            )
        )
        if has_image:
            count_text = (
                f"学习者另附了 {image_count} 张图片作为作答内容"
                if image_count > 1
                else "学习者另附了一张图片作为作答内容"
            )
            parts.append(f"{count_text}，请结合图片中的文字/公式/草图一并判定。")
        parts.append("请针对该学习者的具体作答给出 AI 评判。")
    else:
        parts = [
            f"Question type: {question_type or 'unknown'}",
            f"Question:\n{question}",
        ]
        if options_block:
            parts.append(f"Options:\n{options_block}")
        if correct_answer:
            parts.append(f"Reference answer:\n{correct_answer}")
        if explanation:
            parts.append(f"Reference explanation:\n{explanation}")
        parts.append(
            "Learner's answer:\n"
            + (
                user_answer.strip()
                if user_answer and user_answer.strip()
                else "(only an image was submitted, no typed answer)"
            )
        )
        if has_image:
            if image_count > 1:
                parts.append(
                    f"The learner attached {image_count} images as part of the answer. "
                    "Read their text/formulas/sketches and factor them into the judgment."
                )
            else:
                parts.append(
                    "The learner attached an image as part of the answer. "
                    "Read its text/formulas/sketches and factor it into the judgment."
                )
        parts.append("Produce an AI judgment that addresses this learner's specific answer.")
    return "\n\n".join(parts)


async def _build_multimodal_user_content(
    *,
    text: str,
    image_records: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Compose an OpenAI-style content-parts array with text + image blocks.

    For ``url``-only records we resolve local AttachmentStore paths to
    base64 here (most providers can fetch external URLs themselves, but
    locally-hosted ``/api/attachments/...`` is only reachable from the
    browser). Resolution failures are rejected rather than forwarding an
    untrusted URL to a provider.
    """
    from urllib.parse import unquote, urlparse

    from deeptutor.services.storage import get_attachment_store

    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    attachment_store = get_attachment_store()
    resolve = getattr(attachment_store, "resolve_path", None)

    for record in image_records:
        b64 = record.get("base64") or ""
        url = record.get("url") or ""
        filename = record.get("filename") or "answer.png"
        mime_type = record.get("mime_type") or _guess_image_mime(filename)

        if not b64 and url and resolve is not None:
            try:
                parsed = urlparse(url)
                parts = (parsed.path or url).strip("/").split("/")
                # Expected shape: api/attachments/{sid}/{aid}/{name}
                if len(parts) >= 5 and parts[0] == "api" and parts[1] == "attachments":
                    sid = unquote(parts[2])
                    aid = unquote(parts[3])
                    name = unquote("/".join(parts[4:]))
                    target = resolve(session_id=sid, attachment_id=aid, filename=name)
                    if target is None or not target.is_file():
                        raise ValueError("judge attachment is unavailable")
                    from deeptutor.services.config.runtime_settings import (
                        get_chat_attachment_limits,
                    )

                    if target.stat().st_size > get_chat_attachment_limits().max_file_bytes:
                        raise ValueError("judge attachment exceeds the size limit")
                    b64 = _b64.b64encode(target.read_bytes()).decode("ascii")
            except Exception as exc:
                raise ValueError("judge attachment is unavailable") from exc

        if b64:
            data_url = f"data:{mime_type};base64,{b64}"
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        else:
            raise ValueError("judge attachment is unavailable")

    return content


def _guess_image_mime(filename: str | None) -> str:
    if not filename:
        return "image/png"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "image/png")


def _bounded_judge_text(data: dict[str, Any], key: str, maximum: int) -> str:
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("judge text is invalid")
    return value


def _validated_judge_options(data: dict[str, Any]) -> dict[str, str] | None:
    options = data.get("options")
    if options is None:
        return None
    if not isinstance(options, dict) or len(options) > _MAX_JUDGE_OPTION_COUNT:
        raise ValueError("judge options are invalid")
    validated: dict[str, str] = {}
    for key, value in options.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or len(key) > _MAX_JUDGE_OPTION_CHARS
            or len(value) > _MAX_JUDGE_OPTION_CHARS
        ):
            raise ValueError("judge options are invalid")
        validated[key] = value
    return validated


def _validated_judge_images(data: dict[str, Any]) -> list[dict[str, str]]:
    """Validate image metadata and uploaded bytes before prompt construction."""
    import base64
    from urllib.parse import urlparse

    from deeptutor.services.storage.attachment_validation import (
        MAX_NOTEBOOK_ANSWER_IMAGE_COUNT,
        AttachmentValidationError,
        validate_notebook_answer_images,
    )

    raw_images = data.get("user_answer_images")
    if raw_images is None:
        raw_images = [
            {
                "base64": data.get("user_answer_image") or "",
                "url": "",
                "filename": data.get("image_filename") or "answer.png",
                "mime_type": _guess_image_mime(data.get("image_filename")),
            }
        ]
    if not isinstance(raw_images, list) or len(raw_images) > MAX_NOTEBOOK_ANSWER_IMAGE_COUNT:
        raise ValueError("judge images are invalid")

    records: list[dict[str, str]] = []
    for entry in raw_images:
        if not isinstance(entry, dict):
            raise ValueError("judge images are invalid")
        b64 = entry.get("base64") or ""
        url = entry.get("url") or ""
        filename = entry.get("filename") or "answer.png"
        mime_type = entry.get("mime_type") or _guess_image_mime(filename)
        if not all(isinstance(value, str) for value in (b64, url, filename, mime_type)):
            raise ValueError("judge images are invalid")
        if len(filename) > _MAX_JUDGE_FILENAME_CHARS or (b64 and url):
            raise ValueError("judge images are invalid")
        if b64.startswith("data:"):
            try:
                b64 = b64.split(",", 1)[1]
            except IndexError as exc:
                raise ValueError("judge images are invalid") from exc
        if url:
            parsed = urlparse(url)
            if (
                parsed.scheme
                or parsed.netloc
                or parsed.query
                or parsed.fragment
                or not parsed.path.startswith("/api/attachments/")
            ):
                raise ValueError("judge images are invalid")
            try:
                from urllib.parse import unquote

                from deeptutor.services.config.runtime_settings import (
                    get_chat_attachment_limits,
                )
                from deeptutor.services.storage import get_attachment_store

                parts = parsed.path.strip("/").split("/")
                if len(parts) < 5 or parts[0:2] != ["api", "attachments"]:
                    raise ValueError("judge attachment is unavailable")
                target = get_attachment_store().resolve_path(
                    session_id=unquote(parts[2]),
                    attachment_id=unquote(parts[3]),
                    filename=unquote("/".join(parts[4:])),
                )
                if target is None or not target.is_file():
                    raise ValueError("judge attachment is unavailable")
                if target.stat().st_size > get_chat_attachment_limits().max_file_bytes:
                    raise ValueError("judge attachment exceeds the size limit")
                b64 = base64.b64encode(target.read_bytes()).decode("ascii")
                url = ""
            except Exception as exc:
                raise ValueError("judge images are invalid") from exc
        if not b64:
            continue
        record = {
            "base64": b64,
            "url": url,
            "filename": filename,
            "mime_type": mime_type,
        }
        records.append(record)

    try:
        # URL-backed records were resolved through the current user's local
        # store above, so the same strict byte/magic policy covers both fresh
        # and previously persisted images before any provider call.
        validate_notebook_answer_images(records)
    except AttachmentValidationError as exc:
        raise ValueError("judge images are invalid") from exc
    return records


def _activate_judge_llm_scope() -> object:
    """Install the live user's authorized LLM selection for one judge request.

    Quiz judging has no client-facing model selector.  Non-admin users must
    therefore be pinned to a currently granted, configured model instead of
    falling through to the deployment's global default.  This is deliberately
    resolved immediately before provider work so a revoked grant is honored
    for an already-open socket.
    """
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.model_access import has_capability_access, redacted_model_access
    from deeptutor.services.model_selection.runtime import activate_llm_selection

    user = get_current_user()
    selection: dict[str, str] | None = None
    if not user.is_admin:
        if not has_capability_access("llm"):
            raise PermissionError("No LLM model is assigned to this account.")
        assignments = [
            item for item in redacted_model_access(user.id).get("llm", []) if item.get("available")
        ]
        if not assignments:
            raise PermissionError("No LLM model is assigned to this account.")
        selection = {
            "profile_id": str(assignments[0].get("profile_id") or ""),
            "model_id": str(assignments[0].get("model_id") or ""),
        }
        if not all(selection.values()):
            raise PermissionError("No LLM model is assigned to this account.")

    _config, token = activate_llm_selection(selection)
    return token


@router.websocket("/question/judge")
async def websocket_quiz_judge(websocket: WebSocket):
    """Stream an AI judgment for a single quiz answer.

    Auth is enforced via ``ws_require_auth`` rather than a router-level
    HTTP dependency — see module docstring.

    Client → Server (initial JSON):
        {
            "question": str,
            "question_type": str,
            "options": dict | null,
            "correct_answer": str,
            "explanation": str,
            "user_answer": str,
            # New: list of image entries. Each entry has either ``base64``
            # (no ``data:`` prefix) or ``url`` (already hosted via the
            # AttachmentStore). ``user_answer_image`` (single, base64) is
            # still accepted for backward compatibility.
            "user_answer_images": [
                {"base64": str, "url": str, "filename": str, "mime_type": str},
                ...
            ] | null,
            "user_answer_image": str | null,  # legacy single-image form
            "image_filename": str | null,     # legacy filename for the above
            "language": "zh" | "en",
        }

    Server → Client (streaming):
        {"type": "started"}
        {"type": "text", "content": "..."}        # zero or more
        {"type": "done"}
        {"type": "error", "content": "..."}
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth, ws_revalidate_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(websocket)
    if user_token is ws_auth_failed:
        return

    await websocket.accept()

    async def safe_send(payload: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            return False

    def reset_user_context() -> None:
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass

    try:
        data = await asyncio.wait_for(
            websocket.receive_json(), timeout=_INITIAL_REQUEST_TIMEOUT_SECONDS
        )
    except WebSocketDisconnect:
        reset_user_context()
        return
    except TimeoutError:
        await safe_send({"type": "error", "content": "Judge request timed out."})
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
        reset_user_context()
        return
    except Exception:
        logger.debug("Invalid AI judge request", exc_info=True)
        await safe_send({"type": "error", "content": "AI judging is unavailable."})
        try:
            await websocket.close()
        except Exception:
            pass
        reset_user_context()
        return

    try:
        if not isinstance(data, dict):
            raise ValueError("judge request is invalid")
        question_text = _bounded_judge_text(data, "question", _MAX_JUDGE_QUESTION_CHARS).strip()
        question_type = _bounded_judge_text(data, "question_type", 80)
        correct_answer = _bounded_judge_text(data, "correct_answer", _MAX_JUDGE_REFERENCE_CHARS)
        explanation = _bounded_judge_text(data, "explanation", _MAX_JUDGE_EXPLANATION_CHARS)
        user_answer = _bounded_judge_text(data, "user_answer", _MAX_JUDGE_ANSWER_CHARS)
        options_value = _validated_judge_options(data)
        image_records = _validated_judge_images(data)
        requested_language = _bounded_judge_text(data, "language", 80).strip().lower()
    except ValueError:
        await safe_send({"type": "error", "content": "Invalid judge request."})
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
        reset_user_context()
        return

    if not question_text:
        await safe_send({"type": "error", "content": "Question is required"})
        try:
            await websocket.close()
        except Exception:
            pass
        reset_user_context()
        return

    if requested_language not in ("zh", "en"):
        requested_language = get_ui_language(
            default=_config.get("system", {}).get("language", "en")
        )
        if requested_language not in ("zh", "en"):
            requested_language = "en"

    has_image = bool(image_records)
    system_prompt = _JUDGE_SYSTEM_PROMPTS.get(requested_language, _JUDGE_SYSTEM_PROMPTS["en"])
    user_prompt = _build_judge_user_prompt(
        language=requested_language,
        question=question_text,
        question_type=question_type,
        options=options_value,
        correct_answer=correct_answer,
        explanation=explanation,
        user_answer=user_answer,
        has_image=has_image,
        image_count=len(image_records),
    )

    if not (user_answer.strip() or has_image):
        await safe_send(
            {
                "type": "error",
                "content": ("No answer to judge — submit a typed answer or attach an image."),
            }
        )
        try:
            await websocket.close()
        except Exception:
            pass
        reset_user_context()
        return

    # A socket can outlive its original account decision. Re-check the current
    # JWT/account record immediately before the only provider-backed operation
    # so an account disabled after upgrade cannot spend provider resources.
    if not await ws_revalidate_auth(websocket):
        reset_user_context()
        return

    # Revalidate the current logical model grant after the socket's account
    # revalidation.  A learner's grant can change independently of the JWT;
    # scope the provider call to the resolved grant rather than the global
    # active model configuration.
    llm_scope_token: object | None = None
    global_quota_lease = None
    user_quota_lease = None
    try:
        llm_scope_token = _activate_judge_llm_scope()
        from deeptutor.multi_user.context import get_current_user

        user_quota_lease = await _JUDGE_REQUEST_QUOTA.acquire(get_current_user().id)
        global_quota_lease = await _JUDGE_GLOBAL_QUOTA.acquire(_JUDGE_GLOBAL_QUOTA_KEY)
    except (PermissionError, QuotaExceeded, ValueError):
        if user_quota_lease is not None:
            await user_quota_lease.__aexit__(None, None, None)
        if global_quota_lease is not None:
            await global_quota_lease.__aexit__(None, None, None)
        if llm_scope_token is not None:
            from deeptutor.services.model_selection.runtime import reset_llm_selection

            reset_llm_selection(llm_scope_token)
        await safe_send({"type": "error", "content": "AI judging is unavailable."})
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
        reset_user_context()
        return
    except Exception:
        if user_quota_lease is not None:
            await user_quota_lease.__aexit__(None, None, None)
        if global_quota_lease is not None:
            await global_quota_lease.__aexit__(None, None, None)
        if llm_scope_token is not None:
            from deeptutor.services.model_selection.runtime import reset_llm_selection

            reset_llm_selection(llm_scope_token)
        logger.exception("AI judge admission failed")
        await safe_send({"type": "error", "content": "AI judging is unavailable."})
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        reset_user_context()
        return

    assert global_quota_lease is not None
    assert user_quota_lease is not None

    try:
        async with global_quota_lease, user_quota_lease:
            # Build a multimodal user message when ≥1 image was attached. We
            # pass the full ``messages`` array to ``factory.stream`` so it
            # forwards the content-parts unchanged (the single-image
            # ``image_data`` kwarg only supports one image).
            stream_kwargs: dict[str, Any] = {}
            if has_image:
                from deeptutor.services.llm import config as _llm_config_mod
                from deeptutor.services.llm.capabilities import supports_vision

                llm_cfg = _llm_config_mod.get_llm_config()
                binding = getattr(llm_cfg, "binding", "openai") or "openai"
                model = getattr(llm_cfg, "model", "") or ""
                if supports_vision(binding, model):
                    user_content = await _build_multimodal_user_content(
                        text=user_prompt,
                        image_records=image_records,
                    )
                    stream_kwargs["messages"] = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ]
                else:
                    # Vision-incapable model — fall back to text-only judge so
                    # the learner still gets feedback on their typed answer.
                    logger.info(
                        "Judge: %s/%s does not support vision; dropping %d image(s)",
                        binding,
                        model,
                        len(image_records),
                    )

            if not await safe_send({"type": "started"}):
                return
            async for chunk in llm_stream(
                prompt=user_prompt,
                system_prompt=system_prompt,
                **stream_kwargs,
            ):
                if not chunk:
                    continue
                if not await safe_send({"type": "text", "content": chunk}):
                    break
            await safe_send({"type": "done"})
    except WebSocketDisconnect:
        logger.debug("AI judge client disconnected mid-stream")
    except Exception:
        logger.exception("AI judge stream failed")
        await safe_send({"type": "error", "content": "AI judging is unavailable."})
    finally:
        from deeptutor.services.model_selection.runtime import reset_llm_selection

        reset_llm_selection(llm_scope_token)
        try:
            await websocket.close()
        except Exception:
            pass
        reset_user_context()
