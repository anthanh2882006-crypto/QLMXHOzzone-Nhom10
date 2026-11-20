"""UC-ACC-04 Tra cứu nhân viên — GD-008 Danh bạ nhân viên, GD-009 Hồ sơ nhân viên (chỉ đọc).

directory       : tìm theo từ khóa (họ tên, mã NV, vị trí, kỹ năng) + lọc phòng ban/vị trí/kỹ năng.
employee_detail : xem hồ sơ người khác; B3e: nhân viên không còn hồ sơ -> trang 'không khả dụng'.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.db.models import Q
from django.shortcuts import redirect, render

from projectp.models import HoSoNhanVien

from ..forms import DirectorySearchForm
from ._chung import can_doi_mat_khau, thong_tin_ho_so

User = get_user_model()


@login_required
@can_doi_mat_khau
def directory(request):
    """GD-008 Danh bạ nhân viên."""
    try:
        return _render_directory(request)
    except DatabaseError:
        return render(request, "accounts/directory.html", {
            "active_side": "directory",
            "directory_error": "Chưa tải được danh bạ nhân viên. Vui lòng thử lại.",
        }, status=503)


def _render_directory(request):
    form = DirectorySearchForm(request.GET or None)
    people = HoSoNhanVien.objects.filter(nguoi_dung__is_active=True).order_by("nguoi_dung__first_name")

    if form.is_valid():
        data = form.cleaned_data
        for tu in data["q"].split():  # mỗi từ phải khớp (AND), một trong các cột (OR)
            people = people.filter(
                Q(nguoi_dung__first_name__icontains=tu)
                | Q(nguoi_dung__last_name__icontains=tu)
                | Q(ma_nhan_vien__icontains=tu)
                | Q(vi_tri__ten_vi_tri__icontains=tu)
                | Q(kynangnhanvien__ky_nang__ten_ky_nang__icontains=tu)
            )
        if data["phong_ban"]:
            people = people.filter(phong_ban=data["phong_ban"])
        if data["vi_tri"]:
            people = people.filter(vi_tri=data["vi_tri"])
        if data["ky_nang"]:
            people = people.filter(kynangnhanvien__ky_nang=data["ky_nang"])
        people = people.distinct()  # 1 người khớp 2 kỹ năng không bị lặp dòng

    return render(
        request, "accounts/directory.html", {"form": form, "people": people, "active_side": "directory"}
    )


@login_required
@can_doi_mat_khau
def employee_detail(request, username):
    """GD-009 Hồ sơ nhân viên (chỉ đọc)."""
    person = User.objects.filter(username=username, is_active=True).first()
    if person is None:
        return render(request, "accounts/employee_unavailable.html", {"active_side": "directory"}, status=404)
    if person == request.user:
        return redirect("accounts:profile")
    context = thong_tin_ho_so(person, viewer=request.user)
    if context["profile"] is None:  # B3e: nhân viên không còn khả dụng
        return render(request, "accounts/employee_unavailable.html", {"active_side": "directory"}, status=404)
    context.update({"is_me": False, "active_side": "directory"})
    return render(request, "accounts/profile.html", context)
