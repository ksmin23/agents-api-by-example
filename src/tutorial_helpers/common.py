"""Environment setup and resource cleanup; execution stays in notebooks."""

from __future__ import annotations
import json, os, time
from dataclasses import dataclass, field
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from dotenv import dotenv_values


def project_root():
    return next(
        (
            p
            for p in (Path.cwd(), *Path.cwd().parents)
            if (p / "tutorial.json").is_file()
        ),
        Path.cwd(),
    )


@dataclass
class Settings:
    enabled: bool
    model: str
    root: Path
    api_key: str | None = field(default=None, repr=False)


def load_settings(run_live=False, model_override=""):
    enabled = bool(run_live) and os.environ.get("TUTORIAL_OFFLINE_CHECK") != "1"
    settings = Settings(enabled, model_override, project_root())
    if not enabled:
        return settings
    if "google.colab" in __import__("sys").modules or os.environ.get(
        "COLAB_RELEASE_TAG"
    ):
        from google.colab import userdata

        settings.api_key = userdata.get("OPENAI_API_KEY")
        settings.model = model_override or userdata.get("OPENAI_MODEL")
    else:
        values = dotenv_values(settings.root / ".env.local")
        settings.api_key = values.get("OPENAI_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        settings.model = (
            model_override
            or values.get("OPENAI_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or ""
        )
    if not settings.api_key or not settings.model:
        raise RuntimeError(
            "Check OPENAI_API_KEY and OPENAI_MODEL settings. Do not print their values."
        )
    return settings


def safe_error(error):
    return {
        "exception": type(error).__name__,
        "status_code": getattr(error, "status_code", None),
        "request_id": getattr(error, "request_id", None),
    }


def new_session_metadata(
    chapter, run_id, label="main", *, attempts=None, output_dir=None
):
    metadata = {
        "tutorial": "feature-guide",
        "tutorial_run_id": run_id,
        "tutorial_creation_id": uuid4().hex,
        "chapter": chapter,
        "label": label,
    }
    if attempts is not None:
        attempts.append(metadata)
    if output_dir is not None:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "creation.json").write_text(
            json.dumps(attempts or [metadata])
        )
    return metadata


def save_agent_reference(output_dir, *, run_id, agent_id):
    """Persist only an owned Agent ID and run ID; no API calls or configuration."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "agent.json"
    temporary = directory / "agent.json.tmp"
    temporary.write_text(json.dumps({"run_id": run_id, "agent_id": agent_id}) + "\n")
    temporary.replace(path)


def delete_session_safely(client, session_id, *, attempts=8, sleep=time.sleep):
    from openai import ConflictError, NotFoundError

    cancel_sent = False
    for attempt in range(1, attempts + 1):
        try:
            state = client.beta.agents.sessions.retrieve(session_id, timeout=15)
        except NotFoundError:
            return {
                "deleted": True,
                "verified_absent": True,
                "cancel_sent": cancel_sent,
                "attempts": attempt,
            }
        if state.status in {"in_progress", "requires_action"} and not cancel_sent:
            client.beta.agents.sessions.events.create(
                session_id, events=[{"type": "agent.session.input.cancel"}], timeout=15
            )
            cancel_sent = True
        try:
            removed = client.beta.agents.sessions.delete(session_id, timeout=15)
        except ConflictError:
            if attempt == attempts:
                raise RuntimeError(f"Session cleanup pending: {session_id}") from None
            sleep(min(attempt, 3))
            continue
        except NotFoundError:
            return {
                "deleted": True,
                "verified_absent": True,
                "cancel_sent": cancel_sent,
                "attempts": attempt,
            }
        if not removed.deleted:
            raise RuntimeError("API did not confirm deletion")
        try:
            client.beta.agents.sessions.retrieve(session_id, timeout=15)
        except NotFoundError:
            return {
                "deleted": True,
                "verified_absent": True,
                "cancel_sent": cancel_sent,
                "attempts": attempt,
            }
        if attempt < attempts:
            sleep(min(attempt, 3))
    raise RuntimeError(f"Session deletion was not verified: {session_id}")


def cleanup_resources(client, sessions, agents, attempts):
    """Clean every owned resource, including lost create responses; return safe errors."""
    from openai import NotFoundError

    errors = []
    try:
        for metadata in attempts:
            try:
                for owned in client.beta.agents.sessions.list(
                    metadata={"tutorial_creation_id": metadata["tutorial_creation_id"]},
                    timeout=15,
                ):
                    if all(
                        owned.metadata.get(k) == metadata[k]
                        for k in ("tutorial_run_id", "tutorial_creation_id")
                    ):
                        sessions.setdefault(owned.id, {"deleted": False})
            except Exception as error:
                errors.append({"stage": "recover_session", **safe_error(error)})
        for sid in sessions:
            try:
                sessions[sid].update(delete_session_safely(client, sid))
            except Exception as error:
                errors.append({"session_id": sid, **safe_error(error)})
        for aid in agents:
            try:
                try:
                    removed = client.beta.agents.delete(aid, timeout=15)
                    if not removed.deleted:
                        raise RuntimeError("Agent deletion not confirmed")
                except NotFoundError:
                    agents[aid].update(deleted=True, verified_absent=True)
                for attempt in range(10):
                    try:
                        client.beta.agents.retrieve(aid, timeout=15)
                    except NotFoundError:
                        agents[aid].update(deleted=True, verified_absent=True)
                        break
                    time.sleep(min(attempt + 1, 3))
                if not agents[aid].get("verified_absent"):
                    raise RuntimeError("Agent still exists after bounded confirmation")
            except Exception as error:
                errors.append({"agent_id": aid, **safe_error(error)})
    finally:
        client.close()
    return errors


def check_event(event):
    """Shared failure guard, not an agent loop. Result collection remains in the lesson."""
    if event.type in {
        "error",
        "agent.session.failed",
        "agent.session.environment.failed",
    }:
        raise RuntimeError("Agent lifecycle failure: " + event.type)
    if (
        event.type in {"agent.session.turn.failed", "agent.session.turn.cancelled"}
        and event.turn.subagent_id is None
    ):
        raise RuntimeError("Root turn ended: " + event.turn.status)


@contextmanager
def cleanup_on_error(client, sessions, agents, attempts, *, errors=None, finalizers=()):
    """Keep resources between cells; attempt cleanup on exceptions or interruption."""
    try:
        yield
    except BaseException as original:
        try:
            failures = cleanup_resources(client, sessions, agents, attempts)
        except Exception as cleanup_error:
            failures = [safe_error(cleanup_error)]
        for finalize in finalizers:
            try:
                finalize()
            except Exception as finalizer_error:
                failures.append(safe_error(finalizer_error))
        if errors is not None:
            errors[:] = failures
        if failures:
            original.add_note("Resource cleanup incomplete; inspect local state and run the cleanup cell.")
        raise
