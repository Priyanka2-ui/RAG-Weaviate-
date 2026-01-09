from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Optional
import mlflow

from app.config import settings
from app.database import init_db
from app.services.sql_agent_service import init_sql_agent
from app.services.weaviate_service import init_weaviate_client
from app.routers import chat, documents, auth, feedback, conversations
from app.utils.auth import get_user_from_jwt

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_weaviate_client()
    init_sql_agent()
    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    mlflow.set_experiment("rag-chat-system")
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc) if str(exc) else "Internal server error",
            "error": "An error occurred processing your request"
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

app.include_router(chat.router, tags=["chat"])
app.include_router(documents.router, tags=["documents"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(feedback.router, tags=["feedback"])
app.include_router(conversations.router, tags=["conversations"])

@app.get("/me")
async def me(authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    user = get_user_from_jwt(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

@app.get("/status")
async def status():
    from app.services.document_service import get_uploaded_docs_count
    return {"status": "running", "docs_uploaded": get_uploaded_docs_count()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)