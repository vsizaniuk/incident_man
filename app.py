import logging
from fastapi import FastAPI

from src.config import settings
from src.rest import router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

app = FastAPI(title="Incident Assistant")
app.include_router(router)
