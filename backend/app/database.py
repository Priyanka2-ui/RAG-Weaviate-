import sqlite3
import uuid
import json
from typing import Optional, List, Dict, Any
from app.config import settings

def get_db_connection():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            response_time_ms INTEGER,
            token_count INTEGER,
            model_version TEXT,
            rag_references TEXT,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_documents (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            name TEXT,
            file_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt BLOB NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','user')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            feedback_type TEXT NOT NULL CHECK(feedback_type IN ('thumbs_up', 'thumbs_down')),
            detailed_feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(message_id) REFERENCES messages(id),
            FOREIGN KEY(conversation_id) REFERENCES conversations(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    
    try:
        cur.execute("SELECT user_id FROM uploaded_documents LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE uploaded_documents ADD COLUMN user_id TEXT")
    
    try:
        cur.execute("SELECT user_id FROM conversations LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT")
    
    try:
        cur.execute("SELECT response_time_ms FROM messages LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE messages ADD COLUMN response_time_ms INTEGER")
        cur.execute("ALTER TABLE messages ADD COLUMN token_count INTEGER")
        cur.execute("ALTER TABLE messages ADD COLUMN model_version TEXT")
    
    try:
        cur.execute("SELECT rag_references FROM messages LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE messages ADD COLUMN rag_references TEXT")
    
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_message_id ON feedback(message_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id)")
    except Exception:
        pass
    
    conn.commit()
    conn.close()

def ensure_conversation(conversation_id: Optional[str], user_id: Optional[str] = None) -> str:
    cid = conversation_id or str(uuid.uuid4())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO conversations(id, user_id) VALUES (?, ?)", (cid, user_id))
    conn.commit()
    conn.close()
    return cid

def add_message(
    conversation_id: str,
    role: str,
    content: str,
    response_time_ms: Optional[int] = None,
    token_count: Optional[int] = None,
    model_version: Optional[str] = None,
    references: Optional[List[str]] = None
) -> str:
    message_id = str(uuid.uuid4())
    conn = get_db_connection()
    cur = conn.cursor()
    references_json = None
    if references:
        references_json = json.dumps(references)
    cur.execute(
        "INSERT INTO messages(id, conversation_id, role, content, response_time_ms, token_count, model_version, rag_references) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (message_id, conversation_id, role, content, response_time_ms, token_count, model_version, references_json),
    )
    conn.commit()
    conn.close()
    return message_id

def get_chat_history(conversation_id: str, include_ids: bool = False) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    if include_ids:
        cur.execute(
            "SELECT id, role, content, rag_references FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        )
    else:
        cur.execute(
            "SELECT role, content, rag_references FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        )
    rows = cur.fetchall()
    conn.close()
    
    paired = []
    current = {}
    for row in rows:
        if include_ids:
            msg_id = row["id"]
            role = row["role"]
            content = row["content"]
            references_json = row["rag_references"] if "rag_references" in row.keys() else None
        else:
            role = row["role"]
            content = row["content"]
            references_json = row["rag_references"] if "rag_references" in row.keys() else None
            msg_id = None
        
        references = None
        if references_json:
            try:
                references = json.loads(references_json)
            except:
                references = None
        
        if role == "user":
            if current:
                paired.append(current)
            current = {"user": content}
            if include_ids:
                current["user_message_id"] = msg_id
        else:
            if current:
                current["assistant"] = content
                if include_ids:
                    current["message_id"] = msg_id
                if references:
                    current["references"] = references
                paired.append(current)
                current = {}
            else:
                item = {"user": "", "assistant": content}
                if include_ids:
                    item["message_id"] = msg_id
                if references:
                    item["references"] = references
                paired.append(item)
    if current:
        paired.append(current)
    return paired

def get_user_conversations(user_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.created_at, 
               (SELECT content FROM messages 
                WHERE conversation_id = c.id AND role = 'user' 
                ORDER BY created_at ASC LIMIT 1) as title
        FROM conversations c 
        WHERE c.user_id = ? 
        ORDER BY c.created_at DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    conversations = []
    for row in rows:
        conv_id, created_at, title = row
        display_title = (title[:50] + "...") if title and len(title) > 50 else (title or "New Chat")
        conversations.append({
            "id": conv_id,
            "created_at": created_at,
            "title": display_title
        })
    return conversations

def add_uploaded_document_record(
    conversation_id: Optional[str],
    doc_id: str,
    name: str,
    file_type: str,
    user_id: Optional[str] = None
):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO uploaded_documents(id, conversation_id, name, file_type, user_id) VALUES (?, ?, ?, ?, ?)",
        (doc_id, conversation_id, name, file_type, user_id),
    )
    conn.commit()
    conn.close()

def get_uploaded_documents(conversation_id: str) -> List[Dict[str, str]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, file_type FROM uploaded_documents WHERE conversation_id = ? ORDER BY created_at ASC",
        (conversation_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "file_type": r["file_type"] if "file_type" in r.keys() else ""
        }
        for r in rows
    ]

def delete_uploaded_document_record(doc_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM uploaded_documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()

def clear_messages(conversation_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.commit()
    conn.close()

def delete_conversation(conversation_id: str, user_id: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT user_id FROM conversations WHERE id = ?", (conversation_id,))
    row = cur.fetchone()
    if not row or row[0] != user_id:
        conn.close()
        return False
    
    cur.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    cur.execute("DELETE FROM uploaded_documents WHERE conversation_id = ?", (conversation_id,))
    cur.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    
    conn.commit()
    conn.close()
    return True

def has_uploaded_document_named(name: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM uploaded_documents WHERE name = ? LIMIT 1", (name,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists

