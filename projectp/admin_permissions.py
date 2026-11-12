from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied


def current_admin(request, permission):
    """Đọc lại quyền khi ghi, kể cả khi tài khoản đã thay đổi trong lúc mở form."""
    actor = get_user_model().objects.get(pk=request.user.pk)
    if not actor.is_active or not actor.is_staff or not actor.has_perm(permission):
        raise PermissionDenied("Quyền quản trị đã thay đổi. Tải lại để kiểm tra quyền hiện hành.")
    return actor
