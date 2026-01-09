from fastapi import APIRouter, Form, HTTPException, Depends
from app.utils.auth import require_user
from app.database import (
    ensure_conversation,
    add_message,
    get_chat_history,
    get_uploaded_documents
)
from app.services.weaviate_service import retrieve_docs
from app.services.sql_agent_service import get_sql_agent, is_sql_query
from app.config import settings
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
import json
import time
import mlflow
import re

router = APIRouter()

SQL_FILE_TYPES = {".csv", ".xls", ".xlsx", ".tsv"}
DOCUMENT_FILE_TYPES = {".pdf", ".docx", ".doc", ".txt", ".pptx", ".ppt"}

def clean_markdown(text: str) -> str:
    if not text:
        return text
    
    text = re.sub(r'\*\*\*(.*?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    
    return text

async def needs_web_search(query: str, llm, has_documents: bool = False) -> bool:
    """Use Runnable pattern to determine if web search is needed."""
    if has_documents:
        system_prompt = """You are a routing assistant. The user has uploaded documents. Determine if the query MUST use web search for real-time information that cannot be found in documents.

Return ONLY "YES" if the query ABSOLUTELY requires current/real-time information that documents cannot provide (e.g., current date, today's weather, latest news, recent sports results, current stock prices, breaking news).

Return ONLY "NO" if the query can be answered from documents, general knowledge, or doesn't need real-time info. When documents are available, prefer using them.

Examples that need web search (even with documents):
- "what's today's date?"
- "current weather in New York"
- "latest news about AI"
- "who won the cricket match yesterday?"

Examples that DON'T need web search (use documents instead):
- "what is the exam level for..."
- "according to the table..."
- "what does the document say about..."
- "explain the procedure for..."
- "what are the requirements for..."
- Any question about content in uploaded documents

Query: {query}

Answer (YES or NO):"""
    else:
        system_prompt = """You are a routing assistant. Determine if a user query requires real-time, current information that would need a web search to answer accurately.

Return ONLY "YES" if the query needs web search (e.g., current date, recent events, latest news, sports results, stock prices, weather, current statistics, recent matches/games, breaking news, or anything that changes frequently).

Return ONLY "NO" if the query can be answered with general knowledge, historical facts, definitions, explanations, or information that doesn't change frequently.

Query: {query}

Answer (YES or NO):"""

    try:
        # Use Runnable pattern with ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{query}")
        ])
        
        # Create a Runnable chain
        chain = prompt | llm | RunnableLambda(lambda x: x.content.strip().upper() if hasattr(x, "content") else str(x).strip().upper())
        
        response = await chain.ainvoke({"query": query})
        return response.startswith("YES")
    except Exception as e:
        print(f"Error in needs_web_search: {e}")
        return False

def is_document_meta_query(query: str) -> bool:
    query_lower = query.lower().strip()
    
    action_keywords = ["summarize", "explain", "analyze", "what does", "what is in", "tell me about", "describe", "extract", "find", "search", "answer", "according to"]
    if any(query_lower.startswith(action) or f" {action} " in query_lower for action in action_keywords):
        return False
    
    meta_patterns = [
        r"^what (document|file|doc|book) (did|have) (i|you) (upload|uploaded)",
        r"^whats? (the )?(uploaded )?(document|file|doc|book) (name|is|was)",
        r"^(which|what) (document|file|doc|book) (did|have) (i|you)",
        r"^(list|show) (me )?(the )?(uploaded )?(documents|files|docs)",
        r"^(what|which) (is|are) (the )?(name|names) (of )?(the )?(uploaded )?(documents|files|docs)",
        r"^name (of )?(the )?(uploaded )?(document|file|doc|book)"
    ]
    
    import re
    for pattern in meta_patterns:
        if re.search(pattern, query_lower):
            return True
    
    return False

