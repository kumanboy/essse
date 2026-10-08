def is_admin(user_id: int, admin_id: int) -> bool:
    return user_id == admin_id


def require_admin(user_id: int, admin_id: int) -> None:
    if not is_admin(user_id, admin_id):
        raise PermissionError("Admin access required")
