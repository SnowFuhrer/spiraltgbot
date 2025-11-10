import traceback

from sqlalchemy import Column, String, BigInteger
from tg_bot.modules.sql import BASE, SESSION


class Royals(BASE):
    __tablename__ = "royals"

    user_id = Column(BigInteger, primary_key=True)
    role_name = Column(String(255))

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role_name = role

    def __repr__(self):
        return f"<royal {self.user_id} with role {self.role_name}>"


# SQLAlchemy 2.x: explicitly bind when creating tables
with SESSION() as _s:
    BASE.metadata.create_all(bind=_s.get_bind(), tables=[Royals.__table__])


def is_royal(user_id: int, role: str = None) -> bool:
    with SESSION() as s:
        if role is not None:
            return s.query(Royals).filter(
                Royals.user_id == user_id,
                Royals.role_name == role,
            ).first() is not None
        else:
            return s.get(Royals, user_id) is not None


def get_royal_role(user_id: int):
    with SESSION() as s:
        row = s.get(Royals, user_id)
        return row.role_name if row else None


def get_royals(role: str = None):
    with SESSION() as s:
        q = s.query(Royals)
        if role is not None:
            q = q.filter(Royals.role_name == role)
        return q.all()


def set_royal_role(user_id: int, role: str):
    with SESSION() as s:
        try:
            row = s.get(Royals, user_id)
            if row is None:
                s.add(Royals(user_id, role))
            else:
                row.role_name = role
            s.commit()
        except Exception:
            traceback.print_exc()
            s.rollback()
            raise


def remove_royal(user_id: int):
    with SESSION() as s:
        try:
            row = s.get(Royals, user_id)
            if row:
                s.delete(row)
            s.commit()
        except Exception:
            traceback.print_exc()
            s.rollback()
            raise