async def is_document_query(query: str, llm, uploaded_docs: list) -> bool:
    """Determine if a query is actually about the uploaded documents or just general conversation using Runnable pattern."""
    if not uploaded_docs:
        return False
    
    # Simple greetings and general conversation should not use RAG
    query_lower = query.lower().strip()
    general_greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "how are you", "what's up", "thanks", "thank you", "bye", "goodbye"]
    
    if query_lower in general_greetings or any(query_lower.startswith(greeting) for greeting in general_greetings):
        return False
    
    # Use LLM to determine if query is about documents
    system_prompt = """You are a routing assistant. The user has uploaded documents. Determine if the query is asking about the CONTENT of those documents or is just general conversation.

Return ONLY "YES" if the query is asking about:
- Content, information, or data FROM the documents
- Questions that can be answered using the documents
- Analysis, summary, or explanation of document content
- Specific facts, details, or information that might be in the documents

Return ONLY "NO" if the query is:
- General greetings (hi, hello, how are you)
- General conversation or chit-chat
- Questions about the AI itself or how it works
- Questions that don't relate to document content
- General knowledge questions that don't reference the documents

Examples that ARE about documents (YES):
- "What does the document say about..."
- "Summarize the uploaded document"
- "What is the capital mentioned in the document?"
- "According to the table, what is..."
- "Explain the procedure in the document"

Examples that are NOT about documents (NO):
- "hi" or "hello"
- "how are you?"
- "what can you do?"
- "what is the capital of India?" (general knowledge, not referencing documents)
- "tell me a joke"

Query: {query}

Answer (YES or NO):"""

    try:
        # Use Runnable pattern with ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{query}")
        ])
        
        # Create a Runnable chain
        chain = prompt | llm | RunnableLambda(lambda x: x.content.strip().upper() if hasattr(x, "content") else str(x).strip().upper())
        
        response = await chain.ainvoke({"query": query})
        return response.startswith("YES")
    except Exception as e:
        print(f"Error in is_document_query: {e}")
        # Default to False (use LLM) if we can't determine
        return False

async def detect_route(query: str, conversation_id: str | None, llm) -> str:
    uploaded_docs = []
    if conversation_id:
        uploaded_docs = get_uploaded_documents(conversation_id)
    
    # Check for document metadata queries first
    if uploaded_docs and is_document_meta_query(query):
        return "doc_meta"
    
    has_sql_files = any(
        doc["file_type"].lower() in SQL_FILE_TYPES 
        for doc in uploaded_docs
    )
    has_doc_files = any(
        doc["file_type"].lower() in DOCUMENT_FILE_TYPES 
        for doc in uploaded_docs
    )
    
    # If no documents uploaded, use LLM (no automatic web search)
    if not uploaded_docs:
        return "llm"
    
    # If SQL files exist, check if it's a SQL query
    if has_sql_files:
        if is_sql_query(query):
            return "sql"
        # If not a SQL query, check if it's about documents
        if has_doc_files:
            is_about_docs = await is_document_query(query, llm, uploaded_docs)
            if is_about_docs:
                return "rag"
            return "llm"
        # Only SQL files, use SQL agent
        return "sql"
    
    # If document files exist, check if query is actually about documents
    if has_doc_files:
        is_about_docs = await is_document_query(query, llm, uploaded_docs)
        if is_about_docs:
            return "rag"
        return "llm"
    
    # Fallback: no recognized file types
    return "llm"

