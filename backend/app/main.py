from fastapi import FastAPI

from app import account, applications, auth, dashboard, offers, preferences, profile, statuses
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
    application.include_router(preferences.router)
    application.include_router(account.router)
    application.include_router(profile.router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
