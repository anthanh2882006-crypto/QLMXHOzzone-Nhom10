"""UC-COM-04 Xem bảng tin cộng đồng — GD-034 Không gian cộng đồng (tab Bảng tin), trang chi tiết bài.

community_detail : bài đang hiển thị, bài ghim lên đầu; nút Tham gia/Gửi yêu cầu nếu chưa là thành viên.
post_detail      : đọc 1 bài trong đúng cộng đồng; bài ẩn chỉ người quản trị nội dung thấy (GD-017 nếu không khả dụng).
"""

from django.contrib.auth.decorators import login_required
from ._chung import community_posts, handled
from social.views import _post_cards, post_discussion_context
from django.shortcuts import redirect, render

from projectp.models import BaiViet, CongDong, DinhKem, MemberStatus, YeuCauThamGia

from ..forms import JoinRequestForm
from ._chung import (
    can_doi_mat_khau, du_an_lien_ket, duoc_dang, duoc_doc, la_quan_tri_noi_dung, lay_cong_dong, sidebar, tu_cach,
)


@login_required
@can_doi_mat_khau
@handled
def community_detail(request, pk):
    """GD-034 Không gian cộng đồng — tab Bảng tin, bài ghim lên đầu."""
    cd = lay_cong_dong(request.user, pk, include_project_introductions=True)
    tv = tu_cach(request.user, cd)
    if cd.loai_cong_dong == CongDong.Type.PROJECT and tv is None:
        return redirect("communities:about", pk=pk)

    posts = []
    if duoc_doc(cd, tv):
        posts = (
            community_posts(cd).filter(trang_thai="hien")
            .exclude(loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT)
            .select_related("nguoi_dang__ho_so_nhan_vien__vi_tri")
            .order_by("-da_ghim", "-ngay_tao")
        )

        posts = _post_cards(posts, request.user).order_by("-da_ghim", "-ngay_tao", "-ma_bai_viet")

    context = {
        "community": cd,
        "membership": tv,
        "can_read": duoc_doc(cd, tv),
        "can_post": duoc_dang(cd, tv),
        "can_moderate": la_quan_tri_noi_dung(tv),
        "project": du_an_lien_ket(cd),
        "posts": posts,
        "pending": YeuCauThamGia.objects.filter(cong_dong=cd, nguoi_dung=request.user,
                                                 trang_thai=YeuCauThamGia.Status.PENDING).first(),
        "join_form": JoinRequestForm(request.POST if request.method == "POST" else None),
        "is_suspended": cd.thanh_vien.filter(nguoi_dung=request.user, trang_thai=MemberStatus.SUSPENDED, ket_thuc_luc__isnull=True).exists(),
        "member_count": cd.thanh_vien.filter(trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True, nguoi_dung__is_active=True).count(),
        "tab": "feed",
    }
    context.update(sidebar(request, "community", cd))
    return render(request, "communities/detail.html", context)


@login_required
@can_doi_mat_khau
@handled
def post_detail(request, pk, post_id):
    """Đọc 1 bài trong đúng cộng đồng; bài ẩn chỉ người quản trị nội dung thấy (GD-017 nếu không khả dụng)."""
    cd = lay_cong_dong(request.user, pk)
    tv = tu_cach(request.user, cd)
    post = _post_cards(
        community_posts(cd).exclude(loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT).filter(pk=post_id),
        request.user,
    ).first()

    context = {"community": cd, "membership": tv}
    context.update(sidebar(request, "community", cd))
    if post is None or not duoc_doc(cd, tv) or (post.trang_thai != "hien" and not la_quan_tri_noi_dung(tv)):
        return render(request, "communities/unavailable.html", context, status=404)

    project = du_an_lien_ket(cd)
    if project and not post.du_an_id:
        post.du_an = project
    context.update(post_discussion_context(request, post))
    context.update({
        "project": project,
        "post": post,
        "attachments": DinhKem.objects.filter(bai_viet=post, tep_tin__trang_thai="san_sang", tep_tin__da_xoa_mem=False).select_related("tep_tin", "nguoi_dinh_kem"),
    })
    return render(request, "communities/post_detail.html", context)
