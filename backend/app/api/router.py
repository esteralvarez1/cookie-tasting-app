from fastapi import APIRouter

from app.api.routes import debug, evaluations, exports, health, sessions, tasting_sessions

api_router = APIRouter(prefix='/api/v1')
api_router.include_router(health.router)
api_router.include_router(debug.router)
api_router.include_router(tasting_sessions.router)
api_router.include_router(sessions.router)
api_router.include_router(evaluations.router)
api_router.include_router(exports.router)
