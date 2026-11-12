"""UC-COM-01 Khám phá / Xem cộng đồng — GD-033 Khám phá cộng đồng, GD-035 Giới thiệu cộng đồng.

community_list  : danh sách cộng đồng được thấy, tìm theo tên/mô tả, lọc 'của tôi', trạng thái của tôi ở từng cộng đồng.
community_about : trang giới thiệu (chủ sở hữu, số thành viên, dự án liên kết).
"""

from django.contrib.auth.decorators import login_required
from ._chung import active_community_memberships, handled
from django.db.models import Count, Q
from django.shortcuts import render

from projectp.models import CommunityRole, MemberStatus, ThanhVienCongDong, YeuCauThamGia

from ._chung import can_doi_mat_khau, cong_dong_xem_duoc, du_an_lien_ket, duoc_doc, lay_cong_dong, sidebar, tu_cach


@login_required
@can_doi_mat_khau
@handled
def community_list(request):
    """GD-033 Khám phá cộng đồng."""
    q = request.GET.get("q", "").strip()
    chi_cua_toi = request.GET.get("mine") == "1"

    ds = cong_dong_xem_duoc(request.user).annotate(
        so_thanh_vien=Count("thanh_vien", filter=Q(thanh_vien__trang_thai=MemberStatus.ACTIVE, thanh_vien__ket_thuc_luc__isnull=True, thanh_vien__nguoi_dung__is_active=True))
    )
    if q:
        ds = ds.filter(Q(ten_cong_dong__icontains=q) | Q(mo_ta__icontains=q))

    # Trạng thái của tôi ở từng cộng đồng: {mã cộng đồng: trạng thái}
    trang_thai_cua_toi = dict(
        ThanhVienCongDong.objects.filter(nguoi_dung=request.user).values_list("cong_dong_id", "trang_thai")
    )
    active_ids = set(active_community_memberships(request.user).values_list("cong_dong_id", flat=True))
    dang_cho = set(
        YeuCauThamGia.objects.filter(nguoi_dung=request.user, trang_thai=YeuCauThamGia.Status.PENDING)
        .values_list("cong_dong_id", flat=True)
    )

    cards = []
    for c in ds.order_by("loai_cong_dong", "ten_cong_dong"):
        st = trang_thai_cua_toi.get(c.pk)
        if c.pk in active_ids:
            state = "member"
        elif c.pk in dang_cho:
            state = "pending"
        elif st == MemberStatus.SUSPENDED:
            state = "suspended"
        else:
            state = "none"
        if chi_cua_toi and state != "member":
            continue
        cards.append({"c": c, "state": state})

    context = {"cards": cards, "q": q, "mine": chi_cua_toi}
    context.update(sidebar(request, "explore"))
    return render(request, "communities/list.html", context)


@login_required
@can_doi_mat_khau
@handled
def community_about(request, pk):
    """GD-035 Giới thiệu cộng đồng."""
    cd = lay_cong_dong(request.user, pk)
    tv = tu_cach(request.user, cd)
    context = {
        "community": cd,
        "membership": tv,
        "owners": cd.thanh_vien.filter(vai_tro=CommunityRole.OWNER, trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True, nguoi_dung__is_active=True),
        "member_count": cd.thanh_vien.filter(trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True, nguoi_dung__is_active=True).count(),
        "project": du_an_lien_ket(cd),
        "can_read": duoc_doc(cd, tv),
        "tab": "about",
    }
    context.update(sidebar(request, "community", cd))
    return render(request, "communities/about.html", context)
