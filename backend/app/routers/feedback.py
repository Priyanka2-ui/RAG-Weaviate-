from fastapi import APIRouter, Form, HTTPException, Depends
from app.utils.auth import require_user
from app.database import get_db_connection
import uuid

router = APIRouter()

@router.post("/feedback")
async def save_feedback(
    message_id: str = Form(...),
    feedback_type: str = Form(...),
    detailed_feedback: str = Form(None),
    current_user: dict = Depends(require_user),
):
    if feedback_type not in ["thumbs_up", "thumbs_down"]:
        raise HTTPException(status_code=400, detail="feedback_type must be 'thumbs_up' or 'thumbs_down'")
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT conversation_id FROM messages WHERE id = ?", (message_id,))
    msg_row = cur.fetchone()
    if not msg_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Message not found")
    conversation_id = msg_row[0]
    
    cur.execute(
        "SELECT id FROM feedback WHERE message_id = ? AND user_id = ?",
        (message_id, current_user["id"])
    )
    existing = cur.fetchone()
    
    feedback_id = str(uuid.uuid4())
    if existing:
        cur.execute(
            "UPDATE feedback SET feedback_type = ?, detailed_feedback = ? WHERE id = ?",
            (feedback_type, detailed_feedback, existing[0])
        )
        feedback_id = existing[0]
    else:
        cur.execute(
            "INSERT INTO feedback(id, message_id, conversation_id, user_id, feedback_type, detailed_feedback) VALUES (?, ?, ?, ?, ?, ?)",
            (feedback_id, message_id, conversation_id, current_user["id"], feedback_type, detailed_feedback)
        )
    
    conn.commit()
    conn.close()
    
    return {"message": "Feedback saved", "feedback_id": feedback_id}

@router.get("/feedback/{message_id}")
async def get_feedback(message_id: str, current_user: dict = Depends(require_user)):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT feedback_type, detailed_feedback, created_at FROM feedback WHERE message_id = ? AND user_id = ?",
        (message_id, current_user["id"])
    )
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return {"feedback": None}
    
    return {
        "feedback": {
            "feedback_type": row[0],
            "detailed_feedback": row[1],
            "created_at": row[2],
        }
    }

