from pydantic import BaseModel, ConfigDict

SERVICES = (
    "api-gateway",
    "auth-service",
    "payment-service",
    "billing-service",
    "notification-service",
    "reporting-service",
)

CATEGORY_PREFIXES = (*SERVICES, "unknown")

MAX_HYPOTHESES = 3
MIN_NEXT_STEPS = 2
MAX_NEXT_STEPS = 3

SYSTEM_DESCRIPTION = """\
Our payment platform consists of the following main services:

- api-gateway: receives external HTTP requests from clients and routes them to internal services.
- auth-service: authentication and token issuance.
- payment-service: creation and processing of payment transactions.
- billing-service: balance management and invoicing.
- notification-service: sending e-mail and SMS notifications.
- reporting-service: generating reports and exporting data.

General notes:
- All services write logs to a centralized log storage (ELK).
- The main database is PostgreSQL, with separate instances for payment-service and billing-service.
- Payments often experience external provider errors (timeout, 5xx, invalid credentials).
- notification-service may degrade when external SMTP/SMS providers have issues.
- reporting-service puts extra load on the DB with long analytical queries."""


class PastIncident(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    services: tuple[str, ...]
    category: str


PAST_INCIDENTS = (
    PastIncident(
        id="INC-101",
        text=(
            "Customers report that they cannot pay by card. "
            "In payment-service logs we see massive timeouts when calling the PayGate provider. "
            "The issue started around 12:05 UTC. No other metric anomalies were noticed."
        ),
        services=("payment-service",),
        category="[payment-service] - PayGate provider timeouts",
    ),
    PastIncident(
        id="INC-102",
        text=(
            "Sharp increase in response time for /payments/create (up to 5-7 seconds). "
            "DB dashboards show high CPU and many long-running queries from reporting-service. "
            "Some customers receive 504 Gateway Timeout from api-gateway."
        ),
        services=("reporting-service", "payment-service", "api-gateway"),
        category="[reporting-service] - DB degradation caused by analytical queries",
    ),
    PastIncident(
        id="INC-103",
        text=(
            "Users do not receive top-up confirmation e-mails. "
            "Money is credited successfully, balances are correct. "
            "In notification-service logs there are intermittent connection errors to the SMTP provider."
        ),
        services=("notification-service", "billing-service"),
        category="[notification-service] - SMTP provider connection errors",
    ),
    PastIncident(
        id="INC-104",
        text=(
            "Some customers cannot log in via the mobile app. "
            "auth-service responds with 401 errors. "
            "Logs show messages about invalid token signatures. "
            "No large-scale failures in other services."
        ),
        services=("auth-service",),
        category="[auth-service] - invalid token signatures",
    ),
)
