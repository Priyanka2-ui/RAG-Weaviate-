uploaded_docs = {}

def get_uploaded_docs_count():
    return len(uploaded_docs)

def add_document(doc_id, docs):
    uploaded_docs[doc_id] = docs

def remove_document(doc_id):
    if doc_id in uploaded_docs:
        del uploaded_docs[doc_id]
        return True
    return False

def get_document(doc_id):
    return uploaded_docs.get(doc_id)

def get_all_documents():
    return uploaded_docs

