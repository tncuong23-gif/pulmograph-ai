from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.modules.context.api.routes import router
from app.modules.context.config import get_settings
from app.modules.context.container import ApplicationContainer


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    container = ApplicationContainer.build(settings)
    try:
        await container.initialize()
        app.state.container = container
        yield
    finally:
        await container.close()


def create_app():
    app = FastAPI(
        title="Medical Context Graph Gateway",
        version="0.2.3",
        description=(
            "Restores conversational context and maintains History/Patient graphs "
            "before downstream medical knowledge-graph reasoning."
        ),
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
