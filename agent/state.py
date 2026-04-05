"""
agent/state.py — the LangGraph agent's state schema.

LangGraph passes this state object between every node in the graph.
Think of it as the agent's working memory for a single conversation turn.
"""
from typing import Annotated, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """
    State carried through the agent graph.

    messages: Full conversation history for this session.
    user_id: Telegram user who sent the message.
    task: The original user request (human-readable).
    tool_outputs: Results from tool calls in this turn.
    error: Set if the agent hit a hard error.
    retry_count: How many times we've retried after an error.
    """
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    user_id: int = 0
    task: str = ""
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    retry_count: int = 0