async def handle_rag_query(query: str, conversation_id: str | None, llm, chat_history: list = None):
    """Handle RAG queries using modern Runnable patterns."""
    try:
        print(f"🔍 Starting RAG query: '{query}' for conversation: {conversation_id}")
        
        # Retrieve documents
        retrieved_docs = retrieve_docs(query, k=8, conversation_id=conversation_id)
        
        if not retrieved_docs:
            print(f"⚠️ No documents retrieved for query: {query}")
            # Double-check if documents exist in database
            if conversation_id:
                uploaded_docs = get_uploaded_documents(conversation_id)
                if uploaded_docs:
                    print(f"⚠️ Documents exist in DB ({len(uploaded_docs)}) but not retrieved from Weaviate")
                else:
                    print(f"⚠️ No documents found in database for conversation {conversation_id}")
            return None, None
        
        print(f"✅ Retrieved {len(retrieved_docs)} documents for RAG query")
        
        # Build document context with better chunking
        document_parts = []
        total_length = 0
        max_length = 8000  # Increased context window
        
        for i, doc in enumerate(retrieved_docs):
            content = doc.page_content.strip()
            if not content:
                continue
            
            # Take up to 2000 chars per document, but respect total limit
            chunk_size = min(2000, max_length - total_length)
            if chunk_size <= 0:
                break
            
            if len(content) > chunk_size:
                content = content[:chunk_size] + "..."
            
            document_parts.append(f"[Document Chunk {i+1}]\n{content}")
            total_length += len(content)
            
            if total_length >= max_length:
                break
        
        document_context = "\n\n".join(document_parts)
        
        if not document_context.strip():
            print("⚠️ Document context is empty after processing")
            return None, None
        
        print(f"✅ Built document context ({len(document_context)} chars from {len(document_parts)} chunks)")
        
        # Enhanced system prompt for better RAG responses
        system_prompt = """You are a helpful assistant that answers questions based EXCLUSIVELY on the provided document context.

CRITICAL INSTRUCTIONS:
1. Use ONLY the information from the document context to answer the question.
2. If the context contains tables, data, or specific information, use it directly and accurately.
3. If the question asks you to summarize, analyze, or explain something from the documents, do so based on the provided context.
4. If the context doesn't contain enough information to fully answer the question, say "Based on the provided document context, [partial answer]. However, the document context does not contain complete information to fully answer this question."
5. Be precise, accurate, and detailed in your response.
6. Respond in plain text without any markdown formatting, bold text, asterisks, or special characters.
7. If summarizing, provide a comprehensive summary covering the main points from the document context."""
        
        # Build chat history messages for context
        history_messages = []
        if chat_history:
            for msg in chat_history[-4:]:  # Reduced to 4 to save tokens for document context
                if isinstance(msg, dict):
                    if msg.get("user"):
                        history_messages.append(("human", msg["user"]))
                    if msg.get("assistant"):
                        history_messages.append(("assistant", msg["assistant"]))
        
        # Use ChatPromptTemplate with Runnable pattern
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            *history_messages,
            ("human", """Document Context:
{document_context}

Question: {query}

Based on the document context provided above, please answer the question. If the question asks for a summary, provide a comprehensive summary of the relevant content from the documents.""")
        ])
        
        # Create Runnable chain: prompt | llm | extract content | clean markdown
        extract_content = RunnableLambda(
            lambda x: x.content if hasattr(x, "content") else str(x)
        )
        clean_content = RunnableLambda(lambda x: clean_markdown(x) if x else None)
        
        chain = prompt_template | llm | extract_content | clean_content
        
        print(f"🔍 Invoking LLM with Runnable chain...")
        answer = await chain.ainvoke({
            "document_context": document_context,
            "query": query
        })
        
        if not answer or answer.strip() == "":
            print("⚠️ LLM returned empty answer")
            return None, None
        
        print(f"✅ Generated answer ({len(answer)} chars)")
        
        # Build references from document metadata
        references = []
        seen_doc_ids = set()
        for i, doc in enumerate(retrieved_docs):
            if hasattr(doc, "metadata") and doc.metadata:
                doc_id = doc.metadata.get("doc_id") or doc.metadata.get("source", "")
                if doc_id and doc_id not in seen_doc_ids:
                    # Try to get document name from database
                    if conversation_id:
                        uploaded_docs = get_uploaded_documents(conversation_id)
                        for ud in uploaded_docs:
                            if ud.get("id") == doc_id:
                                references.append(ud.get("name", f"Document {len(references)+1}"))
                                seen_doc_ids.add(doc_id)
                                break
                    if doc_id not in seen_doc_ids:
                        references.append(f"Document {len(references)+1}")
                        seen_doc_ids.add(doc_id)
        
        if not references:
            references = [f"Document {i+1}" for i in range(min(len(retrieved_docs), 3))]
        
        print(f"✅ RAG query completed successfully with {len(references)} references")
        return answer, references[:3]  # Limit to 3 references
        
    except Exception as e:
        print(f"⚠️ Error in handle_rag_query: {e}")
        import traceback
        traceback.print_exc()
        return None, None

