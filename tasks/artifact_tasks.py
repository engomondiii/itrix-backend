"""
Artifact generation tasks (Backend v6.0 §1.5).

Generation is a model call plus a governance pass, so it belongs off the request path —
but it must still work synchronously, because the artifact is what the visitor is waiting
for at the end of the question loop.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

try:
    from tasks.celery import app
except Exception:  # noqa: BLE001
    app = None


def _task(func):
    if app is None:
        return func
    return app.task(name=f"itrix.artifacts.{func.__name__}")(func)


@_task
def generate_artifact(thread_id: str, artifact_type: str, disclosure_level: str = "public") -> dict:
    from apps.conversations.models import Thread
    from apps.journey.services import artifacts

    thread = Thread.objects.filter(id=thread_id).first()
    if thread is None:
        return {"generated": False, "reason": "thread not found"}
    try:
        artifact = artifacts.generate(thread, artifact_type, disclosure_level=disclosure_level)
        return {"generated": True, "artifact_id": str(artifact.id), "version": artifact.version}
    except artifacts.ArtifactNotAuthorized as exc:
        logger.info("artifact refused: %s", exc)
        return {"generated": False, "reason": "not authorized"}
    except Exception:  # noqa: BLE001
        logger.exception("artifact generation failed for thread %s", thread_id)
        return {"generated": False, "reason": "error"}


@_task
def generate_qualification_artifacts(thread_id: str) -> dict:
    """
    The stop-rule handoff (§5.5).

        When the stop rule fires for the qualification band,
        artifacts.generate(thread, "reflection") runs, then the pitch room, then
        journey.advance(). NO FURTHER QUESTION IS ASKED.
    """
    from apps.conversations.models import Thread
    from apps.journey.constants import ARTIFACT_PITCH_ROOM, ARTIFACT_REFLECTION
    from apps.journey.services import artifacts
    from apps.journey.services.advance import on_loop_closed

    thread = Thread.objects.filter(id=thread_id).select_related("lead").first()
    if thread is None:
        return {"generated": False, "reason": "thread not found"}

    produced = []
    lead = thread.lead
    if lead is not None:
        try:
            on_loop_closed(lead, thread=thread)
        except Exception:  # noqa: BLE001
            logger.debug("loop-closed advance skipped for lead %s", lead.id)

    for artifact_type in (ARTIFACT_REFLECTION, ARTIFACT_PITCH_ROOM):
        try:
            artifact = artifacts.generate(thread, artifact_type, force=True)
            produced.append(artifact_type)
            if artifact_type == ARTIFACT_PITCH_ROOM:
                artifacts.bind_capability_token(artifact)
        except Exception:  # noqa: BLE001
            logger.exception("could not generate %s for thread %s", artifact_type, thread_id)

    return {"generated": bool(produced), "artifacts": produced}
