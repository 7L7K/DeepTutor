import asyncio
import base64
from contextlib import AsyncExitStack
from datetime import datetime
import json
import logging
from pathlib import Path
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from deeptutor.agents.question import AgentCoordinator
from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.logging import (
    ProcessLogEvent,
    bind_log_context,
    capture_process_logs,
)
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.llm.config import get_llm_config
from deeptutor.services.path_service import get_path_service
from deeptutor.services.sandbox.quota import UserExecQuota
from deeptutor.services.settings.interface_settings import get_ui_language
from deeptutor.tools.question import mimic_exam_questions
from deeptutor.utils.document_validator import DocumentValidator

# Setup module logger with unified logging system (from config)
config = load_config_with_main("main.yaml", PROJECT_ROOT)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = logging.getLogger(__name__)

router = APIRouter()

_QUESTION_REQUEST_QUOTA = UserExecQuota(max_concurrent=1, max_per_minute=6)
# Question/mimic generation is deliberately serialized across the process.
# The legacy stdout interception has been removed; structured log capture is
# task-scoped and is the only source of user-visible process logs.
_QUESTION_GLOBAL_QUOTA = UserExecQuota(max_concurrent=1, max_per_minute=12)
_QUESTION_GLOBAL_QUOTA_KEY = "question-generation-global"
# Intake protection is intentionally separate from generation admission. It
# bounds authenticated sockets while they receive and locally preprocess a
# request, then releases before any provider work starts.
_QUESTION_INTAKE_USER_QUOTA = UserExecQuota(max_concurrent=2, max_per_minute=24)
_QUESTION_INTAKE_GLOBAL_QUOTA = UserExecQuota(max_concurrent=16, max_per_minute=192)
_QUESTION_INTAKE_GLOBAL_KEY = "question-intake-global"
_MAX_QUESTION_COUNT = 10
_MAX_REQUIREMENT_CHARS = 12_000
_MAX_KB_NAME_CHARS = 128
_MAX_MIMIC_PATH_CHARS = 512
# Keep the legacy question upload inside the fixed 64 MiB WebSocket ceiling
# (40 MiB decoded bytes plus base64/envelope overhead). The general document
# validator remains broader for HTTP/Course ingestion paths.
_MAX_MIMIC_PDF_B64_CHARS = ((40 * 1024 * 1024 + 2) // 3) * 4 + 4
_MAX_REQUEST_JSON_CHARS = _MAX_MIMIC_PDF_B64_CHARS + 64 * 1024
# ``/generate`` has no upload field. Keep its first WebSocket frame bounded
# independently from ``/mimic`` while still allowing the four documented
# requirement strings at their supported maximum, including JSON escaping.
_MAX_GENERATE_REQUEST_JSON_CHARS = 320 * 1024
# Generation capacity is acquired only for validated work, but an upgraded
# socket still gets a finite chance to supply that first request.
_QUESTION_INITIAL_REQUEST_TIMEOUT_S = 30.0

# These are deliberately conservative, process-local beta bulkheads. They
# protect one application process from accidental or abusive provider usage;
# they are not distributed billing or durable rate-limit authority.


def _bounded_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("request text is invalid")
    return value


def _bounded_question_count(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("question count is invalid")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("question count is invalid") from exc
    if not 1 <= count <= _MAX_QUESTION_COUNT:
        raise ValueError("question count is invalid")
    return count


def _activate_question_llm_scope() -> object:
    """Pin non-admin generation to a currently assigned configured model."""
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.model_access import has_capability_access, redacted_model_access
    from deeptutor.services.model_selection.runtime import activate_llm_selection

    user = get_current_user()
    selection: dict[str, str] | None = None
    if not user.is_admin:
        if not has_capability_access("llm"):
            raise PermissionError("No LLM model is assigned to this account.")
        granted = [
            item for item in redacted_model_access(user.id).get("llm", []) if item.get("available")
        ]
        if not granted:
            raise PermissionError("No LLM model is assigned to this account.")
        selection = {
            "profile_id": str(granted[0].get("profile_id") or ""),
            "model_id": str(granted[0].get("model_id") or ""),
        }
        if not all(selection.values()):
            raise PermissionError("No LLM model is assigned to this account.")
    resolved_config, token = activate_llm_selection(selection)
    if not str(getattr(resolved_config, "model", "") or "").strip():
        from deeptutor.services.model_selection.runtime import reset_llm_selection

        reset_llm_selection(token)
        raise PermissionError("Configured LLM model is unavailable")
    return token


def _allowed_question_builtin_tools() -> list[str] | None:
    """Resolve the caller's server-owned built-in tool grant for legacy turns.

    The legacy Question entry points do not use ``turn_runtime``.  They must
    therefore resolve this grant directly rather than accept a browser-provided
    tool list.  ``None`` remains the explicit unrestricted-admin sentinel;
    learners receive a deterministic allowlist (empty by default).
    """
    from deeptutor.multi_user.tool_access import allowed_builtin_tools

    allowed = allowed_builtin_tools()
    return None if allowed is None else sorted(allowed)


async def _admit_question_generation() -> tuple[object, AsyncExitStack]:
    """Install the authorized model and reserve beta bulkhead leases."""
    from deeptutor.multi_user.context import get_current_user

    scope_token = _activate_question_llm_scope()
    leases = AsyncExitStack()
    try:
        user_lease = await _QUESTION_REQUEST_QUOTA.acquire(get_current_user().id)
        await leases.enter_async_context(user_lease)
        global_lease = await _QUESTION_GLOBAL_QUOTA.acquire(_QUESTION_GLOBAL_QUOTA_KEY)
        await leases.enter_async_context(global_lease)
        return scope_token, leases
    except BaseException:
        await leases.aclose()
        from deeptutor.services.model_selection.runtime import reset_llm_selection

        reset_llm_selection(scope_token)
        raise


async def _admit_question_intake() -> AsyncExitStack:
    """Reserve a bounded socket/preprocess slot without selecting a model."""
    from deeptutor.multi_user.context import get_current_user

    leases = AsyncExitStack()
    try:
        user_lease = await _QUESTION_INTAKE_USER_QUOTA.acquire(get_current_user().id)
        await leases.enter_async_context(user_lease)
        global_lease = await _QUESTION_INTAKE_GLOBAL_QUOTA.acquire(_QUESTION_INTAKE_GLOBAL_KEY)
        await leases.enter_async_context(global_lease)
        return leases
    except BaseException:
        await leases.aclose()
        raise


def _resolve_parsed_mimic_path(value: object) -> str:
    raw = _bounded_text(value, maximum=_MAX_MIMIC_PATH_CHARS)
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError("parsed paper path is invalid")
    root = get_path_service().get_question_dir().resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("parsed paper path is invalid") from exc
    if not resolved.is_dir():
        raise ValueError("parsed paper path is invalid")
    return str(resolved)


def _validate_request_envelope(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("request is invalid")
    return data


_GENERATE_REQUEST_FIELDS = frozenset({"requirement", "kb_name", "count"})
_GENERATE_REQUIREMENT_FIELDS = frozenset(
    {"knowledge_point", "preference", "difficulty", "question_type"}
)


def _validate_generate_request_envelope(data: object) -> dict:
    """Reject unsupported generator fields before route-level processing.

    Unlike mimic, generation has no binary payload. Strictly naming its
    compact schema prevents a client from making this legacy endpoint carry
    arbitrary padded JSON that no supported contract consumes.
    """
    envelope = _validate_request_envelope(data)
    if set(envelope) - _GENERATE_REQUEST_FIELDS:
        raise ValueError("request is invalid")

    requirement = envelope.get("requirement")
    if isinstance(requirement, dict) and set(requirement) - _GENERATE_REQUIREMENT_FIELDS:
        raise ValueError("request is invalid")
    return envelope


async def _receive_bounded_request_json(
    websocket: WebSocket,
    *,
    maximum_chars: int | None = None,
    envelope_validator=None,
) -> dict:
    """Receive one text JSON envelope without parsing an unbounded payload."""
    message = await asyncio.wait_for(
        websocket.receive(), timeout=_QUESTION_INITIAL_REQUEST_TIMEOUT_S
    )
    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    raw = message.get("text")
    maximum = _MAX_REQUEST_JSON_CHARS if maximum_chars is None else maximum_chars
    if not isinstance(raw, str) or len(raw) > maximum:
        raise ValueError("request is invalid")
    try:
        validator = envelope_validator or _validate_request_envelope
        return validator(json.loads(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("request is invalid") from exc


def _mimic_output_dir():
    # Resolved per-call so a per-user PathService (set after auth) routes
    # generated mimic papers under the caller's own workspace instead of
    # admin's directory frozen at import time.
    return get_path_service().get_question_dir() / "mimic_papers"


@router.websocket("/mimic")
async def websocket_mimic_generate(websocket: WebSocket):
    """
    WebSocket endpoint for mimic exam paper question generation.

    Supports two modes:
    1. Upload PDF directly via WebSocket (base64 encoded)
    2. Use a pre-parsed paper directory path

    Message format for PDF upload:
    {
        "mode": "upload",
        "pdf_data": "base64_encoded_pdf_content",
        "pdf_name": "exam.pdf",
        "kb_name": "knowledge_base_name",
        "max_questions": 5  // optional
    }

    Message format for pre-parsed:
    {
        "mode": "parsed",
        "paper_path": "directory_name",
        "kb_name": "knowledge_base_name",
        "max_questions": 5  // optional
    }
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth, ws_revalidate_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(websocket)
    if user_token is ws_auth_failed:
        return

    await websocket.accept()

    pusher_task = None
    llm_scope_token = None
    admission_leases = None
    intake_leases = None
    uploaded_pdf_bytes: bytes | None = None

    try:
        # A socket may remain idle after it authenticates.  Revalidate before
        # reading its one bounded envelope, but do not reserve scarce provider
        # or process-wide generation capacity until that envelope has passed
        # local validation.
        if not await ws_revalidate_auth(websocket):
            return

        intake_leases = await _admit_question_intake()
        try:
            # 1. Receive and locally validate/preprocess the request while
            # holding only the bounded intake lease, never a provider lease.
            data = await _receive_bounded_request_json(websocket)
            mode = data.get("mode", "parsed")
            if mode not in {"upload", "parsed"}:
                raise ValueError("mimic mode is invalid")
            kb_name = _bounded_text(data.get("kb_name", "ai_textbook"), maximum=_MAX_KB_NAME_CHARS)
            max_questions = _bounded_question_count(data.get("max_questions"), default=5)
            if mode == "upload":
                pdf_data = _bounded_text(data.get("pdf_data"), maximum=_MAX_MIMIC_PDF_B64_CHARS)
                pdf_name = _bounded_text(data.get("pdf_name", "exam.pdf"), maximum=255)
                try:
                    uploaded_pdf_bytes = base64.b64decode(pdf_data, validate=True)
                    if not uploaded_pdf_bytes.startswith(b"%PDF-"):
                        raise ValueError("not a PDF")
                    safe_pdf_name = DocumentValidator.validate_upload_safety(
                        pdf_name, len(uploaded_pdf_bytes), {".pdf"}
                    )
                except (ValueError, TypeError):
                    raise ValueError("upload is invalid") from None
                data = {**data, "pdf_name": safe_pdf_name}
            else:
                paper_path = _resolve_parsed_mimic_path(data.get("paper_path"))
                data = {**data, "paper_path": paper_path}
        finally:
            await intake_leases.aclose()
            intake_leases = None

        # Provider/model selection and the per-user + global bulkheads cover
        # actual generation only.  An authenticated but idle socket therefore
        # cannot monopolize the single global generation lease.
        llm_scope_token, admission_leases = await _admit_question_generation()
        allowed_builtin_tools = _allowed_question_builtin_tools()

        logger.info(f"Starting mimic generation (mode: {mode}, kb: {kb_name})")

        # 2. Setup Log Queue
        log_queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        task_id = f"question_mimic_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        def emit_process_log(event: ProcessLogEvent) -> None:
            loop.call_soon_threadsafe(log_queue.put_nowait, event.to_dict())

        async def log_pusher():
            while True:
                entry = await log_queue.get()
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
                log_queue.task_done()

        pusher_task = asyncio.create_task(log_pusher())

        try:
            await websocket.send_json(
                {"type": "status", "stage": "init", "content": "Initializing..."}
            )

            pdf_path = None
            paper_dir = None

            # Handle PDF upload mode
            if mode == "upload":
                pdf_name = data.get("pdf_name", "exam.pdf")
                pdf_bytes = uploaded_pdf_bytes
                if pdf_bytes is None:
                    raise ValueError("upload is invalid")
                safe_name = pdf_name

                # Create batch directory for this mimic session
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                pdf_stem = Path(safe_name).stem
                batch_dir = _mimic_output_dir() / f"mimic_{timestamp}_{pdf_stem}"
                batch_dir.mkdir(parents=True, exist_ok=True)

                # Save uploaded PDF in batch directory
                pdf_path = batch_dir / safe_name

                await websocket.send_json(
                    {"type": "status", "stage": "upload", "content": f"Saving PDF: {safe_name}"}
                )

                # Write the validated PDF bytes
                with open(pdf_path, "wb") as f:
                    f.write(pdf_bytes)

                # Additional validation (file readability, etc.)
                try:
                    DocumentValidator.validate_file(pdf_path)
                except (ValueError, FileNotFoundError, PermissionError):
                    # Clean up invalid or inaccessible file
                    pdf_path.unlink(missing_ok=True)
                    await websocket.send_json(
                        {"type": "error", "content": "Invalid generation request."}
                    )
                    return

                await websocket.send_json(
                    {
                        "type": "status",
                        "stage": "parsing",
                        "content": "Parsing PDF exam paper (MinerU)...",
                    }
                )
                logger.info(f"Saved and validated uploaded PDF to: {pdf_path}")

                # Pass batch_dir as output directory
                pdf_path = str(pdf_path)
                output_dir = str(batch_dir)

            elif mode == "parsed":
                paper_path = data.get("paper_path")
                if not paper_path:
                    await websocket.send_json(
                        {"type": "error", "content": "paper_path is required for parsed mode"}
                    )
                    return
                paper_dir = paper_path

                # Create batch directory for parsed mode too
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                batch_dir = _mimic_output_dir() / f"mimic_{timestamp}_{Path(paper_path).name}"
                batch_dir.mkdir(parents=True, exist_ok=True)
                output_dir = str(batch_dir)

            else:
                await websocket.send_json(
                    {"type": "error", "content": "Invalid generation request."}
                )
                return

            # Create WebSocket callback for real-time progress updates
            async def ws_callback(event_type: str, data: dict):
                """Send progress updates to the frontend via WebSocket."""
                try:
                    message = {"type": event_type, **data}
                    await websocket.send_json(message)
                except Exception as e:
                    logger.debug(f"WebSocket send failed: {e}")

            # Run the complete mimic workflow with callback
            await websocket.send_json(
                {
                    "type": "status",
                    "stage": "processing",
                    "content": "Executing question generation workflow...",
                }
            )

            with bind_log_context(task_id=task_id, capability="deep_question", sink="ui"):
                with capture_process_logs(emit_process_log, task_id=task_id):
                    result = await mimic_exam_questions(
                        pdf_path=pdf_path,
                        paper_dir=paper_dir,
                        kb_name=kb_name,
                        output_dir=output_dir,
                        max_questions=max_questions,
                        allowed_builtin_tools=allowed_builtin_tools,
                        ws_callback=ws_callback,
                    )

            if result.get("success"):
                # Results are already sent via ws_callback during generation
                # Just send the final complete signal
                total_ref = result.get("total_reference_questions", 0)
                generated = result.get("generated_questions", [])
                failed = result.get("failed_questions", [])

                logger.info(
                    f"Mimic generation complete: {len(generated)} succeeded, {len(failed)} failed"
                )

                try:
                    await websocket.send_json({"type": "complete"})
                except (RuntimeError, WebSocketDisconnect):
                    logger.debug("WebSocket closed before complete signal could be sent")
            else:
                error_msg = "Question generation is unavailable."
                try:
                    await websocket.send_json({"type": "error", "content": error_msg})
                except (RuntimeError, WebSocketDisconnect):
                    pass
                logger.error(f"Mimic generation failed: {error_msg}")

        finally:
            # The outer cleanup owns sockets, log tasks, and admission leases.
            pass

    except WebSocketDisconnect:
        logger.debug("Client disconnected during mimic generation")
    except Exception:
        logger.exception("Mimic generation error")
        try:
            await websocket.send_json(
                {"type": "error", "content": "Question generation is unavailable."}
            )
        except Exception:
            pass
    finally:
        # Clean up pusher task
        if pusher_task:
            try:
                pusher_task.cancel()
                await pusher_task
            except asyncio.CancelledError:
                pass  # Expected when cancelling
            except Exception:
                pass

        # Drain any remaining items in the queue
        try:
            while not log_queue.empty():
                log_queue.get_nowait()
        except Exception:
            pass

        # Close WebSocket
        try:
            await websocket.close()
        except Exception:
            pass

        if admission_leases is not None:
            await admission_leases.aclose()
        if intake_leases is not None:
            await intake_leases.aclose()
        if llm_scope_token is not None:
            from deeptutor.services.model_selection.runtime import reset_llm_selection

            reset_llm_selection(llm_scope_token)

        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass


@router.websocket("/generate")
async def websocket_question_generate(websocket: WebSocket):
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth, ws_revalidate_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(websocket)
    if user_token is ws_auth_failed:
        return

    await websocket.accept()

    # Get task ID manager
    task_manager = TaskIDManager.get_instance()
    llm_scope_token = None
    admission_leases = None
    intake_leases = None

    try:
        # Do not let an idle authenticated socket reserve generation capacity.
        # Validate its bounded request before taking provider/process leases.
        if not await ws_revalidate_auth(websocket):
            return

        intake_leases = await _admit_question_intake()
        try:
            # 1. Receive and locally validate the request before consuming a
            # provider/generation rate-quota slot.
            data = await _receive_bounded_request_json(
                websocket,
                maximum_chars=_MAX_GENERATE_REQUEST_JSON_CHARS,
                envelope_validator=_validate_generate_request_envelope,
            )
            requirement = data.get("requirement")
            if isinstance(requirement, dict):
                requirement = {
                    key: _bounded_text(value, maximum=_MAX_REQUIREMENT_CHARS)
                    for key, value in requirement.items()
                    if key in {"knowledge_point", "preference", "difficulty", "question_type"}
                }
            else:
                requirement = _bounded_text(requirement, maximum=_MAX_REQUIREMENT_CHARS)
            kb_name = _bounded_text(data.get("kb_name", "ai_textbook"), maximum=_MAX_KB_NAME_CHARS)
            count = _bounded_question_count(data.get("count"), default=1)
        finally:
            await intake_leases.aclose()
            intake_leases = None

        if not requirement:
            try:
                await websocket.send_json({"type": "error", "content": "Requirement is required"})
            except (RuntimeError, WebSocketDisconnect):
                pass
            return

        llm_scope_token, admission_leases = await _admit_question_generation()
        allowed_builtin_tools = _allowed_question_builtin_tools()

        # Generate task ID
        task_key = f"question_{kb_name}_{hash(str(requirement))}"
        task_id = task_manager.generate_task_id("question_gen", task_key)

        # Send task ID to frontend
        try:
            await websocket.send_json({"type": "task_id", "task_id": task_id})
        except (RuntimeError, WebSocketDisconnect):
            logger.debug("WebSocket closed, cannot send task_id")
            return

        topic_for_log = (
            requirement.get("knowledge_point", "Unknown")
            if isinstance(requirement, dict)
            else requirement
        )
        logger.info(f"[{task_id}] Starting question generation: {topic_for_log}")

        # 2. Initialize Coordinator
        path_service = get_path_service()
        output_base = path_service.get_question_batch_dir(task_id)

        llm_config = get_llm_config()
        if not str(getattr(llm_config, "model", "") or "").strip():
            raise PermissionError("Configured LLM model is unavailable")
        api_key = llm_config.api_key
        base_url = llm_config.base_url
        api_version = getattr(llm_config, "api_version", None)

        coordinator = AgentCoordinator(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            kb_name=kb_name,
            language=get_ui_language(default=config.get("system", {}).get("language", "en")),
            output_dir=str(output_base),
            allowed_builtin_tools=allowed_builtin_tools,
        )

        # 3. Setup Log Queue for WebSocket streaming
        log_queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit_process_log(event: ProcessLogEvent) -> None:
            loop.call_soon_threadsafe(log_queue.put_nowait, event.to_dict())

        # WebSocket callback for coordinator to send structured updates
        async def ws_callback(data: dict):
            try:
                await log_queue.put(data)
            except Exception:
                pass

        coordinator.set_ws_callback(ws_callback)

        # 4. Define background pusher for logs
        async def log_pusher():
            while True:
                entry = await log_queue.get()
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
                log_queue.task_done()

        pusher_task = asyncio.create_task(log_pusher())

        # 5. Run generation while streaming logs bound to this task.
        try:
            with bind_log_context(task_id=task_id, capability="deep_question", sink="ui"):
                with capture_process_logs(emit_process_log, task_id=task_id):
                    try:
                        await websocket.send_json({"type": "status", "content": "started"})
                    except (RuntimeError, WebSocketDisconnect):
                        logger.debug("WebSocket closed, stopping question generation")
                        return

                    # Extract fields from requirement dict
                    user_topic = (
                        requirement.get("knowledge_point", "")
                        if isinstance(requirement, dict)
                        else str(requirement)
                    )
                    difficulty = (
                        requirement.get("difficulty", "") if isinstance(requirement, dict) else ""
                    )
                    question_type = (
                        requirement.get("question_type", "")
                        if isinstance(requirement, dict)
                        else ""
                    )
                    question_types = [question_type] if question_type else []
                    per_type_counts = {question_type: count} if question_type else {}

                    logger.info(
                        f"Starting question generation for {count} question(s), topic: {user_topic}"
                    )

                    batch_result = await coordinator.generate_from_topic(
                        user_topic=user_topic,
                        num_questions=count,
                        difficulty=difficulty,
                        question_types=question_types,
                        per_type_counts=per_type_counts,
                    )

                    # Send batch summary
                    try:
                        await websocket.send_json(
                            {
                                "type": "batch_summary",
                                "requested": count,
                                "completed": batch_result.get("completed", 0),
                                "failed": batch_result.get("failed", 0),
                            }
                        )
                    except (RuntimeError, WebSocketDisconnect):
                        pass

                    if not batch_result.get("success"):
                        logger.warning(
                            f"Question generation had failures: {batch_result.get('failed', 0)} failed"
                        )

                    # Wait for any pending messages in the queue to be sent
                    # Give the pusher a moment to process remaining messages
                    await asyncio.sleep(0.1)
                    while not log_queue.empty():
                        await asyncio.sleep(0.05)

                    # Send complete signal
                    try:
                        await websocket.send_json({"type": "complete"})
                        logger.info(f"[{task_id}] Question generation completed")
                        task_manager.update_task_status(task_id, "completed")
                    except (RuntimeError, WebSocketDisconnect):
                        logger.debug("WebSocket closed, cannot send complete signal")

        except Exception:
            error_msg = "Question generation is unavailable."
            error_traceback = traceback.format_exc()
            logger.error(f"Question generation error: {error_msg}")
            logger.error(f"Error traceback:\n{error_traceback}")

            # Log additional context if available
            try:
                context_result = locals().get("batch_result")
                if context_result is not None:
                    logger.error(
                        f"Result type: {type(context_result)}, result keys: {context_result.keys() if isinstance(context_result, dict) else 'N/A'}"
                    )
                    if isinstance(context_result, dict) and "validation" in context_result:
                        validation = context_result["validation"]
                        logger.error(f"Validation type: {type(validation)}")
                        if isinstance(validation, dict):
                            logger.error(f"Validation keys: {validation.keys()}")
                            logger.error(
                                f"Issues type: {type(validation.get('issues'))}, value: {validation.get('issues')}"
                            )
                            logger.error(
                                f"Suggestions type: {type(validation.get('suggestions'))}, value: {validation.get('suggestions')}"
                            )
            except Exception as context_error:
                logger.warning(f"Failed to log error context: {context_error}")

            try:
                await websocket.send_json({"type": "error", "content": error_msg})
            except (RuntimeError, WebSocketDisconnect):
                logger.debug("WebSocket closed, cannot send error message")
            task_manager.update_task_status(task_id, "error", error=error_msg)

        finally:
            pusher_task.cancel()
            try:
                await pusher_task
            except asyncio.CancelledError:
                pass
            try:
                await websocket.close()
            except Exception:
                pass

    except WebSocketDisconnect:
        logger.debug("Client disconnected")
    except Exception:
        logger.exception("Question generation WebSocket error")
        try:
            await websocket.send_json(
                {"type": "error", "content": "Question generation is unavailable."}
            )
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        if admission_leases is not None:
            await admission_leases.aclose()
        if intake_leases is not None:
            await intake_leases.aclose()
        if llm_scope_token is not None:
            from deeptutor.services.model_selection.runtime import reset_llm_selection

            reset_llm_selection(llm_scope_token)
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
