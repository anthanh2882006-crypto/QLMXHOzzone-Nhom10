"""UC-ACC-03 Quản lý hồ sơ cá nhân — GD-006 Hồ sơ của tôi, GD-007 Chỉnh sửa hồ sơ.

profile      : xem hồ sơ của chính mình.
profile_edit : sửa họ tên (bảng User), điện thoại/giới thiệu/ảnh (HoSoNhanVien), kỹ năng (KyNangNhanVien).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.shortcuts import redirect, render

from projectp.models import HoSoNhanVien, KyNangNhanVien
from social.permissions import accessible_posts

from ..forms import ProfileForm
from ..services import save_profile
from ._chung import can_doi_mat_khau, thong_tin_ho_so


@login_required
@can_doi_mat_khau
def profile(request):
    """GD-006 Hồ sơ của tôi."""
    context = thong_tin_ho_so(request.user)
    context.update({
        "is_me": True, "active_side": "profile",
        "contributions": accessible_posts(request.user).filter(nguoi_dang=request.user)[:8],
    })
    return render(request, "accounts/profile.html", context)


@login_required
@can_doi_mat_khau
def profile_edit(request):
    """GD-007 Chỉnh sửa hồ sơ."""
    ho_so = HoSoNhanVien.objects.filter(nguoi_dung=request.user).first()
    if ho_so is None:
        messages.info(request, "Tài khoản này chưa có hồ sơ nhân viên. Liên hệ quản trị viên.")
        return redirect("accounts:profile")

    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=ho_so)
        if form.is_valid():
            old_name = (request.user.first_name, request.user.last_name)
            try:
                save_profile(request.user, form)
            except (DatabaseError, OSError, ValidationError):
                request.user.first_name, request.user.last_name = old_name
                form.add_error(None, "Chưa lưu được hồ sơ. Dữ liệu cũ được giữ; bạn có thể thử lại.")
            else:
                messages.success(request, "Đã lưu hồ sơ.")
                return redirect("accounts:profile")
    else:
        form = ProfileForm(
            instance=ho_so,
            initial={
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "ky_nang": list(
                    KyNangNhanVien.objects.filter(ho_so=ho_so).values_list("ky_nang_id", flat=True)
                ),
            },
        )
    return render(
        request, "accounts/profile_edit.html", {"form": form, "profile": ho_so, "active_side": "profile"}
    )
