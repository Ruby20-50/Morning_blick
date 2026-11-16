from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import ProcessedWebhook


def mark_processed(db: Session, notification_id: str) -> bool:
    """True if new, False if this notification was already handled."""
    db.add(ProcessedWebhook(notification_id=notification_id))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False