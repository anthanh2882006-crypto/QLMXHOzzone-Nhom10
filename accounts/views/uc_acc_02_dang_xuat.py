"""UC-ACC-02 Đăng xuất — GD-005 Cài đặt tài khoản, trang xác nhận đăng xuất.

logout_view      : GET hỏi xác nhận, POST đăng xuất thật (B3e: phiên hết hạn thì về trang đăng nhập).
account_settings : đổi mật khẩu (nhánh B1b) + nút đăng xuất.
"""

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from urllib.parse import urlsplit

from ..forms import DoiMatKhauForm
from ._chung import can_doi_mat_khau


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """Hiển thị xác nhận với GET và kết thúc phiên đăng nhập với POST."""
    if request.method == "POST":
        logout(request)
        return redirect("accounts:login")
    if not request.user.is_authenticated:      # B3e: phiên đã hết hạn
        return redirect("accounts:login")
    next_url = request.GET.get("next", "")
    if (
        not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
        or urlsplit(next_url).path in {
            reverse("accounts:logout"), reverse("projects:logout"), reverse("admin:logout"),
        }
    ):
        next_url = reverse("accounts:after_login")
    return render(request, "accounts/logout_confirm.html", {
        "active_side": "settings", "cancel_url": next_url,
    })


@login_required
@can_doi_mat_khau
def account_settings(request):
    """GD-005 Cài đặt tài khoản: đổi mật khẩu + nút đăng xuất."""
    if request.method == "POST":
        form = DoiMatKhauForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, "Đã đổi mật khẩu.")
            return redirect("accounts:settings")
    else:
        form = DoiMatKhauForm(request.user)
    return render(request, "accounts/settings.html", {"form": form, "active_side": "settings"})
