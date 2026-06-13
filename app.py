import streamlit as st
import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="AI Chat",
    page_icon="💬",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Main background */
    .stApp { background-color: #0f1117; }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #1a1d27;
        border-right: 1px solid #2d2f3e;
    }

    /* Chat message bubbles */
    .user-bubble {
        background: linear-gradient(135deg, #4f46e5, #7c3aed);
        color: white;
        padding: 12px 16px;
        border-radius: 18px 18px 4px 18px;
        margin: 8px 0 8px 15%;
        word-wrap: break-word;
        box-shadow: 0 2px 8px rgba(79,70,229,0.3);
    }
    .assistant-bubble {
        background: #1e2130;
        color: #e2e8f0;
        padding: 12px 16px;
        border-radius: 18px 18px 18px 4px;
        margin: 8px 15% 8px 0;
        word-wrap: break-word;
        border: 1px solid #2d2f3e;
    }
    .role-label {
        font-size: 11px;
        opacity: 0.6;
        margin-bottom: 4px;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }

    /* Thread buttons */
    div[data-testid="stButton"] > button {
        border-radius: 8px;
        transition: all 0.2s;
    }

    /* Hide default streamlit header */
    header { visibility: hidden; }

    /* Input area */
    .stTextInput > div > div > input {
        background-color: #1e2130;
        color: #e2e8f0;
        border: 1px solid #2d2f3e;
        border-radius: 12px;
    }
</style>
""", unsafe_allow_html=True)


# ── API Helpers ───────────────────────────────────────────────────────────────

def api_get(path):
    try:
        r = requests.get(f"{API_URL}{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to backend. Make sure FastAPI is running on port 8000.")
        return None
    except Exception as e:
        st.error(f"API error: {e}")
        return None

def api_post(path, data):
    try:
        r = requests.post(f"{API_URL}{path}", json=data, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to backend. Make sure FastAPI is running on port 8000.")
        return None
    except Exception as e:
        st.error(f"API error: {e}")
        return None

def api_patch(path, data):
    try:
        r = requests.patch(f"{API_URL}{path}", json=data, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None

def api_delete(path):
    try:
        r = requests.delete(f"{API_URL}{path}", timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        st.error(f"API error: {e}")
        return False


# ── Session State ─────────────────────────────────────────────────────────────

if "active_thread_id" not in st.session_state:
    st.session_state.active_thread_id = None
if "renaming_thread_id" not in st.session_state:
    st.session_state.renaming_thread_id = None


# ── Sidebar — Thread List ─────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 💬 AI Chat")
    st.markdown("---")

    if st.button("＋  New Thread", use_container_width=True, type="primary"):
        result = api_post("/threads", {"title": "New Thread"})
        if result:
            st.session_state.active_thread_id = result["id"]
            st.rerun()

    st.markdown("### Threads")

    threads = api_get("/threads") or []

    if not threads:
        st.caption("No threads yet. Create one above!")
    else:
        for thread in threads:
            tid = thread["id"]
            title = thread["title"]

            # Rename mode
            if st.session_state.renaming_thread_id == tid:
                new_name = st.text_input(
                    "Rename", value=title, key=f"rename_input_{tid}", label_visibility="collapsed"
                )
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✓", key=f"confirm_rename_{tid}", use_container_width=True):
                        api_patch(f"/threads/{tid}", {"title": new_name})
                        st.session_state.renaming_thread_id = None
                        st.rerun()
                with col2:
                    if st.button("✕", key=f"cancel_rename_{tid}", use_container_width=True):
                        st.session_state.renaming_thread_id = None
                        st.rerun()
            else:
                is_active = st.session_state.active_thread_id == tid
                btn_type = "primary" if is_active else "secondary"

                col1, col2, col3 = st.columns([6, 1, 1])
                with col1:
                    label = f"{'▶ ' if is_active else ''}{title[:28]}{'…' if len(title) > 28 else ''}"
                    if st.button(label, key=f"thread_{tid}", use_container_width=True, type=btn_type):
                        st.session_state.active_thread_id = tid
                        st.rerun()
                with col2:
                    if st.button("✏️", key=f"edit_{tid}", help="Rename"):
                        st.session_state.renaming_thread_id = tid
                        st.rerun()
                with col3:
                    if st.button("🗑️", key=f"del_{tid}", help="Delete"):
                        api_delete(f"/threads/{tid}")
                        if st.session_state.active_thread_id == tid:
                            st.session_state.active_thread_id = None
                        st.rerun()

    st.markdown("---")
    st.caption("🧠 Universal memory: AI remembers all past threads")


# ── Main Chat Area ────────────────────────────────────────────────────────────

if st.session_state.active_thread_id is None:
    # Welcome screen
    st.markdown("""
    <div style='text-align:center; margin-top: 20vh;'>
        <h1 style='font-size: 3rem;'>💬</h1>
        <h2 style='color: #e2e8f0;'>Welcome to AI Chat</h2>
        <p style='color: #64748b; font-size: 1.1rem;'>
            Create a new thread from the sidebar to start chatting.<br>
            The AI remembers context across all your threads.
        </p>
    </div>
    """, unsafe_allow_html=True)
else:
    active_id = st.session_state.active_thread_id

    # Find thread title
    thread_title = next(
        (t["title"] for t in threads if t["id"] == active_id), "Chat"
    )
    st.markdown(f"### 💬 {thread_title}")
    st.markdown("---")

    # Load messages
    messages = api_get(f"/threads/{active_id}/messages") or []

    # Render messages
    chat_container = st.container()
    with chat_container:
        if not messages:
            st.markdown(
                "<p style='color:#64748b; text-align:center; margin-top:40px;'>"
                "Send a message to start the conversation…</p>",
                unsafe_allow_html=True,
            )
        else:
            for msg in messages:
                if msg["role"] == "user":
                    st.markdown(
                        f'<div class="user-bubble">'
                        f'<div class="role-label">You</div>{msg["content"]}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    # Render assistant markdown properly
                    with st.container():
                        st.markdown(
                            f'<div class="assistant-bubble">'
                            f'<div class="role-label" style="color:#7c3aed;">✦ Assistant</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(msg["content"])

    st.markdown("---")

    # Input box
    with st.form(key="chat_form", clear_on_submit=True):
        col1, col2 = st.columns([9, 1])
        with col1:
            user_input = st.text_input(
                "Message",
                placeholder="Type your message…",
                label_visibility="collapsed",
            )
        with col2:
            submitted = st.form_submit_button("Send", use_container_width=True, type="primary")

    if submitted and user_input.strip():
        with st.spinner("Thinking…"):
            result = api_post("/chat", {
                "thread_id": active_id,
                "message": user_input.strip(),
            })
        if result:
            st.rerun()
