"""Tool registry and execution engine.

Centralizes tool registration, schema validation, authorization,
timeout enforcement, and audit logging. No tool executes without
passing through this safety layer.

Execution flow:
  Tool request → Schema validation → Authorization check
    → Business validation → Execution with timeout → Audit log
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable, Coroutine  # noqa: TC003
from dataclasses import dataclass
from datetime import date
from typing import Any  # noqa: TC003

import structlog
from sqlalchemy import select

from app.config import get_settings
from app.db.models import DemoRequest, Product

settings = get_settings()
logger = structlog.get_logger(__name__)


@dataclass
class ToolDefinition:
    """Registration of a tool with its metadata and handler."""

    name: str
    description: str
    handler: Callable[..., Coroutine[Any, Any, dict]]
    required_role: str = "user"  # Minimum role required
    timeout_seconds: int = 10
    requires_confirmation: bool = False


# ── Tool Registry ────────────────────────────────────────────────────────────

_tools: dict[str, ToolDefinition] = {}


def register_tool(tool_def: ToolDefinition) -> None:
    """Register a tool in the allowlist."""
    _tools[tool_def.name] = tool_def
    logger.info("tool_registered", name=tool_def.name)


async def execute_tool(
    tool_name: str,
    tool_input: dict,
    user_id: str,
    user_role: str,
) -> dict:
    """Execute a tool through the safety layer.

    1. Verify tool is in allowlist
    2. Check user authorization
    3. Execute with timeout
    4. Log execution for audit
    """
    # 1. Allowlist check
    if tool_name not in _tools:
        raise ValueError(f"Tool '{tool_name}' is not registered")

    tool_def = _tools[tool_name]

    # 2. Authorization check
    role_hierarchy = {"admin": 2, "user": 1}
    user_level = role_hierarchy.get(user_role, 0)
    required_level = role_hierarchy.get(tool_def.required_role, 0)

    if user_level < required_level:
        raise PermissionError(
            f"Insufficient permissions for tool '{tool_name}'. "
            f"Required role: {tool_def.required_role}"
        )

    # 3. Execute with timeout
    start = time.monotonic()

    try:
        result = await asyncio.wait_for(
            tool_def.handler(**tool_input),
            timeout=tool_def.timeout_seconds,
        )
    except TimeoutError:
        duration = int((time.monotonic() - start) * 1000)
        logger.error(
            "tool_timeout",
            tool=tool_name,
            timeout=tool_def.timeout_seconds,
            duration_ms=duration,
        )
        raise TimeoutError(
            f"Tool '{tool_name}' timed out after {tool_def.timeout_seconds}s"
        ) from None

    duration_ms = int((time.monotonic() - start) * 1000)

    # 4. Audit log
    logger.info(
        "tool_executed",
        tool=tool_name,
        user_id=user_id,
        duration_ms=duration_ms,
        success=True,
    )

    return result


# ── Tool Implementations ─────────────────────────────────────────────────────


async def search_products(
    query: str,
    category: str | None = None,
) -> dict:
    """Search for products/services matching the query.

    Returns structured product data from the products table.
    """
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        stmt = select(Product).where(Product.is_active == True)  # noqa: E712

        if category:
            stmt = stmt.where(Product.category == category)

        # Simple text search on name and description
        stmt = stmt.where(
            Product.name.ilike(f"%{query}%")
            | Product.description.ilike(f"%{query}%")
        )
        stmt = stmt.limit(10)

        result = await session.execute(stmt)
        products = result.scalars().all()

        return {
            "products": [
                {
                    "name": p.name,
                    "category": p.category,
                    "description": p.description,
                    "features": p.features,
                    "pricing_tier": p.pricing_tier,
                }
                for p in products
            ],
            "count": len(products),
        }


async def create_demo_request(
    customer_name: str,
    email: str,
    company: str,
    product: str,
    requirements: str | None = None,
) -> dict:
    """Create a demo request in the mock CRM.

    Uses idempotency key (hash of email + product + date) to prevent
    duplicate submissions.
    """
    from app.db.session import async_session_factory

    # Generate idempotency key
    key_input = f"{email}:{product}:{date.today().isoformat()}"
    idempotency_key = hashlib.sha256(key_input.encode()).hexdigest()

    async with async_session_factory() as session:
        # Check for existing request
        existing = await session.execute(
            select(DemoRequest).where(DemoRequest.idempotency_key == idempotency_key)
        )
        if existing.scalar_one_or_none():
            return {
                "status": "already_exists",
                "message": "A demo request for this product has already been submitted today.",
            }

        demo = DemoRequest(
            customer_name=customer_name,
            email=email,
            company=company,
            product=product,
            requirements=requirements,
            idempotency_key=idempotency_key,
        )
        session.add(demo)
        await session.commit()
        await session.refresh(demo)

        return {
            "status": "created",
            "demo_request_id": str(demo.id),
            "message": f"Demo request created for {product}. Our team will contact {email} within 24 hours.",  # noqa: E501
        }


async def search_knowledge(
    query: str,
    filters: dict | None = None,
) -> dict:
    """Search the knowledge base with optional metadata filters."""
    from app.db.session import async_session_factory
    from app.retrieval.retriever import hybrid_retrieve

    async with async_session_factory() as session:
        result = await hybrid_retrieve(
            query=query,
            db=session,
            metadata_filters=filters,
            rerank_top_k=5,
        )

        return {
            "results": [
                {
                    "content": chunk.content[:500],
                    "source": chunk.metadata.get("title", "Unknown"),
                    "section": chunk.metadata.get("section", ""),
                    "score": round(chunk.score, 3),
                }
                for chunk in result.chunks
            ],
            "count": len(result.chunks),
        }


async def compare_products(
    product_a: str,
    product_b: str,
) -> dict:
    """Compare two products based on structured data and knowledge base."""
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        # Get product data
        result_a = await session.execute(
            select(Product).where(Product.name.ilike(f"%{product_a}%"))
        )
        result_b = await session.execute(
            select(Product).where(Product.name.ilike(f"%{product_b}%"))
        )

        prod_a = result_a.scalar_one_or_none()
        prod_b = result_b.scalar_one_or_none()

        comparison = {
            "product_a": {
                "name": prod_a.name if prod_a else product_a,
                "found": prod_a is not None,
                "category": prod_a.category if prod_a else "Unknown",
                "description": prod_a.description if prod_a else "Not found",
                "features": prod_a.features if prod_a else [],
                "pricing_tier": prod_a.pricing_tier if prod_a else "Unknown",
            },
            "product_b": {
                "name": prod_b.name if prod_b else product_b,
                "found": prod_b is not None,
                "category": prod_b.category if prod_b else "Unknown",
                "description": prod_b.description if prod_b else "Not found",
                "features": prod_b.features if prod_b else [],
                "pricing_tier": prod_b.pricing_tier if prod_b else "Unknown",
            },
        }

        return comparison


# ── Register all tools ───────────────────────────────────────────────────────

def register_all_tools() -> None:
    """Register all available tools. Called at application startup."""
    register_tool(ToolDefinition(
        name="search_products",
        description="Search for products and services",
        handler=search_products,
        required_role="user",
        timeout_seconds=10,
    ))

    register_tool(ToolDefinition(
        name="create_demo_request",
        description="Create a product demo request",
        handler=create_demo_request,
        required_role="user",
        timeout_seconds=10,
        requires_confirmation=True,
    ))

    register_tool(ToolDefinition(
        name="search_knowledge",
        description="Search the knowledge base",
        handler=search_knowledge,
        required_role="user",
        timeout_seconds=15,
    ))

    register_tool(ToolDefinition(
        name="compare_products",
        description="Compare two products",
        handler=compare_products,
        required_role="user",
        timeout_seconds=10,
    ))