async def handle_doc_meta_query(query: str, conversation_id: str | None, uploaded_docs: list) -> tuple:
    if not uploaded_docs:
        return "You haven't uploaded any documents yet.", None
    
    doc_names = [doc.get("name", "Unknown") for doc in uploaded_docs]
    doc_count = len(uploaded_docs)
    
    if doc_count == 1:
        answer = f"You have uploaded 1 document: {doc_names[0]}"
    else:
        doc_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(doc_names)])
        answer = f"You have uploaded {doc_count} documents:\n{doc_list}"
    
    return answer, None

async def handle_sql_query(query: str, conversation_id: str | None, user_id: str):
    sql_agent = get_sql_agent()
    if not sql_agent:
        return None, None
    
    try:
        from langchain_core.messages import HumanMessage
        config = {"configurable": {"thread_id": f"{user_id}_{conversation_id or 'default'}"}}
        result = await sql_agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config
        )
        
        if isinstance(result, dict) and "messages" in result:
            last_message = result["messages"][-1]
            answer = last_message.content if hasattr(last_message, "content") else str(last_message)
        else:
            answer = str(result)
        
        return answer, None
    except Exception as e:
        print(f"SQL Agent error: {e}")
        return None, None

async def handle_serpapi_query(query: str, llm, chat_history: list = None):
    """Handle SerpAPI queries using modern Runnable patterns."""
    if not settings.SERPAPI_API_KEY:
        print("⚠️ SERPAPI_API_KEY not set")
        return None, None
    
    from langchain_community.utilities import SerpAPIWrapper
    
    # Optimize query for better search results
    # Remove conversational phrases and focus on key terms
    optimized_query = query.lower()
    # Remove common conversational phrases
    phrases_to_remove = ["tell me", "can you", "please", "what is", "when is", "where is", "who is"]
    for phrase in phrases_to_remove:
        optimized_query = optimized_query.replace(phrase, "").strip()
    
    # Expand abbreviations for better results
    optimized_query = optimized_query.replace("ind vs sa", "India vs South Africa")
    optimized_query = optimized_query.replace("ind vs", "India vs")
    optimized_query = optimized_query.replace(" vs ", " vs ")
    
    # Add context for sports queries
    if any(word in optimized_query for word in ["cricket", "odi", "test", "t20", "match", "schedule"]):
        if "2025" not in optimized_query:
            optimized_query = f"{optimized_query} 2025"
        if "schedule" not in optimized_query and "match" in optimized_query:
            optimized_query = optimized_query.replace("match", "schedule")
    
    optimized_query = optimized_query.strip()
    if not optimized_query:
        optimized_query = query  # Fallback to original if optimization removed everything
    
    print(f"🔍 SerpAPI search query: '{optimized_query}' (original: '{query}')")
    
    serpapi = SerpAPIWrapper(serpapi_api_key=settings.SERPAPI_API_KEY)
    
    try:
        search_results = serpapi.run(optimized_query)
        
        # Handle both string and dict returns
        if isinstance(search_results, dict):
            # If it's a dict, process it manually using the wrapper's method
            search_results = serpapi._process_response(search_results)
        
        # Ensure it's a string
        if not isinstance(search_results, str):
            search_results = str(search_results)
        
        print(f"✅ SerpAPI returned {len(search_results)} characters of results")
        if len(search_results) > 500:
            print(f"📄 First 500 chars of results: {search_results[:500]}...")
        else:
            print(f"📄 Full results: {search_results}")
        
        if not search_results or not search_results.strip():
            print("⚠️ SerpAPI returned empty results")
            return None, None
    except Exception as e:
        print(f"⚠️ SerpAPI error: {e}")
        import traceback
        traceback.print_exc()
        return None, None
    
    system_prompt = """You are a helpful assistant that answers questions based on web search results.

IMPORTANT INSTRUCTIONS:
1. Carefully analyze ALL the search results provided below.
2. Extract and present the most relevant information, especially dates, schedules, and specific details.
3. If the search results contain information that answers the question, provide that information clearly.
4. If the search results mention dates, times, or schedules, include them in your answer.
5. If there are multiple sources with conflicting information, mention the most recent or most authoritative source.
6. Only say "no information available" if the search results truly contain nothing relevant.
7. Respond in plain text without any markdown formatting, bold text, or special characters.
8. Be precise with dates and facts. Include specific dates, times, and venues when available.

The search results may contain partial information - extract and present what is available, even if incomplete."""
    
    # Build chat history messages for context
    history_messages = []
    if chat_history:
        for msg in chat_history[-6:]:
            if isinstance(msg, dict):
                if msg.get("user"):
                    history_messages.append(("human", msg["user"]))
                if msg.get("assistant"):
                    history_messages.append(("assistant", msg["assistant"]))
            elif isinstance(msg, dict) and "role" in msg:
                if msg.get("role") == "user":
                    history_messages.append(("human", msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    history_messages.append(("assistant", msg.get("content", "")))
    
    # Use ChatPromptTemplate with Runnable pattern
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        *history_messages,
        ("human", """Search Results:
{search_results}

Question: {query}

Provide an accurate answer based on the search results above:""")
    ])
    
    # Create Runnable chain: prompt | llm | extract content | clean markdown
    extract_content = RunnableLambda(
        lambda x: x.content if hasattr(x, "content") else str(x)
    )
    clean_content = RunnableLambda(lambda x: clean_markdown(x) if x else None)
    
    chain = prompt_template | llm | extract_content | clean_content
    
    answer = await chain.ainvoke({
        "search_results": search_results,
        "query": query
    })
    
    # SerpAPIWrapper returns formatted string, so we can't extract individual links
    # But we can indicate that search was performed
    references = None
    
    return answer, references

