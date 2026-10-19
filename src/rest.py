import logging

from fastapi import APIRouter, HTTPException, Request, status

from src.dto import Response
from src.service import EmptyIncidentError, IncidentClassificationError, classify_incident

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])

TEXT_BODY_SPEC = {
    "requestBody": {
        "required": True,
        "content": {"text/plain": {"schema": {"type": "string", "title": "Incident description"}}},
    }
}


# the raw body is read directly so any Content-Type is accepted and bad UTF-8 is a clean 422
@router.post("/classify", openapi_extra=TEXT_BODY_SPEC)
async def classify(request: Request) -> Response:
    try:
        incident_desc = (await request.body()).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "request body must be UTF-8 text") from exc

    try:
        return await classify_incident(incident_desc)
    except EmptyIncidentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except IncidentClassificationError as exc:
        logger.error("incident classification failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, {"errors": exc.errors}) from exc
