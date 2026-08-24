"""Database seed script.

Populates the database with initial products, admin user, and sample data.
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select

from app.auth.jwt import hash_password
from app.db.models import Product, User, UserRole
from app.db.session import async_session_factory

logger = structlog.get_logger(__name__)

INITIAL_PRODUCTS = [
    {
        "name": "Digitalsofts Poultry ERP",
        "category": "ERP",
        "description": "Comprehensive enterprise resource planning solution specifically designed for poultry farming businesses. Integrates flock management, feed, inventory, sales, and reporting.",
        "features": [
            "Flock Management",
            "Feed Management",
            "Inventory Control",
            "Sales & Distribution",
            "Financial Reporting",
        ],
        "pricing_tier": "Contact Sales",
        "is_active": True,
    },
    {
        "name": "Digitalsofts General ERP",
        "category": "ERP",
        "description": "Modular enterprise resource planning platform designed for medium to large businesses across multiple industries. Includes finance, supply chain, manufacturing, and project management.",
        "features": [
            "Financial Management",
            "Supply Chain",
            "Manufacturing",
            "Project Management",
            "Business Intelligence",
        ],
        "pricing_tier": "Starting from PKR 200,000/month",
        "is_active": True,
    },
    {
        "name": "Digitalsofts HRMS",
        "category": "HR",
        "description": "Complete human resource management solution covering the employee lifecycle from recruitment to retirement.",
        "features": [
            "Employee Management",
            "Attendance & Leave",
            "Payroll Processing",
            "Recruitment",
            "Performance Management",
        ],
        "pricing_tier": "Starting from PKR 30,000/month",
        "is_active": True,
    },
    {
        "name": "Digitalsofts CRM",
        "category": "CRM",
        "description": "Customer Relationship Management system to track sales pipelines, manage contacts, and improve customer engagement.",
        "features": [
            "Contact Management",
            "Sales Pipeline",
            "Marketing Automation",
            "Customer Support",
            "Analytics",
        ],
        "pricing_tier": "Starting from PKR 25,000/month",
        "is_active": True,
    },
    {
        "name": "Digitalsofts Inventory Management",
        "category": "Operations",
        "description": "Standalone solution for advanced inventory control, multi-location tracking, and automated reorders.",
        "features": [
            "Multi-Location Management",
            "Stock Control",
            "Purchase Management",
            "Barcode & RFID",
            "Reporting",
        ],
        "pricing_tier": "Starting from PKR 50,000/month",
        "is_active": True,
    },
]


async def seed() -> None:
    """Run the seed process."""
    logger.info("seed_started")

    async with async_session_factory() as session:
        # 1. Create admin user
        result = await session.execute(select(User).where(User.email == "admin@digitalsofts.com"))
        admin = result.scalar_one_or_none()

        if not admin:
            admin = User(
                email="admin@digitalsofts.com",
                hashed_password=hash_password("AdminPassword123!"),
                full_name="System Admin",
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin)
            logger.info("seed_admin_created")

        # 2. Create products
        for prod_data in INITIAL_PRODUCTS:
            result = await session.execute(select(Product).where(Product.name == prod_data["name"]))
            product = result.scalar_one_or_none()

            if not product:
                product = Product(**prod_data)
                session.add(product)
                logger.info("seed_product_created", name=prod_data["name"])

        await session.commit()
        logger.info("seed_completed")


if __name__ == "__main__":
    asyncio.run(seed())
