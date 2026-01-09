import { useState, useEffect, useRef } from "react"
import axios from "axios"
import "tailwindcss/tailwind.css"

// Get API URL from environment variable, default to localhost:8001 for development
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001'

function App() {
  const [query, setQuery] = useState("")
  const [chatHistory, setChatHistory] = useState([])
  const [uploadedDocs, setUploadedDocs] = useState([]) // Track multiple docs
  const [isLoading, setIsLoading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState("")
  const [showDocs, setShowDocs] = useState(false) // For viewing documents
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const [conversationId, setConversationId] = useState("")
  const [token, setToken] = useState(localStorage.getItem("auth_token") || "")
  const [authMode, setAuthMode] = useState("login") // 'login' | 'register'
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [me, setMe] = useState(null)
  const [feedbackModal, setFeedbackModal] = useState({ open: false, messageId: null, feedbackType: null })
  const [detailedFeedback, setDetailedFeedback] = useState("")
  const [messageFeedbacks, setMessageFeedbacks] = useState({}) // messageId -> feedback
  const [conversations, setConversations] = useState([]) // List of all conversations
  const [sidebarOpen, setSidebarOpen] = useState(true) // Sidebar visibility
  const [searchOnline, setSearchOnline] = useState(false) // Web search toggle

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [chatHistory])

  // Auto-focus textarea when component mounts
  useEffect(() => {
    if (token && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [token])

  // Load conversations list
  const loadConversations = async () => {
    if (!token || !me?.id) return
    try {
      const res = await axios.get(`${API_URL}/conversations`)
      setConversations(res.data.conversations || [])
    } catch (e) {
      console.error("Failed to load conversations:", e)
    }
  }

  // Load a specific conversation
  const loadConversation = async (convId) => {
    if (!token || !convId) return
    try {
      const [convRes, docsRes] = await Promise.all([
        axios.get(`${API_URL}/conversations/${convId}`),
        axios.get(`${API_URL}/documents`, { 
          params: { conversation_id: convId } 
        })
      ])
      
      setConversationId(convId)
      const history = convRes.data.chat_history || []
      setChatHistory(history)
      
      // Load feedback for all messages
      const feedbackPromises = history
        .filter(msg => msg.message_id)
        .map(msg => 
          axios.get(`${API_URL}/feedback/${msg.message_id}`)
            .then(res => ({ messageId: msg.message_id, feedback: res.data.feedback }))
            .catch(() => null)
        )
      const feedbackResults = await Promise.all(feedbackPromises)
      const feedbacksMap = {}
      feedbackResults.forEach(result => {
        if (result && result.feedback) {
          feedbacksMap[result.messageId] = result.feedback
        }
      })
      setMessageFeedbacks(feedbacksMap)
      
      setUploadedDocs(docsRes.data.documents || [])
      
      // Reload conversations list to update titles
      loadConversations()
      } catch (e) {
        console.error("Failed to load conversation:", e)
      }
    }
    
  // Initialize conversations list
  useEffect(() => {
    if (me?.id) {
      loadConversations()
    }
  }, [token, me?.id])

  // Load current conversation on mount
  useEffect(() => {
    const loadCurrent = async () => {
      if (!token || !me?.id) return
      
      try {
        const currentConvRes = await axios.get(`${API_URL}/conversations/current`)
        const conversationId = currentConvRes.data.conversation_id
        
        await loadConversation(conversationId)
      } catch (e) {
        console.error("Failed to load current conversation:", e)
      }
    }
    
    if (me?.id) {
      loadCurrent()
    }
  }, [token, me?.id])

  // Keep axios Authorization header in sync and setup 401 interceptor
  useEffect(() => {
    if (token) {
      axios.defaults.headers.common["Authorization"] = `Bearer ${token}`
      localStorage.setItem("auth_token", token)
    } else {
      delete axios.defaults.headers.common["Authorization"]
      localStorage.removeItem("auth_token")
    }
    
    const interceptor = axios.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) {
          localStorage.removeItem("auth_token")
          setToken("")
          setMe(null)
        }
        return Promise.reject(error)
      }
    )
    
    return () => {
      axios.interceptors.response.eject(interceptor)
    }
  }, [token])

  useEffect(() => {
    const fetchMe = async () => {
      if (!token) { 
        setMe(null)
        return 
      }
      try {
        const res = await axios.get(`${API_URL}/me`, {
          headers: { Authorization: `Bearer ${token}` }
        })
        setMe(res.data)
      } catch (err) {
        if (err.response?.status === 401) {
          setToken("")
          localStorage.removeItem("auth_token")
          setMe(null)
        } else {
          setMe(null)
        }
      }
    }
    fetchMe()
  }, [token])

  const handleLogin = async (e) => {
    e?.preventDefault()
    if (!username || !password) return
    try {
      const form = new FormData()
      form.append("username", username)
      form.append("password", password)
      const res = await axios.post(`${API_URL}/auth/login`, form)
      setToken(res.data.token)
      setUploadStatus("Logged in")
      setTimeout(() => setUploadStatus(""), 2000)
    } catch (err) {
      setUploadStatus("Login failed")
      setTimeout(() => setUploadStatus(""), 3000)
    }
  }

  const handleLogout = async () => {
    try {
      await axios.post(`${API_URL}/auth/logout`)
    } catch (_) {}
    setToken("")
    setUsername("")
    setPassword("")
  }

  const handleRegisterUser = async (e) => {
    e?.preventDefault()
    if (!username || !password) return
    try {
      const form = new FormData()
      form.append("username", username)
      form.append("password", password)
      await axios.post(`${API_URL}/auth/register`, form)
      setUploadStatus("User registered. You can now login.")
      setTimeout(() => setUploadStatus(""), 3000)
      setAuthMode("login")
    } catch (err) {
      setUploadStatus("Registration failed. Username may already exist.")
      setTimeout(() => setUploadStatus(""), 4000)
    }
  }


  const handleSend = async () => {
    if (!query.trim() || isLoading) return

    const userMessage = query.trim()
    setQuery("") // Clear input immediately for better UX
    
    // Add user message to chat immediately
    const newUserMessage = { user: userMessage, assistant: "" }
    setChatHistory(prev => [...prev, newUserMessage])

    setIsLoading(true)
    try {
      const formData = new FormData()
      formData.append("query", userMessage)
      formData.append("search_online", searchOnline ? "true" : "false")
      // Always pass the current conversation_id so messages are saved to the same conversation
      if (conversationId) {
        formData.append("conversation_id", conversationId)
      }

      const res = await axios.post(`${API_URL}/chat/text`, formData)
      
      // Update chat history with the complete response (includes message_ids and references)
      setChatHistory(res.data.chat_history)
      
      // Load feedback for the new message if it exists
      if (res.data.message_id) {
        try {
          const feedbackRes = await axios.get(`${API_URL}/feedback/${res.data.message_id}`)
          if (feedbackRes.data.feedback) {
            setMessageFeedbacks(prev => ({
              ...prev,
              [res.data.message_id]: feedbackRes.data.feedback
            }))
          }
        } catch (err) {
          // Ignore if no feedback exists
        }
      }
      
      // Update conversation_id if we got a new one (for new chats) or keep the existing one
      if (res.data.conversation_id) {
        if (res.data.conversation_id !== conversationId) {
        setConversationId(res.data.conversation_id)
        }
        // Reload conversations to update the title
        loadConversations()
      } else if (conversationId) {
        // If we already have a conversation_id, make sure it's still set
        // This ensures subsequent messages go to the same conversation
        setConversationId(conversationId)
      }
    } catch (err) {
      console.error(err)
      if (err.response?.status === 401) {
        setToken("")
        localStorage.removeItem("auth_token")
        setMe(null)
        setUploadStatus("Please login first to continue")
        setTimeout(() => setUploadStatus(""), 5000)
      } else {
        setUploadStatus("Error sending message")
        setTimeout(() => setUploadStatus(""), 3000)
      }
      
      // Remove the user message if there was an error
      setChatHistory(prev => prev.slice(0, -1))
    } finally {
      setIsLoading(false)
      // Focus the textarea for continuous conversation
      setTimeout(() => {
        textareaRef.current?.focus()
      }, 100)
    }
  }

  const handleUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return

    const allowedTypes = [
      "application/pdf",
      "text/plain",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "text/csv",
      "application/vnd.ms-excel",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]
    if (!allowedTypes.includes(file.type)) {
      setUploadStatus("Please upload a PDF, DOCX, TXT, CSV, XLS, or XLSX file")
      setTimeout(() => setUploadStatus(""), 3000)
      return
    }

    const formData = new FormData()
    formData.append("file", file)
    // Always pass the current conversation_id so documents are associated with the current conversation
    if (conversationId) {
      formData.append("conversation_id", conversationId)
    }

    setUploadStatus("Uploading document...")
    try {
      const res = await axios.post(`${API_URL}/upload_document`, formData)
      setUploadStatus(`Document uploaded successfully: ${file.name}`)
      setUploadedDocs((prev) => [...prev, { id: res.data.document_id, name: file.name }]) // store filename too
      
      // Update conversation_id if we got one from the backend (ensures all messages go to same conversation)
      if (res.data.conversation_id) {
        setConversationId(res.data.conversation_id)
      }
      
      setTimeout(() => setUploadStatus(""), 3000)
    } catch (err) {
      console.error(err)
      setUploadStatus("Upload failed. Please try again.")
      setTimeout(() => setUploadStatus(""), 3000)
    }
  }

  const handleRemove = async () => {
    if (uploadedDocs.length === 0) {
      setUploadStatus("No document to remove")
      setTimeout(() => setUploadStatus(""), 3000)
      return
    }

    // Remove last uploaded document
    const docToRemove = uploadedDocs[uploadedDocs.length - 1]

    try {
      const formData = new FormData()
      formData.append("document_id", docToRemove.id)

      await axios.post(`${API_URL}/remove_document`, formData)
      setUploadStatus("Document removed successfully")
      setUploadedDocs((prev) => prev.filter((doc) => doc.id !== docToRemove.id))
      setTimeout(() => setUploadStatus(""), 3000)
    } catch (err) {
      console.error(err)
      setUploadStatus("Failed to remove document")
      setTimeout(() => setUploadStatus(""), 3000)
    }
  }

  const handleRemoveSpecific = async (docId) => {
    try {
      const formData = new FormData()
      formData.append("document_id", docId)
      await axios.post(`${API_URL}/remove_document`, formData)
      setUploadedDocs((prev) => prev.filter((doc) => doc.id !== docId))
    } catch (err) {
      console.error(err)
      setUploadStatus("Failed to remove document")
      setTimeout(() => setUploadStatus(""), 3000)
    }
  }

  const handleClearHistory = async () => {
    if (!conversationId) return
    try {
      const formData = new FormData()
      formData.append("conversation_id", conversationId)
      await axios.post(`${API_URL}/clear_history`, formData)
      setChatHistory([])
      setMessageFeedbacks({})
      loadConversations() // Reload to update title
    } catch (err) {
      console.error(err)
      setUploadStatus("Failed to clear history")
      setTimeout(() => setUploadStatus(""), 3000)
    }
  }

  const handleNewChat = async () => {
    // Clear current conversation state - a new conversation will be created when first message is sent
    setConversationId(null) // Clear conversation ID so backend creates a new one
    setChatHistory([])
    setMessageFeedbacks({})
    setUploadedDocs([])
    // Reload conversations list (new conversation will appear after first message)
    loadConversations()
  }

  const handleSwitchConversation = async (convId) => {
    await loadConversation(convId)
  }

  const handleDeleteConversation = async (convId, e) => {
    e.stopPropagation() // Prevent triggering the conversation switch
    
    if (!window.confirm("Are you sure you want to delete this conversation? This action cannot be undone.")) {
      return
    }

    try {
      await axios.delete(`${API_URL}/conversations/${convId}`)
      
      // If we deleted the current conversation, clear it and start fresh
      if (convId === conversationId) {
        setConversationId(null)
        setChatHistory([])
        setMessageFeedbacks({})
        setUploadedDocs([])
      }
      
      // Reload conversations list
      loadConversations()
      setUploadStatus("Conversation deleted successfully")
      setTimeout(() => setUploadStatus(""), 3000)
    } catch (err) {
      console.error("Failed to delete conversation:", err)
      setUploadStatus("Failed to delete conversation")
      setTimeout(() => setUploadStatus(""), 3000)
    }
  }

  const formatDate = (dateString) => {
    if (!dateString) return ""
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now - date
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return "Just now"
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
  }

  const handleFeedback = async (messageId, feedbackType) => {
    try {
      const formData = new FormData()
      formData.append("message_id", messageId)
      formData.append("feedback_type", feedbackType)
      
      if (feedbackModal.open && feedbackModal.feedbackType === feedbackType) {
        // Open modal for detailed feedback
        setFeedbackModal({ open: true, messageId, feedbackType })
      } else {
        // Save feedback immediately
        await axios.post(`${API_URL}/feedback`, formData)
        setMessageFeedbacks(prev => ({
          ...prev,
          [messageId]: { feedback_type: feedbackType, detailed_feedback: null }
        }))
        setUploadStatus("Feedback saved!")
        setTimeout(() => setUploadStatus(""), 2000)
      }
    } catch (err) {
      console.error(err)
      setUploadStatus("Failed to save feedback")
      setTimeout(() => setUploadStatus(""), 3000)
    }
  }

  const handleOpenFeedbackModal = (messageId, feedbackType) => {
    setFeedbackModal({ open: true, messageId, feedbackType })
    setDetailedFeedback("")
  }

  const handleSubmitDetailedFeedback = async () => {
    if (!feedbackModal.messageId) return
    try {
      const formData = new FormData()
      formData.append("message_id", feedbackModal.messageId)
      formData.append("feedback_type", feedbackModal.feedbackType)
      if (detailedFeedback.trim()) {
        formData.append("detailed_feedback", detailedFeedback.trim())
      }
      
      await axios.post(`${API_URL}/feedback`, formData)
      setMessageFeedbacks(prev => ({
        ...prev,
        [feedbackModal.messageId]: { 
          feedback_type: feedbackModal.feedbackType, 
          detailed_feedback: detailedFeedback.trim() || null 
        }
      }))
      setFeedbackModal({ open: false, messageId: null, feedbackType: null })
      setDetailedFeedback("")
      setUploadStatus("Feedback saved!")
      setTimeout(() => setUploadStatus(""), 2000)
    } catch (err) {
      console.error(err)
      setUploadStatus("Failed to save feedback")
      setTimeout(() => setUploadStatus(""), 3000)
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // If not authenticated, show auth screen
  if (!token) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center p-6">
        <div className="w-full max-w-lg">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="w-20 h-20 bg-gradient-to-br from-blue-600 to-purple-600 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg">
              <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">AI Document Assistant</h1>
            <p className="text-gray-600">Powered by RAG + OCR Technology</p>
          </div>

          {/* Auth Card */}
          <div className="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden">
            {/* Tab Navigation */}
            <div className="flex border-b border-gray-100">
            <button
                className={`flex-1 py-4 px-6 text-sm font-medium transition-all duration-200 ${
                  authMode === "login" 
                    ? "bg-blue-50 text-blue-600 border-b-2 border-blue-600" 
                    : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
                }`}
              onClick={() => setAuthMode("login")}
            >
                <div className="flex items-center justify-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
                  </svg>
                  User Login
                </div>
            </button>
            <button
                className={`flex-1 py-4 px-6 text-sm font-medium transition-all duration-200 ${
                  authMode === "register" 
                    ? "bg-blue-50 text-blue-600 border-b-2 border-blue-600" 
                    : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
                }`}
              onClick={() => setAuthMode("register")}
            >
                <div className="flex items-center justify-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
                  </svg>
                  Register User
                </div>
            </button>
          </div>

            {/* Form Content */}
            <div className="p-8">
              {authMode === "login" && (
                <form onSubmit={handleLogin} className="space-y-6">
              <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-2">Username</label>
                    <input 
                      value={username} 
                      onChange={(e) => setUsername(e.target.value)} 
                      className="w-full border border-gray-300 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200" 
                      placeholder="Enter your username"
                    />
              </div>
              <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-2">Password</label>
                    <input 
                      type="password" 
                      value={password} 
                      onChange={(e) => setPassword(e.target.value)} 
                      className="w-full border border-gray-300 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200" 
                      placeholder="Enter your password"
                    />
              </div>
                  <button 
                    type="submit" 
                    className="w-full py-3 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 text-white font-semibold rounded-xl transition-all duration-200 transform hover:scale-105 shadow-lg"
                  >
                    Sign In
                  </button>
            </form>
              )}

              {authMode === "register" && (
                <form onSubmit={handleRegisterUser} className="space-y-6">
              <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-2">New Username</label>
                    <input 
                      value={username} 
                      onChange={(e) => setUsername(e.target.value)} 
                      className="w-full border border-gray-300 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200" 
                      placeholder="Choose a username"
                    />
              </div>
              <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-2">New Password</label>
                    <input 
                      type="password" 
                      value={password} 
                      onChange={(e) => setPassword(e.target.value)} 
                      className="w-full border border-gray-300 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200" 
                      placeholder="Choose a password"
                    />
              </div>
                  <button 
                    type="submit" 
                    className="w-full py-3 bg-gradient-to-r from-green-600 to-green-700 hover:from-green-700 hover:to-green-800 text-white font-semibold rounded-xl transition-all duration-200 transform hover:scale-105 shadow-lg"
                  >
                    Create Account
                  </button>
            </form>
              )}


          {uploadStatus && (
                <div className={`mt-6 p-4 rounded-xl text-sm font-medium text-center ${
                  uploadStatus.includes("Error") || uploadStatus.includes("failed")
                    ? "bg-red-50 text-red-700 border border-red-200"
                    : "bg-green-50 text-green-700 border border-green-200"
                }`}>
                  <div className="flex items-center justify-center gap-2">
                    {uploadStatus.includes("Error") || uploadStatus.includes("failed") ? (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    ) : (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                    {uploadStatus}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Features */}
          <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="text-center p-4 bg-white rounded-xl shadow-sm border border-gray-100">
              <div className="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
              <h3 className="font-semibold text-gray-900 mb-1">AI Chat</h3>
              <p className="text-sm text-gray-600">Ask questions about your documents</p>
            </div>
            <div className="text-center p-4 bg-white rounded-xl shadow-sm border border-gray-100">
              <div className="w-12 h-12 bg-green-100 rounded-xl flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
              </div>
              <h3 className="font-semibold text-gray-900 mb-1">Document Upload</h3>
              <p className="text-sm text-gray-600">Upload PDFs, Word docs, and more</p>
            </div>
            <div className="text-center p-4 bg-white rounded-xl shadow-sm border border-gray-100">
              <div className="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </div>
              <h3 className="font-semibold text-gray-900 mb-1">Admin Panel</h3>
              <p className="text-sm text-gray-600">Manage documents and system</p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-slate-50">
      {/* Sidebar */}
      <div className={`${sidebarOpen ? 'w-64' : 'w-0'} transition-all duration-300 bg-white border-r border-gray-200 flex flex-col overflow-hidden ${sidebarOpen ? '' : 'hidden'}`}>
        <div className="p-4 border-b border-gray-200">
          <button
            onClick={handleNewChat}
            className="w-full flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-xl hover:from-blue-700 hover:to-purple-700 transition-all duration-200 shadow-lg font-medium"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            New Chat
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto">
          <div className="p-2">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide px-3 py-2">Recent Chats</div>
            {conversations.length === 0 ? (
              <div className="px-3 py-4 text-sm text-gray-500 text-center">
                No conversations yet. Start a new chat!
              </div>
            ) : (
              conversations.map((conv) => (
                <div
                  key={conv.id}
                  className={`group w-full px-3 py-2.5 rounded-lg mb-1 transition-all duration-200 flex items-center gap-2 ${
                    conv.id === conversationId
                      ? 'bg-blue-50 text-blue-700 border border-blue-200'
                      : 'text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  <button
                    onClick={() => handleSwitchConversation(conv.id)}
                    className="flex-1 text-left flex items-start gap-2 min-w-0"
                  >
                    <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{conv.title}</div>
                      <div className="text-xs text-gray-500 mt-0.5">{formatDate(conv.created_at)}</div>
                    </div>
                  </button>
                  <button
                    onClick={(e) => handleDeleteConversation(conv.id, e)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 p-1.5 hover:bg-red-100 rounded text-red-600 hover:text-red-700"
                    title="Delete conversation"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
      {/* Header */}
      <header className="bg-gradient-to-r from-blue-600 via-purple-600 to-indigo-600 text-white shadow-xl border-b border-blue-700">
          <div className="px-6 py-4">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
                <button
                  onClick={() => setSidebarOpen(!sidebarOpen)}
                  className="p-2 hover:bg-white/20 rounded-lg transition-all"
                  title={sidebarOpen ? "Close sidebar" : "Open sidebar"}
                >
                  {sidebarOpen ? (
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  ) : (
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                  )}
                </button>
              <div className="w-12 h-12 bg-white/20 rounded-2xl flex items-center justify-center backdrop-blur-sm shadow-lg">
                <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                  />
                </svg>
              </div>
              <div>
                <h1 className="text-2xl font-bold">AI Document Assistant</h1>
                <p className="text-blue-100 text-sm">Powered by RAG + OCR Technology</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              {uploadedDocs.length > 0 && (
                <div className="flex items-center gap-2 bg-white/20 px-4 py-2 rounded-xl backdrop-blur-sm shadow-lg">
                  <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></div>
                  <span className="text-sm font-medium">
                    {uploadedDocs.length} document{uploadedDocs.length > 1 ? "s" : ""} loaded
                  </span>
                </div>
              )}
              <div className="flex items-center gap-2">
                <button 
                  onClick={handleLogout} 
                  className="px-4 py-2 bg-white/20 hover:bg-white/30 rounded-xl text-sm font-medium transition-all duration-200 backdrop-blur-sm"
                >
                  Logout
                </button>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Chat Area */}
      <main className="flex-1 overflow-y-auto bg-gradient-to-br from-blue-50 via-white to-purple-50">
        <div className="max-w-5xl mx-auto px-6 py-8">
          {chatHistory.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-20">
              <div className="w-24 h-24 bg-gradient-to-br from-blue-100 to-purple-100 rounded-3xl flex items-center justify-center mb-8 shadow-lg">
                <svg className="w-12 h-12 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                  />
                </svg>
              </div>
              <h2 className="text-3xl font-bold text-gray-900 mb-4">Welcome to AI Document Assistant</h2>
              <p className="text-gray-600 max-w-lg leading-relaxed text-lg mb-8">
                Upload documents and ask questions about them, or just start chatting with the AI assistant powered by RAG + OCR technology!
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-2xl">
                <div className="p-4 bg-white rounded-xl shadow-sm border border-gray-100">
                  <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center mx-auto mb-3">
                    <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <h3 className="font-semibold text-gray-900 mb-1">Upload Documents</h3>
                  <p className="text-sm text-gray-600">PDF, Word, Excel, Images</p>
                </div>
                <div className="p-4 bg-white rounded-xl shadow-sm border border-gray-100">
                  <div className="w-10 h-10 bg-green-100 rounded-xl flex items-center justify-center mx-auto mb-3">
                    <svg className="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                    </svg>
                  </div>
                  <h3 className="font-semibold text-gray-900 mb-1">AI Processing</h3>
                  <p className="text-sm text-gray-600">OCR + Embeddings</p>
                </div>
                <div className="p-4 bg-white rounded-xl shadow-sm border border-gray-100">
                  <div className="w-10 h-10 bg-purple-100 rounded-xl flex items-center justify-center mx-auto mb-3">
                    <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                  </div>
                  <h3 className="font-semibold text-gray-900 mb-1">Smart Q&A</h3>
                  <p className="text-sm text-gray-600">Ask questions</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-8">
              {chatHistory.map((msg, idx) => (
                <div key={idx} className="space-y-6">
                  {/* User Message */}
                  {msg.user && (
                    <div className="flex justify-end animate-fadeIn">
                      <div className="flex items-start gap-4 max-w-3xl">
                        <div className="bg-gradient-to-r from-blue-600 to-purple-600 text-white p-5 rounded-2xl rounded-br-lg shadow-xl">
                          <p className="text-sm leading-relaxed whitespace-pre-wrap font-medium">{msg.user}</p>
                      </div>
                        <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-500 rounded-full flex items-center justify-center flex-shrink-0 shadow-lg">
                          <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 13l-3-3m0 0l-3 3m3-3v12"
                          />
                        </svg>
                      </div>
                    </div>
                  </div>
                  )}

                  {/* Assistant Message */}
                  {msg.assistant && (
                    <div className="flex justify-start animate-fadeIn">
                      <div className="flex items-start gap-4 max-w-3xl">
                        <div className="w-10 h-10 bg-gradient-to-br from-emerald-500 to-teal-500 rounded-full flex items-center justify-center flex-shrink-0 shadow-lg">
                          <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                          />
                        </svg>
                      </div>
                        <div className="bg-white border border-gray-200 p-5 rounded-2xl rounded-bl-lg shadow-lg flex-1">
                          <p className="text-sm leading-relaxed text-gray-700 whitespace-pre-wrap mb-3">{msg.assistant}</p>
                          
                          {/* RAG References */}
                          {msg.references && msg.references.length > 0 && (
                            <div className="mt-4 pt-4 border-t border-gray-100">
                              <div className="flex items-center gap-2 mb-2">
                                <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                </svg>
                                <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Sources</span>
                              </div>
                              <div className="space-y-2 max-h-40 overflow-y-auto">
                                {msg.references.slice(0, 3).map((ref, refIdx) => (
                                  <div key={refIdx} className="text-xs text-gray-600 bg-gray-50 p-2 rounded border border-gray-200">
                                    <div className="flex items-start gap-2">
                                      <span className="text-gray-400 font-mono text-[10px] mt-0.5 flex-shrink-0">{refIdx + 1}</span>
                                      <p className="line-clamp-2">{ref.substring(0, 200)}{ref.length > 200 ? '...' : ''}</p>
                                    </div>
                                  </div>
                                ))}
                                {msg.references.length > 3 && (
                                  <div className="text-xs text-gray-500 italic text-center">
                                    +{msg.references.length - 3} more source{msg.references.length - 3 > 1 ? 's' : ''}
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                          
                          {/* Feedback Buttons - Icons Only */}
                          {msg.message_id && (
                            <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-100">
                              <button
                                onClick={() => handleOpenFeedbackModal(msg.message_id, "thumbs_up")}
                                className={`p-2 rounded-lg transition-all ${
                                  messageFeedbacks[msg.message_id]?.feedback_type === "thumbs_up"
                                    ? "bg-green-100 text-green-700"
                                    : "bg-gray-100 text-gray-600 hover:bg-green-50 hover:text-green-600"
                                }`}
                                title="Helpful"
                              >
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5" />
                                </svg>
                              </button>
                              <button
                                onClick={() => handleOpenFeedbackModal(msg.message_id, "thumbs_down")}
                                className={`p-2 rounded-lg transition-all ${
                                  messageFeedbacks[msg.message_id]?.feedback_type === "thumbs_down"
                                    ? "bg-red-100 text-red-700"
                                    : "bg-gray-100 text-gray-600 hover:bg-red-50 hover:text-red-600"
                                }`}
                                title="Not Helpful"
                              >
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14H5.236a2 2 0 01-1.789-2.894l3.5-7A2 2 0 018.736 3h4.018a2 2 0 01.485.06l3.76.94m-7 10v5a2 2 0 002 2h.096c.5 0 .905-.405.905-.904 0-.715.211-1.413.608-2.008L17 13V4m-7 10h2m5-10h2a2 2 0 012 2v6a2 2 0 01-2 2h-2.5" />
                                </svg>
                              </button>
                            </div>
                          )}
                      </div>
                    </div>
                  </div>
                  )}
                </div>
              ))}

              {isLoading && (
                <div className="flex justify-start">
                  <div className="flex items-start gap-4 max-w-3xl">
                    <div className="w-10 h-10 bg-gradient-to-br from-emerald-500 to-teal-500 rounded-full flex items-center justify-center flex-shrink-0 shadow-lg">
                      <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                        />
                      </svg>
                    </div>
                    <div className="bg-white border border-gray-200 p-5 rounded-2xl rounded-bl-lg shadow-lg">
                      <div className="flex items-center gap-3">
                      <div className="flex gap-1">
                          <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce"></div>
                        <div
                            className="w-2 h-2 bg-purple-500 rounded-full animate-bounce"
                          style={{ animationDelay: "0.1s" }}
                        ></div>
                        <div
                            className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce"
                          style={{ animationDelay: "0.2s" }}
                        ></div>
                        </div>
                        <span className="text-sm text-gray-600 font-medium">AI is processing your request...</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* Input Area */}
      <footer className="bg-white border-t border-gray-200 shadow-xl">
        <div className="max-w-5xl mx-auto p-6">
          {/* Status Message */}
          {uploadStatus && (
            <div
              className={`mb-4 p-3 rounded-lg text-sm font-medium text-center ${
                uploadStatus.includes("Error") || uploadStatus.includes("failed")
                  ? "bg-red-50 text-red-700 border border-red-200"
                  : "bg-green-50 text-green-700 border border-green-200"
              }`}
            >
              <div className="flex items-center justify-center gap-2">
                {uploadStatus.includes("Error") || uploadStatus.includes("failed") ? (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                )}
                {uploadStatus}
              </div>
            </div>
          )}

          {/* Input Wrapper */}
          <div className="flex items-end gap-4 mb-6">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyPress={handleKeyPress}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question or start a conversation..."
                className="w-full min-h-[70px] max-h-40 p-5 pr-24 border-2 border-gray-200 rounded-2xl bg-white text-gray-700 placeholder-gray-400 resize-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100 focus:outline-none transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed shadow-sm"
                disabled={isLoading}
                rows={1}
              />
              {/* Search Online Toggle Button */}
              <button
                onClick={() => setSearchOnline(!searchOnline)}
                className={`absolute right-16 bottom-4 p-2 rounded-lg transition-all duration-200 ${
                  searchOnline
                    ? "bg-green-500 text-white hover:bg-green-600 shadow-lg"
                    : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                }`}
                disabled={isLoading}
                title={searchOnline ? "Web search enabled - Click to disable" : "Enable web search"}
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
              </button>
              {/* File Upload Button */}
              <button
                onClick={() => document.getElementById("file-input").click()}
                className="absolute right-4 bottom-4 p-2 text-gray-400 hover:text-blue-600 transition-colors duration-200"
                disabled={isLoading}
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                  />
                </svg>
              </button>
            </div>
            <button
              onClick={handleSend}
              disabled={!query.trim() || isLoading}
              className="w-14 h-14 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white rounded-2xl flex items-center justify-center transition-all duration-200 transform hover:scale-105 disabled:transform-none shadow-lg"
            >
              {isLoading ? (
                <div className="w-6 h-6 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
              ) : (
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                  />
                </svg>
              )}
            </button>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-center gap-4 flex-wrap">
            <label className="flex items-center gap-3 px-6 py-3 bg-gradient-to-r from-blue-50 to-purple-50 hover:from-blue-100 hover:to-purple-100 text-gray-700 rounded-xl cursor-pointer transition-all duration-200 border border-blue-200 shadow-sm">
              <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                />
              </svg>
              <span className="text-sm font-semibold">Upload Document</span>
              <input
                id="file-input"
                type="file"
                onChange={handleUpload}
                accept=".pdf,.doc,.docx,.txt,.csv,.xls,.xlsx,.pptx,.png,.jpg,.jpeg,.tif,.tiff"
                className="hidden"
              />
            </label>

            {uploadedDocs.length > 0 && (
              <>
                <button
                  onClick={handleRemove}
                  className="flex items-center gap-3 px-6 py-3 bg-red-50 hover:bg-red-100 text-red-700 rounded-xl transition-all duration-200 border border-red-200 shadow-sm"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  <span className="text-sm font-semibold">Remove Document</span>
                </button>

                <button
                  onClick={() => setShowDocs(true)}
                  className="flex items-center gap-3 px-6 py-3 bg-blue-50 hover:bg-blue-100 text-blue-700 rounded-xl transition-all duration-200 border border-blue-200 shadow-sm"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="text-sm font-semibold">View Documents</span>
                </button>
              </>
            )}


            <button
              onClick={handleClearHistory}
              className="flex items-center gap-3 px-6 py-3 bg-gray-50 hover:bg-gray-100 text-gray-700 rounded-xl transition-all duration-200 border border-gray-200 shadow-sm"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              <span className="text-sm font-semibold">Clear Chat</span>
            </button>
          </div>
        </div>
      </footer>

      {/* Uploaded Documents Modal */}
      {showDocs && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl max-w-md w-full p-6 shadow-lg">
            <h2 className="text-lg font-bold mb-4">Uploaded Documents</h2>
            <ul className="space-y-2 max-h-60 overflow-y-auto">
              {uploadedDocs.map((doc, idx) => (
                <li key={idx} className="flex items-center justify-between border-b border-slate-200 py-2 text-sm text-slate-700">
                  <span>{doc.name} (ID: {doc.id})</span>
                  <button
                    onClick={() => handleRemoveSpecific(doc.id)}
                    className="px-2 py-1 text-red-600 hover:text-red-700 hover:bg-red-50 rounded"
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
            <div className="mt-4 text-right">
              <button
                onClick={() => setShowDocs(false)}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Feedback Modal */}
      {feedbackModal.open && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-gray-900">
                {feedbackModal.feedbackType === "thumbs_up" ? "👍 Helpful Feedback" : "👎 Not Helpful Feedback"}
              </h2>
                <button
                onClick={() => {
                  setFeedbackModal({ open: false, messageId: null, feedbackType: null })
                  setDetailedFeedback("")
                }}
                className="text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
            </div>
            <p className="text-sm text-gray-600 mb-4">
              {feedbackModal.feedbackType === "thumbs_up" 
                ? "What did you find helpful? (Optional)" 
                : "What could be improved? (Optional)"}
            </p>
            <textarea
              value={detailedFeedback}
              onChange={(e) => setDetailedFeedback(e.target.value)}
              placeholder="Share your thoughts..."
              className="w-full border border-gray-300 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
              rows={4}
            />
            <div className="flex gap-3 mt-6">
                  <button 
                onClick={handleSubmitDetailedFeedback}
                className="flex-1 px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 text-white font-semibold rounded-lg transition-all duration-200 shadow-lg"
                  >
                Submit Feedback
                  </button>
                  <button 
                onClick={() => {
                  setFeedbackModal({ open: false, messageId: null, feedbackType: null })
                  setDetailedFeedback("")
                }}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 font-semibold rounded-lg transition-all duration-200"
              >
                Cancel
                  </button>
                </div>
          </div>
        </div>
      )}
      </div>
    </div>
  )
}

export default App
