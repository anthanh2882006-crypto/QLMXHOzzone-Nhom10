"""UC-COM-05 Xem thành viên cộng đồng — GD-039 Thành viên cộng đồng.

members : tìm theo tên/vị trí, lọc theo vai trò; sắp xếp Chủ sở hữu -> Kiểm duyệt viên -> Thành viên.
          Chủ sở hữu thấy thêm nút bàn giao quyền (xử lý ở UC-COM-07, view transfer).
"""

from django.contrib.auth.decorators import login_required
from ._chung import du_an_lien_ket, duoc_dang, handled
from django.db.models import Q
from django.shortcuts import render

from projectp.models import CommunityRole, CongDong, MemberStatus, ThanhVienDuAn

from ..forms import MemberFilterForm
from ._chung import can_doi_mat_khau, duoc_doc, la_chu_so_huu, lay_cong_dong, sidebar, tu_cach


@login_required
@can_doi_mat_khau
@handled
def members(request, pk):
    """GD-039 Thành viên cộng đồng (chủ sở hữu thấy thêm nút bàn giao — UC-COM-07)."""
    cd = lay_cong_dong(request.user, pk)
    tv = tu_cach(request.user, cd)
    project = du_an_lien_ket(cd)
    context = {"community": cd, "membership": tv, "tab": "members", "project": project}
    context.update(sidebar(request, "members", cd))
    if not duoc_doc(cd, tv):
        context["locked"] = True
        return render(request, "communities/members.html", context)

    form = MemberFilterForm(request.GET or None)
    ds = cd.thanh_vien.filter(trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True, nguoi_dung__is_active=True).select_related(
        "nguoi_dung__ho_so_nhan_vien__phong_ban", "nguoi_dung__ho_so_nhan_vien__vi_tri")
    if form.is_valid():
        q = form.cleaned_data["q"]
        if q:
            ds = ds.filter(Q(nguoi_dung__first_name__icontains=q) | Q(nguoi_dung__last_name__icontains=q)
                           | Q(nguoi_dung__ho_so_nhan_vien__vi_tri__ten_vi_tri__icontains=q))
        if form.cleaned_data["vai_tro"]:
            ds = ds.filter(vai_tro=form.cleaned_data["vai_tro"])

    # Thứ tự hiển thị: Chủ sở hữu -> Kiểm duyệt viên -> Thành viên
    thu_tu = {CommunityRole.OWNER: 0, CommunityRole.MODERATOR: 1, CommunityRole.MEMBER: 2}
    rows = sorted(ds, key=lambda m: (thu_tu[m.vai_tro], m.nguoi_dung.first_name))

    project_members = set(ThanhVienDuAn.objects.filter(
        du_an=project, trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True,
        nguoi_dung__is_active=True,
    ).values_list("nguoi_dung_id", flat=True)) if project else set()
    for member in rows:
        member.can_receive_owner = project is None or member.nguoi_dung_id in project_members
    context.update({"form": form, "rows": rows, "is_owner": la_chu_so_huu(tv) and duoc_dang(cd, tv),
                    "is_project": cd.loai_cong_dong == CongDong.Type.PROJECT})
    return render(request, "communities/members.html", context)
