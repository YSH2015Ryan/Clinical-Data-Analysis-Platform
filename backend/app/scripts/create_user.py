"""运维脚本：创建用户。

契约（docs/14）无 /auth/register 端点——初始管理员与后续账号由部署/运维侧创建：
    docker compose exec api python -m app.scripts.create_user \\
        --email admin@example.com --password '<随机>' --role admin
"""

import argparse
import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db import get_session_factory
from app.models.entities import User


async def _create(email: str, password: str, role: str, display_name: str) -> None:
    async with get_session_factory()() as db:
        exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if exists is not None:
            print(f"用户已存在: {email}")
            return
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                role=role,
                display_name=display_name or email,
            )
        )
        await db.commit()
        print(f"已创建: {email} (role={role})")


def main() -> None:
    parser = argparse.ArgumentParser(description="创建 CDAP 用户")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="researcher", choices=["admin", "researcher", "viewer"])
    parser.add_argument("--display-name", default="")
    args = parser.parse_args()
    asyncio.run(_create(args.email, args.password, args.role, args.display_name))


if __name__ == "__main__":
    main()
