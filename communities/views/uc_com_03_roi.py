"""UC-COM-03 Rời cộng đồng — GD-038 Xác nhận rời cộng đồng.

leave : GET hỏi lại; POST chuyển tư cách sang 'kết thúc' (giữ dòng -> giữ lịch sử, bài đã đăng).
        Không cho rời nếu là chủ sở hữu duy nhất, hoặc là cộng đồng dự án.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from ._chung import community_change, handled
from django.shortcuts import redirect, render
from django.utils import timezone

from projectp.models import CommunityRole, CongDong, MemberStatus

from ._chung import can_doi_mat_khau, ghi_nhat_ky, lay_cong_dong, sidebar, tu_cach


@login_required
@can_doi_mat_khau
@handled
def leave(request, pk):
    """GD-038 Xác nhận rời cộng đồng. GET: hỏi lại. POST: rời thật."""
    cd = lay_cong_dong(request.user, pk)
    tv = tu_cach(request.user, cd)
    if tv is None:
        messages.info(request, "Bạn không phải thành viên của cộng đồng này.")
        return redirect("communities:detail", pk=pk)

    so_chu_so_huu = cd.thanh_vien.filter(
        vai_tro=CommunityRole.OWNER, trang_thai=MemberStatus.ACTIVE,
        ket_thuc_luc__isnull=True, nguoi_dung__is_active=True,
    ).count()
    chu_duy_nhat = tv.vai_tro == CommunityRole.OWNER and so_chu_so_huu <= 1
    la_cd_du_an = cd.loai_cong_dong == CongDong.Type.PROJECT

    if request.method == "POST":
        with community_change(request.user, pk) as cd:
            tv = tu_cach(request.user, cd)
            if tv is None:
                messages.info(request, "Bạn không còn là thành viên hoạt động của cộng đồng.")
                return redirect("communities:detail", pk=pk)
            owners = cd.thanh_vien.filter(
                vai_tro=CommunityRole.OWNER, trang_thai=MemberStatus.ACTIVE,
                ket_thuc_luc__isnull=True, nguoi_dung__is_active=True,
            ).count()
            chu_duy_nhat = tv.vai_tro == CommunityRole.OWNER and owners <= 1
            la_cd_du_an = cd.loai_cong_dong == CongDong.Type.PROJECT
            if not chu_duy_nhat and not la_cd_du_an:
                tv.trang_thai = MemberStatus.ENDED
                tv.ket_thuc_luc = timezone.now()
                tv.save()
                ghi_nhat_ky(request, "roi_cong_dong", "THANH_VIEN_CONG_DONG", tv.pk,
                            sau={"trang_thai": tv.trang_thai})
                messages.success(request, f"Bạn đã rời {cd.ten_cong_dong}. Lịch sử bài đăng được giữ nguyên.")
                return redirect("communities:list")

    context = {"community": cd, "membership": tv, "sole_owner": chu_duy_nhat, "is_project": la_cd_du_an}
    context.update(sidebar(request, "community", cd))
    return render(request, "communities/leave.html", context)
