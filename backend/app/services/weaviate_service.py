import weaviate
from weaviate.classes.init import Auth
from weaviate.classes.config import Property, DataType
from app.config import settings
from langchain_openai import AzureOpenAIEmbeddings

client = None
embedder = None

def init_weaviate_client():
    global client, embedder
    
    if settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME:
        embedder = AzureOpenAIEmbeddings(
            azure_deployment=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME
        )
    else:
        print("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME not set. Embeddings will fail.")
    
    if settings.WEAVIATE_URL:
        try:
            client = weaviate.connect_to_weaviate_cloud(
                cluster_url=settings.WEAVIATE_URL,
                auth_credentials=Auth.api_key(settings.WEAVIATE_API_KEY) if settings.WEAVIATE_API_KEY else None,
            )
            print("✅ Weaviate client connected successfully")
        except Exception as e:
            print(f"⚠️ Failed to connect to Weaviate: {e}")
            print("⚠️ Vector search will be disabled. BM25 search will still work.")
            client = None
    else:
        print("⚠️ WEAVIATE_URL not set. Vector search will be disabled. BM25 search will still work.")

def ensure_weaviate_schema():
    if not client:
        return
    if not client.collections.exists("DocumentChunk"):
        client.collections.create(
            name="DocumentChunk",
            properties=[
                Property(name="text", data_type=DataType.TEXT),
                Property(name="doc_id", data_type=DataType.TEXT),
                Property(name="conversation_id", data_type=DataType.TEXT)
            ]
        )

def embed_and_index_docs(docs, doc_id=None, conversation_id=None):
    if not embedder:
        raise RuntimeError("Azure OpenAI embeddings not configured")
    if not client:
        print("⚠️ Weaviate client not available. Skipping vector indexing.")
        return None
    
    if not docs:
        print("⚠️ No documents to index")
        return None
    
    try:
        ensure_weaviate_schema()
        collection = client.collections.get("DocumentChunk")
        
        indexed_count = 0
        for i, doc in enumerate(docs):
            try:
                content = doc.page_content.strip()
                if not content:
                    print(f"⚠️ Skipping empty document chunk {i+1}")
                    continue
                
                # Generate embedding
                vec = embedder.embed_query(content)
                
                # Insert into Weaviate
                collection.data.insert(
                    properties={
                        "text": content,
                        "doc_id": doc_id or "",
                        "conversation_id": conversation_id or ""
                    },
                    vector=vec
                )
                indexed_count += 1
                
            except Exception as chunk_error:
                print(f"⚠️ Error indexing chunk {i+1}: {chunk_error}")
                continue
        
        print(f"✅ Successfully indexed {indexed_count}/{len(docs)} document chunks for doc_id: {doc_id}")
        return collection
        
    except Exception as e:
        print(f"⚠️ Error in embed_and_index_docs: {e}")
        import traceback
        traceback.print_exc()
        raise

def retrieve_docs_from_disk(conversation_id, query, k=4):
    """Fallback: Read documents directly from disk when Weaviate is unavailable"""
    if not conversation_id:
        return []
    
    try:
        from app.database import get_uploaded_documents
        from app.config import settings
        from app.routers.documents import process_document
        from langchain_core.documents import Document
        import os
        
        doc_records = get_uploaded_documents(conversation_id)
        if not doc_records:
            return []
        
        all_docs = []
        documents_dir = os.path.abspath(settings.DOCUMENTS_DIR)
        
        for doc_record in doc_records:
            doc_id = doc_record["id"]
            file_type = doc_record.get("file_type", "")
            file_path = os.path.join(documents_dir, f"{doc_id}{file_type}")
            
            if os.path.exists(file_path):
                try:
                    with open(file_path, "rb") as f:
                        file_content = f.read()
                    
                    # Process the document
                    processed_docs = process_document(file_content, file_type)
                    for doc in processed_docs:
                        all_docs.append(Document(
                            page_content=doc.page_content,
                            metadata={"doc_id": doc_id, "source": doc_record.get("name", "")}
                        ))
                except Exception as e:
                    print(f"⚠️ Error reading document {doc_id}: {e}")
                    continue
        
        if not all_docs:
            return []
        
        # Simple keyword-based ranking (fallback when no vector search)
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored_docs = []
        for doc in all_docs:
            content_lower = doc.page_content.lower()
            # Count matching words
            matches = sum(1 for word in query_words if word in content_lower)
            if matches > 0:
                scored_docs.append((matches, doc))
        
        # Sort by match count and return top k
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored_docs[:k]]
        
    except Exception as e:
        print(f"⚠️ Error in disk fallback retrieval: {e}")
        import traceback
        traceback.print_exc()
        return []

