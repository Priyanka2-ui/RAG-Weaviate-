from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from app.utils.auth import require_user
from app.database import (
    ensure_conversation,
    add_uploaded_document_record,
    get_uploaded_documents,
    delete_uploaded_document_record
)
from app.config import settings
from app.services.weaviate_service import embed_and_index_docs
import uuid
import os
from pathlib import Path

router = APIRouter()

def get_file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()

def process_document(file_content: bytes, file_type: str):
    from langchain_community.document_loaders import PyPDFLoader, TextLoader, CSVLoader
    from langchain_community.document_loaders import UnstructuredWordDocumentLoader
    from langchain_community.document_loaders import UnstructuredExcelLoader
    import tempfile
    import io
    
    docs = []
    
    try:
        if file_type == ".pdf":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name
            try:
                loader = PyPDFLoader(tmp_path)
                docs = loader.load()
            finally:
                os.unlink(tmp_path)
        
        elif file_type == ".txt":
            loader = TextLoader(io.BytesIO(file_content))
            docs = loader.load()
        
        elif file_type == ".csv":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name
            try:
                loader = CSVLoader(tmp_path)
                docs = loader.load()
            finally:
                os.unlink(tmp_path)
        
        elif file_type in [".xls", ".xlsx"]:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_type) as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name
            try:
                loader = UnstructuredExcelLoader(tmp_path)
                docs = loader.load()
            finally:
                os.unlink(tmp_path)
        
        elif file_type in [".doc", ".docx"]:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_type) as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name
            try:
                loader = UnstructuredWordDocumentLoader(tmp_path)
                docs = loader.load()
            finally:
                os.unlink(tmp_path)
        
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
    
    except Exception as e:
        print(f"Error processing document: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to process document: {str(e)}")
    
    return docs

@router.post("/upload_document")
async def upload_document(
    file: UploadFile = File(...),
    conversation_id: str | None = Form(None),
    current_user: dict = Depends(require_user),
):
    try:
        file_content = await file.read()
        file_type = get_file_extension(file.filename)
        
        allowed_types = {".pdf", ".txt", ".csv", ".xls", ".xlsx", ".doc", ".docx", ".pptx", ".ppt"}
        if file_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed: {', '.join(allowed_types)}"
            )
        
        conversation_id = ensure_conversation(conversation_id, current_user["id"])
        
        doc_id = str(uuid.uuid4())
        
        docs = process_document(file_content, file_type)
        
        if not docs:
            raise HTTPException(status_code=400, detail="Document processing returned no content")
        
        documents_dir = os.path.abspath(settings.DOCUMENTS_DIR)
        os.makedirs(documents_dir, exist_ok=True, mode=0o755)
        
        file_path = os.path.join(documents_dir, f"{doc_id}{file_type}")
        
        try:
            with open(file_path, "wb") as f:
                f.write(file_content)
            os.chmod(file_path, 0o644)
        except PermissionError as e:
            import stat
            dir_stat = os.stat(documents_dir)
            raise HTTPException(
                status_code=500,
                detail=f"Permission denied when saving file to {documents_dir}. Directory permissions: {oct(dir_stat.st_mode)}. Error: {str(e)}"
            )
        except OSError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save file: {str(e)}"
            )
        
        add_uploaded_document_record(
            conversation_id=conversation_id,
            doc_id=doc_id,
            name=file.filename,
            file_type=file_type,
            user_id=current_user["id"]
        )
        
        embed_and_index_docs(docs, doc_id=doc_id, conversation_id=conversation_id)
        
        return {
            "message": "Document uploaded successfully",
            "document_id": doc_id,
            "conversation_id": conversation_id,
            "filename": file.filename
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Upload error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@router.post("/remove_document")
async def remove_document_endpoint(
    document_id: str = Form(...),
    current_user: dict = Depends(require_user),
):
    try:
        from app.services.weaviate_service import get_client
        from weaviate.classes.query import Filter
        
        client = get_client()
        if client:
            try:
                collection = client.collections.get("DocumentChunk")
                collection.data.delete_many(
                    where=Filter.by_property("doc_id").equal(document_id)
                )
            except Exception as e:
                print(f"Error deleting from Weaviate: {e}")
        
        file_path = os.path.join(settings.DOCUMENTS_DIR, document_id)
        for ext in [".pdf", ".txt", ".csv", ".xls", ".xlsx", ".doc", ".docx", ".pptx", ".ppt"]:
            full_path = f"{file_path}{ext}"
            if os.path.exists(full_path):
                os.remove(full_path)
                break
        
        delete_uploaded_document_record(document_id)
        
        return {"message": "Document removed successfully", "document_id": document_id}
    
    except Exception as e:
        print(f"Remove error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove document: {str(e)}")

@router.get("/documents")
async def list_documents(
    conversation_id: str = Query(...),
    current_user: dict = Depends(require_user),
):
    try:
        from app.database import ensure_conversation
        ensure_conversation(conversation_id, current_user["id"])
        
        documents = get_uploaded_documents(conversation_id)
        
        return {"documents": documents}
    
    except Exception as e:
        print(f"List documents error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")
