"""Run module ASGI apps in this process and own all their lifespans."""
from contextlib import AsyncExitStack, asynccontextmanager
import logging

from starlette.responses import JSONResponse

logger = logging.getLogger('uvicorn.error')
MOUNTS = {'context': '/modules/context', 'rag': '/modules/rag',
          'kg': '/modules/kg', 'kg_explorer': '/modules/kg-explorer'}


class AvailabilityMiddleware:
    def __init__(self, app, module_app):
        self.app, self.module_app = app, module_app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and not self.module_app.state.available:
            response = JSONResponse({'detail': 'Module chưa khởi tạo thành công. Kiểm tra log module.startup_failed rồi khởi động lại backend.',
                                     'module': self.module_app.state.module_name}, status_code=503)
            return await response(scope, receive, send)
        await self.app(scope, receive, send)


def create_module_apps():
    from .modules.context.main import create_app as create_context
    from .modules.rag.main import create_app as create_rag
    from .modules.kg_query.retrieval_api import create_app as create_kg
    from .modules.kg_query.web_app import create_app as create_explorer
    apps = {'context': create_context(), 'rag': create_rag(), 'kg': create_kg(),
            'kg_explorer': create_explorer()}
    for name, module_app in apps.items():
        module_app.state.available = False
        module_app.state.module_name = name
        module_app.add_middleware(AvailabilityMiddleware, module_app=module_app)
    return apps


@asynccontextmanager
async def module_lifespans(apps):
    async with AsyncExitStack() as stack:
        for name, module_app in apps.items():
            try:
                await stack.enter_async_context(module_app.router.lifespan_context(module_app))
                module_app.state.available = True
                logger.info('module.started name=%s mount=%s', name, MOUNTS[name])
            except Exception:
                module_app.state.available = False
                logger.exception('module.startup_failed name=%s', name)
        try:
            yield
        finally:
            for module_app in apps.values():
                module_app.state.available = False
