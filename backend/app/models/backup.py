from datetime import datetime
from sqlalchemy import String, BigInteger, DateTime, ForeignKey, Index, text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.user import Base


class Backup(Base):
    __tablename__ = 'backups'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='queued')
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('queued','running','ready','failed')", name='ck_backup_status'),
                     Index('backups_one_active', text('(true)'), unique=True,
                           postgresql_where=text("status IN ('queued','running')")),)
