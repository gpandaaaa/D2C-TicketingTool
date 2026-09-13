import json
import logging
from contextvars import ContextVar

from app.models.entities import AuditLog

request_context = ContextVar("request_context", default={})


def audit(db, actor, action, entity, entity_id, before=None, after=None):
    logging.info(
        json.dumps(
            {
                "event": "audit_action",
                "action": action,
                "entity": entity,
                "entity_id": str(entity_id),
                "actor_id": actor,
            }
        )
    )
    db.add(
        AuditLog(
            actor_id=actor,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            before=before,
            after=after,
            **request_context.get(),
        )
    )
