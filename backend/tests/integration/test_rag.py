"""Integration tests for the RAG pipeline and LangGraph Agent."""

import pytest
from app.agents.graph import run_agent
from app.agents.state import AgentState
from app.retrieval.retriever import RetrievedChunk

@pytest.mark.asyncio
async def test_agent_unsupported_intent(monkeypatch):
    """Test that unsupported intents route directly to the unsupported response node."""
    async def mock_classify_intent(state: AgentState):
        state.intent = "unsupported"
        state.intent_confidence = 0.99
        return state

    monkeypatch.setattr("app.agents.graph.classify_intent", mock_classify_intent)

    state = await run_agent(query="What is the meaning of life?", user_id="test_user")

    assert state.intent == "unsupported"
    assert state.confidence == "unsupported"
    assert "outside my area of expertise" in state.response
    assert state.current_node == "generate_unsupported"
    assert len(state.citations) == 0


@pytest.mark.asyncio
async def test_agent_knowledge_workflow(monkeypatch):
    """Test the complete RAG knowledge workflow (retrieve -> evaluate -> generate -> verify)."""
    
    # 1. Mock intent classification
    async def mock_classify_intent(state: AgentState):
        state.intent = "knowledge"
        state.intent_confidence = 0.95
        return state
    
    # 2. Mock retrieval
    async def mock_retrieve_knowledge(state: AgentState):
        state.retrieved_chunks = [
            RetrievedChunk(
                chunk_id="chunk1",
                document_id="doc1",
                content="Digitalsofts flagship product is Enterprise Suite.",
                metadata={"title": "Product Guide", "source": "guide.md"},
                score=0.9
            )
        ]
        state.retrieval_query = state.query
        state.retrieval_score = 0.9
        state.iteration_count += 1
        return state

    # 3. Mock evaluation
    async def mock_evaluate_retrieval(state: AgentState):
        state.confidence = "supported"
        return state

    # 4. Mock generation
    async def mock_generate_answer(state: AgentState):
        state.response = "Digitalsofts flagship product is Enterprise Suite. [1]"
        return state

    # 5. Mock verification
    async def mock_verify_response(state: AgentState):
        from app.agents.state import Citation
        state.citations = [
            Citation(
                index=1,
                title="Product Guide",
                source="guide.md",
                chunk_id="chunk1"
            )
        ]
        state.current_node = "verify_response"
        return state

    monkeypatch.setattr("app.agents.graph.classify_intent", mock_classify_intent)
    monkeypatch.setattr("app.agents.graph.retrieve_knowledge", mock_retrieve_knowledge)
    monkeypatch.setattr("app.agents.graph.evaluate_retrieval", mock_evaluate_retrieval)
    monkeypatch.setattr("app.agents.graph.generate_answer", mock_generate_answer)
    monkeypatch.setattr("app.agents.graph.verify_response", mock_verify_response)

    state = await run_agent(query="What is the flagship product?", user_id="test_user")

    assert state.intent == "knowledge"
    assert state.confidence == "supported"
    assert "Enterprise Suite" in state.response
    assert state.iteration_count == 1
    assert len(state.citations) == 1
    assert state.citations[0].source == "guide.md"
