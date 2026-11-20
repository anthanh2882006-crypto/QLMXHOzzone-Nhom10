"""Nối điều kiện đổi mật khẩu của app Tài khoản với các phân hệ dùng chung phiên."""

from django.contrib.auth.views import redirect_to_login
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

from accounts.views import da_doi_mat_khau


class FirstPasswordRequiredMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if not request.user.is_authenticated or match.view_name in (
            "accounts:login", "accounts:logout", "accounts:first_password",
            "accounts:first_password_change", "legacy_account_login",
            "legacy_account_logout", "legacy_first_password", "admin:logout", "projects:logout",
        ):
            return None
        if not da_doi_mat_khau(request.user):
            return redirect_to_login(request.get_full_path(), reverse("accounts:first_password"))
        return None