@router.post("/chat/text")
async def chat_text(
    query: str = Form(...),
    search_online: str = Form("false"),
    conversation_id: str | None = Form(None),
    current_user: dict = Depends(require_user),
):
    start_time = time.time()
    user_id = current_user["id"]
    
    conversation_id = ensure_conversation(conversation_id, user_id)
    
    add_message(conversation_id, "user", query)
    
    llm = AzureChatOpenAI(
        azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        openai_api_key=settings.AZURE_OPENAI_API_KEY,
        openai_api_version=settings.AZURE_OPENAI_API_VERSION,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        temperature=0.7
    )
    
    uploaded_docs = []
    if conversation_id:
        uploaded_docs = get_uploaded_documents(conversation_id)
    
    chat_history = get_chat_history(conversation_id, include_ids=False)
    
    route = await detect_route(query, conversation_id, llm)
    
    # Convert search_online string to boolean
    search_online_bool = search_online.lower() in ("true", "1", "yes", "on")
    
    # Override route to SerpAPI if user explicitly requested web search
    if search_online_bool:
        route = "serpapi"
        print(f"🔍 User requested web search, routing to SerpAPI")
    
    print(f"🔍 Initial route detected: {route}, uploaded_docs: {len(uploaded_docs)}, search_online: {search_online_bool}")
    
    answer = None
    references = None
    
    if route == "doc_meta":
        print("🔍 Handling document metadata query...")
        answer, references = await handle_doc_meta_query(query, conversation_id, uploaded_docs)
    
    if route == "sql" and not answer:
        print("🔍 Trying SQL agent...")
        answer, references = await handle_sql_query(query, conversation_id, user_id)
        if not answer:
            print("⚠️ SQL agent returned no answer, falling back to RAG")
            route = "rag"
    
    if route == "rag" and not answer:
        print("🔍 Trying RAG...")
        answer, references = await handle_rag_query(query, conversation_id, llm, chat_history)
        
        # Check if RAG answer indicates no information in documents
        rag_has_no_info = False
        if answer:
            answer_lower = answer.lower()
            no_info_phrases = [
                "does not contain",
                "no information",
                "not contain enough information",
                "doesn't contain",
                "no details",
                "not found in the document"
            ]
            rag_has_no_info = any(phrase in answer_lower for phrase in no_info_phrases)
        
        if not answer or rag_has_no_info:
            if rag_has_no_info:
                print(f"⚠️ RAG returned answer but indicates no information in documents")
            else:
                print(f"⚠️ RAG returned no answer, uploaded_docs: {len(uploaded_docs)}")
            
            # If RAG fails, just fall back to LLM (no automatic SerpAPI)
            if uploaded_docs:
                print("🔍 RAG failed but documents exist, trying with simplified query...")
                simplified_query = " ".join(query.split()[:10])  # First 10 words
                answer, references = await handle_rag_query(simplified_query, conversation_id, llm, chat_history)

                if answer:
                    print("✅ RAG succeeded with simplified query")
                elif not answer:
                    print("⚠️ RAG still failed with simplified query, checking document indexing...")
                    from app.services.weaviate_service import get_client
                    from weaviate.classes.query import Filter
                    client = get_client()
                    if client and client.collections.exists("DocumentChunk"):
                        doc_records = get_uploaded_documents(conversation_id)
                        doc_ids = [doc["id"] for doc in doc_records]
                        if doc_ids:
                            collection = client.collections.get("DocumentChunk")
                            try:
                                test_res = collection.query.fetch_objects(
                                    limit=1,
                                    filters=Filter.by_property("doc_id").contains_any(doc_ids[:1])
                                )
                                if not test_res.objects:
                                    print("⚠️ Documents are not indexed in Weaviate!")
                                    answer = f"I found {len(uploaded_docs)} uploaded document(s), but they appear to not be properly indexed yet. Please try again in a moment, or re-upload the document."
                                else:
                                    print(f"✅ Found {len(test_res.objects)} indexed chunks, but RAG still failed")
                                    route = "llm"
                            except Exception as check_error:
                                print(f"⚠️ Error checking document index: {check_error}")
                                route = "llm"
                    else:
                        print("⚠️ Weaviate client not available")
                        route = "llm"
            else:
                print("🔍 RAG failed, routing to LLM")
                route = "llm"
    
    if route == "serpapi" and not answer:
        print("🔍 Trying SerpAPI (user requested web search)...")
        answer, references = await handle_serpapi_query(query, llm, chat_history)
        if not answer:
            print("⚠️ SerpAPI returned no answer, falling back to LLM")
            route = "llm"
    
    if route == "llm" and not answer:
        print("🔍 Trying LLM...")
        try:
            system_prompt = "You are a helpful assistant. Answer the user's question to the best of your ability. You have access to the conversation history. Respond in plain text without any markdown formatting, bold text, or special characters."
            
            # Build chat history messages for context
            history_messages = []
            if chat_history:
                for msg in chat_history[-10:]:
                    if isinstance(msg, dict):
                        if msg.get("user"):
                            history_messages.append(("human", msg["user"]))
                        if msg.get("assistant"):
                            history_messages.append(("assistant", msg["assistant"]))
                    elif isinstance(msg, dict) and "role" in msg:
                        if msg.get("role") == "user":
                            history_messages.append(("human", msg.get("content", "")))
                        elif msg.get("role") == "assistant":
                            history_messages.append(("assistant", msg.get("content", "")))
            
            # Use ChatPromptTemplate with Runnable pattern
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                *history_messages,
                ("human", "{query}")
            ])
            
            # Create Runnable chain: prompt | llm | extract content | clean markdown
            extract_content = RunnableLambda(
                lambda x: x.content if hasattr(x, "content") else str(x)
            )
            clean_content = RunnableLambda(lambda x: clean_markdown(x) if x else None)
            
            chain = prompt_template | llm | extract_content | clean_content
            
            answer = await chain.ainvoke({"query": query})
            
            if not answer or answer.strip() == "":
                print("⚠️ LLM returned empty answer")
        except Exception as e:
            print(f"⚠️ Error in LLM handler: {e}")
            import traceback
            traceback.print_exc()
            answer = None
    
    if not answer:
        answer = "I apologize, but I couldn't generate a response. Please try rephrasing your question."
    
    response_time_ms = int((time.time() - start_time) * 1000)
    
    references_json = json.dumps(references) if references else None
    message_id = add_message(
        conversation_id,
        "assistant",
        answer,
        response_time_ms=response_time_ms,
        references=references
    )
    
    try:
        mlflow.log_metric("response_time_ms", response_time_ms)
        mlflow.log_param("route", route)
        mlflow.log_param("has_references", bool(references))
    except:
        pass
    
    final_chat_history = get_chat_history(conversation_id, include_ids=True)
    
    return {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "chat_history": final_chat_history,
        "answer": answer,
        "references": references
    }
