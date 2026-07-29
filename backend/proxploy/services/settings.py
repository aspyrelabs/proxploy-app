from proxploy.models import AppSetting


def get_setting(db, key: str, default=None):
    row = db.query(AppSetting).filter_by(key=key).one_or_none()
    return row.value if row else default


def set_setting(db, key: str, value) -> None:
    row = db.query(AppSetting).filter_by(key=key).one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()