def retrieve_docs(query, k=4, conversation_id=None):
    if not embedder:
        print("⚠️ Embedder not initialized")
        # Try disk fallback
        if conversation_id:
            print("🔄 Trying disk fallback retrieval...")
            return retrieve_docs_from_disk(conversation_id, query, k)
        return []
    if not client:
        print("⚠️ Weaviate client not initialized")
        # Try disk fallback
        if conversation_id:
            print("🔄 Trying disk fallback retrieval...")
            return retrieve_docs_from_disk(conversation_id, query, k)
        return []
    
    try:
        ensure_weaviate_schema()
        
        if not client.collections.exists("DocumentChunk"):
            print("⚠️ DocumentChunk collection does not exist")
            # Try disk fallback
            if conversation_id:
                print("🔄 Trying disk fallback retrieval...")
                return retrieve_docs_from_disk(conversation_id, query, k)
            return []
        
        collection = client.collections.get("DocumentChunk")
        
        if conversation_id:
            from app.database import get_uploaded_documents
            doc_records = get_uploaded_documents(conversation_id)
            doc_ids = [doc["id"] for doc in doc_records]
            
            print(f"🔍 Retrieving docs for conversation {conversation_id}, doc_ids: {doc_ids}")
            
            if not doc_ids:
                print("⚠️ No document IDs found for conversation")
                return []
            
            # Try vector search first
            try:
                vec = embedder.embed_query(query)
                from weaviate.classes.query import Filter
                
                res = collection.query.near_vector(
                    near_vector=vec,
                    limit=k * 3,  # Get more results to filter
                    filters=Filter.by_property("doc_id").contains_any(doc_ids)
                )
                
                from langchain_core.documents import Document
                filtered_docs = [
                    Document(
                        page_content=o.properties["text"],
                        metadata={"doc_id": o.properties.get("doc_id", ""), "source": o.properties.get("doc_id", "")}
                    ) 
                    for o in res.objects 
                    if o.properties.get("doc_id") in doc_ids and o.properties.get("text", "").strip()
                ]
                
                if filtered_docs:
                    print(f"✅ Vector search found {len(filtered_docs)} documents")
                    return filtered_docs[:k]
                else:
                    print("⚠️ Vector search returned no matching documents, trying fallback...")
            except Exception as vec_error:
                print(f"⚠️ Vector search failed: {vec_error}, trying fallback...")
            
            # Fallback: fetch all chunks from these documents
            try:
                from weaviate.classes.query import Filter
                from langchain_core.documents import Document
                
                res = collection.query.fetch_objects(
                    limit=min(k * 2, 20),
                    filters=Filter.by_property("doc_id").contains_any(doc_ids)
                )
                
                if res.objects:
                    fallback_docs = [
                        Document(
                            page_content=o.properties["text"],
                            metadata={"doc_id": o.properties.get("doc_id", ""), "source": o.properties.get("doc_id", "")}
                        )
                        for o in res.objects
                        if o.properties.get("text", "").strip()
                    ]
                    if fallback_docs:
                        print(f"✅ Fallback retrieval found {len(fallback_docs)} documents")
                        return fallback_docs[:k]
            except Exception as fallback_error:
                print(f"⚠️ Fallback retrieval also failed: {fallback_error}")
            
            # Final fallback: try disk retrieval
            print("🔄 Weaviate retrieval failed, trying disk fallback...")
            return retrieve_docs_from_disk(conversation_id, query, k)
        else:
            # No conversation_id - search all documents
            try:
                vec = embedder.embed_query(query)
                res = collection.query.near_vector(near_vector=vec, limit=k)
                from langchain_core.documents import Document
                docs = [
                    Document(
                        page_content=o.properties["text"],
                        metadata={"doc_id": o.properties.get("doc_id", ""), "source": o.properties.get("doc_id", "")}
                    )
                    for o in res.objects
                    if o.properties.get("text", "").strip()
                ]
                print(f"✅ Retrieved {len(docs)} documents (no conversation filter)")
                return docs
            except Exception as e:
                print(f"⚠️ Error in global search: {e}")
                return []
    except Exception as e:
        print(f"⚠️ Error retrieving docs from Weaviate: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_client():
    return client

def get_embedder():
    return embedder

def retrieve_docs_from_disk(conversation_id, query, k=4):
    """Fallback: Read documents directly from disk when Weaviate is unavailable"""
    if not conversation_id:
        return []
    
    try:
        from app.database import get_uploaded_documents
        from app.config import settings
        from app.routers.documents import process_document
        from langchain_core.documents import Document
        import os
        
        doc_records = get_uploaded_documents(conversation_id)
        if not doc_records:
            print("⚠️ No documents found in database for disk fallback")
            return []
        
        print(f"🔄 Reading {len(doc_records)} document(s) from disk...")
        all_docs = []
        documents_dir = os.path.abspath(settings.DOCUMENTS_DIR)
        
        for doc_record in doc_records:
            doc_id = doc_record["id"]
            file_type = doc_record.get("file_type", "")
            file_path = os.path.join(documents_dir, f"{doc_id}{file_type}")
            
            if os.path.exists(file_path):
                try:
                    with open(file_path, "rb") as f:
                        file_content = f.read()
                    
                    # Process the document
                    processed_docs = process_document(file_content, file_type)
                    for doc in processed_docs:
                        all_docs.append(Document(
                            page_content=doc.page_content,
                            metadata={"doc_id": doc_id, "source": doc_record.get("name", "")}
                        ))
                    print(f"✅ Loaded document: {doc_record.get('name', doc_id)}")
                except Exception as e:
                    print(f"⚠️ Error reading document {doc_id}: {e}")
                    continue
            else:
                print(f"⚠️ Document file not found: {file_path}")
        
        if not all_docs:
            print("⚠️ No document content extracted from disk")
            return []
        
        # Simple keyword-based ranking (fallback when no vector search)
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored_docs = []
        for doc in all_docs:
            content_lower = doc.page_content.lower()
            # Count matching words
            matches = sum(1 for word in query_words if word in content_lower)
            # Also check for phrase matches
            if query_lower in content_lower:
                matches += 10  # Boost for exact phrase
            if matches > 0:
                scored_docs.append((matches, doc))
        
        # Sort by match count and return top k
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        result = [doc for _, doc in scored_docs[:k]]
        
        if result:
            print(f"✅ Disk fallback found {len(result)} relevant document chunks")
        else:
            # If no matches, return first k documents anyway
            result = all_docs[:k]
            print(f"✅ Disk fallback returning {len(result)} document chunks (no keyword matches)")
        
        return result
        
    except Exception as e:
        print(f"⚠️ Error in disk fallback retrieval: {e}")
        import traceback
        traceback.print_exc()
        return []

