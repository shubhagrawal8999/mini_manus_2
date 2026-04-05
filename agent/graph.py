"""
agent/graph.py — the LangGraph agent graph.

This is the brain of the system. Here's how it works:

1. User message comes in → loaded into state with conversation history
2. LLM (DeepSeek) reads message + history + available tools
3. LLM decides: respond directly OR call a tool
4. If tool called → execute it → feed result back to LLM
5. LLM generates final response
6. Error? → retry up to MAX_RETRIES, then send error message

Why LangGraph?
  LangGraph is the best production agent framework right now. It:
  - Gives you explicit control over the agent loop (unlike "magic" frameworks)
  - Has built-in checkpointing (resume from any step)
  - Handles tool calling reliably
  - Is maintained by the LangChain team with active development
"""
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent.prompts import SYSTEM_PROMPT
from agent.state import AgentState
from agent.tools.deep_search import deep_search, take_screenshot
from agent.tools.email_tool import read_emails, search_emails, send_email
from agent.tools.google_sheets import log_to_sheets
from agent.tools.linkedin import generate_linkedin_post, post_on_linkedin
from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# ── LLM setup ─────────────────────────────────────────────────────────────────

def _make_deepseek_llm(temperature: float = 0.7) -> ChatOpenAI:
    """DeepSeek uses OpenAI-compatible API. Just swap the base_url."""
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=temperature,
    )


def _make_openai_llm(temperature: float = 0.7) -> ChatOpenAI:
    """GPT-4o fallback for complex/hard questions."""
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=temperature,
    )


# ── Tool registry ──────────────────────────────────────────────────────────────

ALL_TOOLS = [
    deep_search,
    take_screenshot,
    read_emails,
    search_emails,
    send_email,
    post_on_linkedin,
    generate_linkedin_post,
    log_to_sheets,
]

# The ToolNode handles calling whichever tool the LLM picks
tool_node = ToolNode(ALL_TOOLS)


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def agent_node(state: AgentState) -> AgentState:
    """
    Core LLM node. Reads state, decides what to do next.
    Falls back to OpenAI if DeepSeek fails.
    """
    try:
        llm = _make_deepseek_llm()
        llm_with_tools = llm.bind_tools(ALL_TOOLS)

        # Build the message list: system prompt + history + current message
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state.messages

        response = await llm_with_tools.ainvoke(messages)
        logger.info("agent_responded", tool_calls=len(response.tool_calls or []))
        return AgentState(
            messages=[response],
            user_id=state.user_id,
            task=state.task,
            retry_count=state.retry_count,
        )

    except Exception as primary_error:
        logger.warning(
            "deepseek_failed_trying_openai",
            error=str(primary_error),
        )
        try:
            # Fallback to OpenAI
            llm = _make_openai_llm()
            llm_with_tools = llm.bind_tools(ALL_TOOLS)
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + state.messages
            response = await llm_with_tools.ainvoke(messages)
            return AgentState(
                messages=[response],
                user_id=state.user_id,
                task=state.task,
                retry_count=state.retry_count,
            )
        except Exception as fallback_error:
            logger.error("both_llms_failed", error=str(fallback_error))
            return AgentState(
                messages=state.messages,
                user_id=state.user_id,
                task=state.task,
                error=str(fallback_error),
                retry_count=state.retry_count + 1,
            )


async def error_handler_node(state: AgentState) -> AgentState:
    """
    Called when the agent hits an error. Decides whether to retry or give up.
    """
    from utils.error_handler import log_error_to_db

    logger.error(
        "agent_error",
        user_id=state.user_id,
        task=state.task,
        error=state.error,
        retry=state.retry_count,
    )

    await log_error_to_db(
        user_id=state.user_id,
        task=state.task,
        error=Exception(state.error),
    )

    if state.retry_count < settings.max_retries:
        # Clear the error and retry
        return AgentState(
            messages=state.messages,
            user_id=state.user_id,
            task=state.task,
            error=None,
            retry_count=state.retry_count + 1,
        )
    else:
        # Give up — return a user-friendly error message
        error_msg = AIMessage(
            content=(
                f"❌ I ran into an issue after {settings.max_retries} attempts:\n"
                f"{state.error}\n\n"
                "Please try again or rephrase your request."
            )
        )
        return AgentState(
            messages=[error_msg],
            user_id=state.user_id,
            task=state.task,
            error=None,
            retry_count=state.retry_count,
        )


# ── Routing logic ─────────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> Literal["tools", "error", END]:
    """
    After the agent node runs, decide what to do next:
    - If there was an error → error handler
    - If the LLM wants to call tools → execute tools
    - Otherwise → we're done, return response
    """
    if state.error:
        return "error"

    last_message = state.messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return END


def after_error(state: AgentState) -> Literal["agent", END]:
    """After handling an error, retry if we haven't given up."""
    if state.error is None and state.retry_count < settings.max_retries:
        return "agent"
    return END


# ── Build the graph ───────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Assemble and compile the agent graph."""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("error", error_handler_node)

    # Entry point
    graph.add_edge(START, "agent")

    # After agent: call tools, handle error, or finish
    graph.add_conditional_edges("agent", should_continue)

    # After tools: always go back to agent (ReAct loop)
    graph.add_edge("tools", "agent")

    # After error handler: retry or end
    graph.add_conditional_edges("error", after_error)

    return graph.compile()


# Module-level compiled graph (built once at import time)
agent_graph = build_graph()


# ── Public interface ──────────────────────────────────────────────────────────

async def run_agent(user_id: int, user_message: str, history: list[dict]) -> str:
    """
    Run the agent for a single user message.

    Args:
        user_id: Telegram user ID.
        user_message: The raw message text from the user.
        history: Previous messages from MemoryStore.get_history()

    Returns:
        The agent's final response as a string.
    """
    # Convert stored history to LangChain message format
    lc_messages = []
    for msg in history:
        if msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
        else:
            lc_messages.append(AIMessage(content=msg["content"]))

    # Add the new message
    lc_messages.append(HumanMessage(content=user_message))

    initial_state = AgentState(
        messages=lc_messages,
        user_id=user_id,
        task=user_message,
    )

    try:
        final_state = await agent_graph.ainvoke(initial_state)

        # Extract the last AI message as the response
        for msg in reversed(final_state["messages"]):
            if isinstance(msg, AIMessage) and msg.content:
                return msg.content

        return "I processed your request but couldn't generate a response. Please try again."

    except Exception as e:
        logger.error("run_agent_failed", user_id=user_id, error=str(e))
        return f"❌ An unexpected error occurred: {str(e)}"
