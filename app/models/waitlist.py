
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin


class WaitlistEntry(TimestampMixin, Base):
    __tablename__ = "waitlist_entries"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    show_id: Mapped[int] = mapped_column(
        ForeignKey("shows.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    seat_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    preferred_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="Waiting", index=True
    )

    show = relationship(
        "Show",
        back_populates="waitlist_entries",
    )

    customer = relationship(
        "User",
        back_populates="waitlist_entries",
    )
