from fastapi import FastAPI

from app import applications, auth, dashboard, offers, statuses
from app.errors import install_error_handlers
from app.security import LoginLimiter


def create_app() -> FastAPI:
    application = FastAPI(title="Assistant alternance", docs_url=None, redoc_url=None)
    application.state.login_limiter = LoginLimiter()
    install_error_handlers(application)
    application.include_router(auth.router)
    application.include_router(statuses.router)
    application.include_router(applications.router)
    application.include_router(offers.router)
    application.include_router(dashboard.router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
