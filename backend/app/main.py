from fastapi import FastAPI

from app import auth
from app.errors import install_error_handlers
from app.security import LoginLimiter


def create_app() -> FastAPI:
    application = FastAPI(title="Assistant alternance", docs_url=None, redoc_url=None)
    application.state.login_limiter = LoginLimiter()
    install_error_handlers(application)
    application.include_router(auth.router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
