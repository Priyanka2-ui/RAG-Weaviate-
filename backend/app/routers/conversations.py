from fastapi import APIRouter, HTTPException, Depends, Query, Form
from app.utils.auth import require_user
from app.database import (
    get_user_conversations,
    get_chat_history,
    ensure_conversation,
    clear_messages,
    delete_conversation
)

router = APIRouter()

@router.get("/conversations")
async def list_conversations(current_user: dict = Depends(require_user)):
    conversations = get_user_conversations(current_user["id"])
    return {"conversations": conversations}

@router.get("/conversations/current")
async def get_current_conversation(current_user: dict = Depends(require_user)):
    conversations = get_user_conversations(current_user["id"])
    if conversations:
        conversation_id = conversations[0]["id"]
    else:
        conversation_id = ensure_conversation(None, current_user["id"])
    
    return {
        "conversation_id": conversation_id,
        "chat_history": get_chat_history(conversation_id)
    }

@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, current_user: dict = Depends(require_user)):
    ensure_conversation(conversation_id, current_user["id"])
    return {
        "conversation_id": conversation_id,
        "chat_history": get_chat_history(conversation_id, include_ids=True)
    }

@router.delete("/conversations/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: str, current_user: dict = Depends(require_user)):
    success = delete_conversation(conversation_id, current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied")
    return {"message": "Conversation deleted successfully"}

@router.get("/history")
async def get_history(conversation_id: str = Query(...), current_user: dict = Depends(require_user)):
    ensure_conversation(conversation_id, current_user["id"])
    return {"conversation_id": conversation_id, "chat_history": get_chat_history(conversation_id)}

@router.post("/clear_history")
async def clear_history(conversation_id: str = Form(...), current_user: dict = Depends(require_user)):
    ensure_conversation(conversation_id, current_user["id"])
    clear_messages(conversation_id)
    return {"message": "History cleared.", "conversation_id": conversation_id}

