import asyncio
import sys

from sqlalchemy import select

from app.db.models import User, UserRole
from app.db.session import async_session_factory


async def promote_user(email: str):
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: User with email '{email}' not found.")
            return

        if user.role == UserRole.ADMIN:
            print(f"User '{email}' is already an admin.")
            return

        user.role = UserRole.ADMIN
        await db.commit()
        print(f"Successfully promoted '{email}' to ADMIN.")

if __name__ == "__main__":
    email = "user@example.com"
    if len(sys.argv) > 1:
        email = sys.argv[1]

    asyncio.run(promote_user(email))
