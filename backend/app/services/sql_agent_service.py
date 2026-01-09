import sqlite3
import warnings
from langchain_openai import AzureChatOpenAI
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent
from app.config import settings

sql_agent = None
sql_db = None
sql_checkpointer = None
sql_checkpoint_conn = None

def init_sql_agent():
    global sql_agent, sql_db, sql_checkpointer, sql_checkpoint_conn
    
    try:
        sql_db = SQLDatabase.from_uri(f"sqlite:///{settings.DATA_DB_PATH}")
        
        llm = AzureChatOpenAI(
            azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            openai_api_key=settings.AZURE_OPENAI_API_KEY,
            openai_api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            temperature=0
        )
        
        toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)
        tools = toolkit.get_tools()
        
        checkpoint_db_path = settings.DATA_DB_PATH.replace('.db', '_checkpoint.db')
        sql_checkpoint_conn = sqlite3.connect(checkpoint_db_path, check_same_thread=False)
        sql_checkpointer = SqliteSaver(sql_checkpoint_conn)
        
        system_prompt = f"""You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct {sql_db.dialect} query to run,
then look at the results of the query and return the answer. Unless the user
specifies a specific number of examples they wish to obtain, always limit your
query to at most 5 results.

You can order the results by a relevant column to return the most interesting
examples in the database. Never query for all the columns from a specific table,
only ask for the relevant columns given the question.

You MUST double check your query before executing it. If you get an error while
executing a query, rewrite the query and try again.

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the
database. You can only SELECT data.

To start you should ALWAYS look at the tables in the database to see what you
can query. Do NOT skip this step.

Then you should query the schema of the most relevant tables.
"""
        
        sql_agent = create_react_agent(
            model=llm,
            tools=tools,
            prompt=system_prompt,
            checkpointer=sql_checkpointer
        )
        
        print("SQL Agent initialized with LangGraph successfully")
        return True
    except Exception as e:
        print(f"Failed to initialize SQL agent: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_sql_agent():
    return sql_agent

def is_sql_query(query: str) -> bool:
    sql_keywords = [
        "count", "sum", "average", "avg", "max", "min", "select", "from", "where",
        "group by", "order by", "having", "join", "table", "tables", "rows", "columns",
        "how many", "what is the total", "list all", "show me", "find all",
        "calculate", "aggregate", "statistics", "data", "dataset"
    ]
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in sql_keywords)

