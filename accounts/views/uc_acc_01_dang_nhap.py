"""UC-ACC-01 Đăng nhập — GD-001 Đăng nhập, GD-002 Đổi mật khẩu lần đầu.

Luồng chính : OzzoneLoginView -> after_login (B4 nhân viên vào trang chủ / B4a quản trị vào Admin)
Luồng B2a   : first_password — tài khoản còn cờ bat_buoc_doi_mat_khau phải đổi mật khẩu rồi mới vào.
"""

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse

from projectp.models import HoSoNhanVien

from ..forms import DoiMatKhauForm, LoginForm


class OzzoneLoginView(auth_views.LoginView):
    """Sử dụng LoginView của Django với biểu mẫu và giao diện đăng nhập OZZONE."""

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
def after_login(request):
    """B4: nhân viên vào trang chủ. B4a: quản trị viên (không có hồ sơ) vào Django Admin."""
    if request.user.is_staff and not HoSoNhanVien.objects.filter(nguoi_dung=request.user).exists():
        return redirect("admin:index")
    # Chuyển đến trang chủ phù hợp với các phân hệ đang được cấu hình.
    for ten_url in ("core:home", "social:feed", "communities:list"):
        try:
            return redirect(reverse(ten_url))
        except NoReverseMatch:
            pass
    return redirect("accounts:profile")


@login_required
def first_password(request):
    """B2a: đổi mật khẩu lần đầu (GD-002)."""
    ho_so = HoSoNhanVien.objects.filter(nguoi_dung=request.user).first()
    if ho_so is None or not ho_so.bat_buoc_doi_mat_khau:
        return redirect("accounts:after_login")

    if request.method == "POST":
        form = DoiMatKhauForm(request.user, request.POST)
        if form.is_valid():
            old_hash = request.user.password
            try:
                with transaction.atomic():
                    form.save()
                    ho_so.bat_buoc_doi_mat_khau = False
                    ho_so.save()
            except DatabaseError:
                request.user.password = old_hash
                request.user._password = None
                ho_so.bat_buoc_doi_mat_khau = True
                form.add_error(None, "Chưa lưu được mật khẩu. Vui lòng thử lại.")
            else:
                update_session_auth_hash(request, form.user)
                messages.success(request, "Đã đổi mật khẩu. Chào mừng bạn đến với OZZONE.")
                return redirect("accounts:after_login")
    else:
        form = DoiMatKhauForm(request.user)
    return render(request, "accounts/first_password.html", {"form": form})
