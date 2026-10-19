import json
import logging
import re

from anthropic import APIError, AsyncAnthropic, transform_schema
from anthropic.types import Message, MessageParam
from langdetect import DetectorFactory, LangDetectException, detect
from pydantic import ValidationError

from src.config import settings
from src.dto import ParsedIncident, Response
from src.knowledge import (
    CATEGORY_PREFIXES,
    MAX_HYPOTHESES,
    MAX_NEXT_STEPS,
    MIN_NEXT_STEPS,
    PAST_INCIDENTS,
    SERVICES,
    PastIncident,
)
from src.templates import INCIDENT_PROMPT, PAST_INCIDENT, REFINE_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class EmptyIncidentError(Exception):
    pass


class IncidentClassificationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# langdetect is non-deterministic without a fixed seed
DetectorFactory.seed = 0


def _detect_language(text: str) -> str | None:
    try:
        return detect(text)
    except LangDetectException:
        return None


HTTP_CODE_RE = re.compile(r"\b[45]\d{2}(?=s?\b)")
TIMESTAMP_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s*UTC)?\b", re.IGNORECASE)


def parse_input(incident_desc: str) -> ParsedIncident:
    text = incident_desc.strip()
    if not text:
        raise EmptyIncidentError("incident description is empty")

    lowered = text.lower()
    return ParsedIncident(
        text=text,
        services=[s for s in SERVICES if s in lowered],
        http_codes=sorted(set(HTTP_CODE_RE.findall(text))),
        timestamps=TIMESTAMP_RE.findall(text),
        language=_detect_language(text),
    )


WORD_RE = re.compile(r"[a-z][a-z0-9/-]{3,}")
STOPWORDS = frozenset({
    "about", "after", "also", "been", "before", "being", "does", "from", "have", "into", "many", "more",
    "most", "only", "other", "some", "than", "that", "their", "them", "there", "they", "this", "very",
    "were", "what", "when", "which", "while", "with", "customers", "users", "logs", "show", "shows",
    "seen", "since", "started", "issue", "noticed", "report", "reports",
})
SHARED_SERVICES_WEIGHT = 3
# a shared service, or at least two shared words
MIN_RELEVANCE = 2


def _words(text: str) -> set[str]:
    return set(WORD_RE.findall(text.lower())) - STOPWORDS - set(SERVICES)


def _relevance(parsed: ParsedIncident, incident: PastIncident) -> int:
    shared_services = len(set(parsed.services) & set(incident.services))
    shared_words = len(_words(parsed.text) & _words(incident.text))
    return SHARED_SERVICES_WEIGHT * shared_services + shared_words


def build_context(parsed: ParsedIncident) -> str:
    scored = sorted(
        ((_relevance(parsed, inc), inc) for inc in PAST_INCIDENTS),
        key=lambda pair: pair[0],
        reverse=True,
    )
    similar = [inc for score, inc in scored[: settings.context_top_k] if score >= MIN_RELEVANCE]
    logger.info("selected past incidents: %s", [inc.id for inc in similar])

    past_incidents = "\n\n".join(
        PAST_INCIDENT.format(id=inc.id, category=inc.category, text=inc.text) for inc in similar
    )
    return INCIDENT_PROMPT.format(
        text=parsed.text,
        language=parsed.language or "unknown",
        services=", ".join(parsed.services) or "none",
        http_codes=", ".join(parsed.http_codes) or "none",
        timestamps=", ".join(parsed.timestamps) or "none",
        past_incidents=past_incidents or "none",
    )


def parse_llm_json(raw_text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return json.loads(cleaned[start : end + 1])


def _extract(message: Message) -> tuple[Response | None, list[str]]:
    if message.stop_reason == "refusal":
        return None, ["the model refused to answer"]

    raw = "".join(b.text for b in message.content if b.type == "text")
    try:
        return Response.model_validate_json(raw), []
    except ValidationError:
        logger.warning("structured output failed validation, falling back to lenient JSON parsing")

    try:
        return Response.model_validate(parse_llm_json(raw)), []
    except ValueError as exc:
        errors = [f"output is not a valid JSON object of the required shape: {exc}"]
        if message.stop_reason == "max_tokens":
            errors.append("output was cut off; keep the answer shorter")
        return None, errors


CATEGORY_RE = re.compile(rf"^\[({'|'.join(map(re.escape, CATEGORY_PREFIXES))})\] - \S.*$")


def validate(response: Response) -> list[str]:
    errors = []

    if not CATEGORY_RE.match(response.category):
        errors.append(
            f'category "{response.category}" must look like "[<service>] - <short description>" '
            f"where <service> is one of: {', '.join(CATEGORY_PREFIXES)}"
        )

    if not response.summary.strip():
        errors.append("summary must not be empty")

    if not 1 <= len(response.hypotheses) <= MAX_HYPOTHESES:
        errors.append(f"there must be 1 to {MAX_HYPOTHESES} hypotheses, got {len(response.hypotheses)}")

    for i, hypothesis in enumerate(response.hypotheses, start=1):
        if not hypothesis.title.strip() or not hypothesis.reasoning.strip():
            errors.append(f"hypothesis {i} must have a non-empty title and reasoning")
        if any(not step.strip() for step in hypothesis.next_steps):
            errors.append(f"hypothesis {i} contains empty next_steps")
        if not MIN_NEXT_STEPS <= len(hypothesis.next_steps) <= MAX_NEXT_STEPS:
            errors.append(
                f"hypothesis {i} must have {MIN_NEXT_STEPS} to {MAX_NEXT_STEPS} next_steps, "
                f"got {len(hypothesis.next_steps)}"
            )

    prose = " ".join([response.summary, *(h.reasoning for h in response.hypotheses)])
    language = _detect_language(prose)
    if language is not None and language != "en":
        errors.append(f'the answer must be in English, detected language "{language}"')

    return errors


def _refine_prompt(errors: list[str]) -> str:
    return REFINE_PROMPT.format(problems="\n".join(f"- {e}" for e in errors))


client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
RESPONSE_SCHEMA = transform_schema(Response.model_json_schema())


# noinspection PyTypeChecker
async def _generate(messages: list[MessageParam]) -> Message:
    try:
        return await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={
                "effort": settings.llm_effort,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
        )
    except APIError as exc:
        raise IncidentClassificationError([f"LLM API error: {exc}"]) from exc


async def classify_incident(incident_desc: str) -> Response:
    parsed = parse_input(incident_desc)
    logger.info(
        "parsed incident: services=%s http_codes=%s language=%s",
        parsed.services, parsed.http_codes, parsed.language,
    )

    messages: list[MessageParam] = [{"role": "user", "content": build_context(parsed)}]
    errors: list[str] = []

    for attempt in range(1, settings.llm_max_attempts + 1):
        message = await _generate(messages)
        response, errors = _extract(message)
        if response is not None:
            errors = validate(response)

        if not errors:
            logger.info("classified on attempt %d: %s", attempt, response.category)
            return response

        logger.warning("attempt %d/%d rejected: %s", attempt, settings.llm_max_attempts, errors)
        if message.content:
            messages.append({"role": "assistant", "content": message.content})
        messages.append({"role": "user", "content": _refine_prompt(errors)})

    raise IncidentClassificationError(errors)
