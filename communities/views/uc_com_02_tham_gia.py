"""UC-COM-02 Tham gia cộng đồng — GD-036 Yêu cầu tham gia.

join           : nhân viên bấm Tham gia (B2a: cộng đồng mở -> vào ngay) hoặc Gửi yêu cầu (B2: chờ duyệt).
                 B2e đã là thành viên; B2f cộng đồng dự án; tư cách bị tạm dừng; đã có yêu cầu chờ.
cancel_request : người gửi tự hủy yêu cầu đang chờ.
join_requests  : chủ sở hữu xem/lọc yêu cầu gửi đến; mọi người xem yêu cầu của mình.
decide         : chủ sở hữu Duyệt (B4) hoặc Từ chối có lý do (B4a); B4e không phải chủ sở hữu.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from ._chung import active_community_memberships, community_change, handled
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from projectp.models import CommunityRole, CongDong, MemberStatus, ThanhVienCongDong, YeuCauThamGia

from ..forms import JoinRequestForm
from ._chung import (
    can_doi_mat_khau, ghi_nhat_ky, ho_ten, kich_hoat_thanh_vien, la_chu_so_huu, lay_cong_dong, sidebar, tu_cach,
)


@login_required
@can_doi_mat_khau
@handled
def join(request, pk):
    """Nhân viên bấm Tham gia / Gửi yêu cầu (chỉ nhận POST)."""
    cd = lay_cong_dong(request.user, pk)
    if request.method != "POST":
        return redirect("communities:detail", pk=pk)

    with community_change(request.user, pk) as cd:
        if cd.loai_cong_dong == CongDong.Type.PROJECT:                    # B2f
            messages.error(request, "Cộng đồng dự án được quản lý qua thành viên dự án. Liên hệ quản lý dự án.")
        elif tu_cach(request.user, cd):                                  # B2e
            messages.info(request, "Bạn đã là thành viên của cộng đồng này.")
        elif ThanhVienCongDong.objects.filter(cong_dong=cd, nguoi_dung=request.user,
                                              trang_thai=MemberStatus.SUSPENDED).exists():
            messages.error(request, "Tư cách thành viên của bạn đang bị tạm dừng. Liên hệ chủ sở hữu cộng đồng.")
        elif cd.quy_tac_tham_gia == CongDong.JoinRule.OPEN:              # B2a: tham gia trực tiếp
            tv = kich_hoat_thanh_vien(cd, request.user)
            # Yêu cầu chờ duyệt cũ (nếu cộng đồng vừa đổi sang 'tham gia trực tiếp') không còn ý nghĩa -> đóng lại
            YeuCauThamGia.objects.filter(cong_dong=cd, nguoi_dung=request.user,
                                         trang_thai=YeuCauThamGia.Status.PENDING).update(
                trang_thai=YeuCauThamGia.Status.CANCELLED, nguoi_xu_ly=request.user,
                ngay_xu_ly=timezone.now(), ly_do_xu_ly="Đã tham gia trực tiếp.",
            )
            ghi_nhat_ky(request, "tham_gia_cong_dong", "CONG_DONG", cd.pk, sau={"thanh_vien": tv.pk})
            messages.success(request, f"Bạn đã tham gia {cd.ten_cong_dong}.")
        elif YeuCauThamGia.objects.filter(cong_dong=cd, nguoi_dung=request.user,
                                          trang_thai=YeuCauThamGia.Status.PENDING).exists():
            messages.info(request, "Bạn đã có một yêu cầu đang chờ duyệt cho cộng đồng này.")
        else:                                                            # B2: lưu yêu cầu chờ duyệt
            form = JoinRequestForm(request.POST)
            if not form.is_valid():
                from .uc_com_04_bang_tin import community_detail
                return community_detail(request, pk)
            loi_nhan = form.cleaned_data["loi_nhan"]
            yc = YeuCauThamGia.objects.create(cong_dong=cd, nguoi_dung=request.user, loi_nhan=loi_nhan)
            ghi_nhat_ky(request, "gui_yeu_cau_tham_gia", "YEU_CAU_THAM_GIA", yc.pk)
            messages.success(request, "Đã gửi yêu cầu tham gia. Chủ sở hữu cộng đồng sẽ xem xét.")
    return redirect("communities:detail", pk=pk)


@login_required
@can_doi_mat_khau
@handled
def cancel_request(request, request_id):
    """Người gửi tự hủy yêu cầu đang chờ."""
    yc = get_object_or_404(YeuCauThamGia, pk=request_id, nguoi_dung=request.user)
    if request.method == "POST":
        with community_change(request.user, yc.cong_dong_id):
            yc = get_object_or_404(YeuCauThamGia, pk=request_id, nguoi_dung=request.user)
            if yc.trang_thai == YeuCauThamGia.Status.PENDING:
                yc.trang_thai = YeuCauThamGia.Status.CANCELLED
                yc.nguoi_xu_ly = request.user
                yc.ngay_xu_ly = timezone.now()
                yc.ly_do_xu_ly = "Người gửi hủy yêu cầu."
                yc.save()
                ghi_nhat_ky(request, "huy_yeu_cau_tham_gia", "YEU_CAU_THAM_GIA", yc.pk)
                messages.success(request, "Đã hủy yêu cầu tham gia.")
    return redirect("communities:detail", pk=yc.cong_dong_id)


@login_required
@can_doi_mat_khau
@handled
def join_requests(request):
    """GD-036 Yêu cầu tham gia: chủ sở hữu xử lý; mọi người xem yêu cầu của mình."""
    so_huu = active_community_memberships(request.user).filter(
        vai_tro=CommunityRole.OWNER, cong_dong__loai_cong_dong=CongDong.Type.GENERAL,
    ).values_list("cong_dong_id", flat=True)

    status = request.GET.get("status", "cho_duyet")
    if status not in (*YeuCauThamGia.Status.values, "all"):
        status = "cho_duyet"
    q = request.GET.get("q", "").strip()
    den = (YeuCauThamGia.objects.filter(cong_dong_id__in=so_huu)
           .select_related("cong_dong", "nguoi_xu_ly", "nguoi_dung__ho_so_nhan_vien__phong_ban")
           .order_by("-ngay_tao"))
    if status != "all":
        den = den.filter(trang_thai=status)
    if q:
        den = den.filter(Q(nguoi_dung__first_name__icontains=q) | Q(nguoi_dung__last_name__icontains=q)
                         | Q(cong_dong__ten_cong_dong__icontains=q))

    context = {
        "is_owner_anywhere": len(so_huu) > 0,
        "incoming": den,
        "mine": YeuCauThamGia.objects.filter(nguoi_dung=request.user, cong_dong__da_xoa_mem=False).select_related("cong_dong")
                                     .order_by("-ngay_tao"),
        "status": status,
        "q": q,
        "status_choices": [("cho_duyet", "Chờ duyệt"), ("da_duyet", "Đã duyệt"), ("da_tu_choi", "Đã từ chối"),
                           ("da_huy", "Đã hủy"), ("all", "Tất cả")],
    }
    context.update(sidebar(request, "requests"))
    return render(request, "communities/requests.html", context)


@login_required
@can_doi_mat_khau
@handled
def decide(request, request_id):
    """B3–B4: chủ sở hữu bấm Duyệt hoặc Từ chối (có lý do)."""
    yc = get_object_or_404(YeuCauThamGia, pk=request_id, cong_dong__da_xoa_mem=False)  # cộng đồng đã xóa -> 404
    if request.method != "POST":
        return redirect("communities:requests")

    with community_change(request.user, yc.cong_dong_id) as cd:
        yc = get_object_or_404(YeuCauThamGia.objects.select_related("nguoi_dung"), pk=request_id)
        duyet = request.POST.get("decision") == "approve"
        ly_do = request.POST.get("ly_do", "").strip()

        if cd.loai_cong_dong != CongDong.Type.GENERAL or cd.quy_tac_tham_gia == CongDong.JoinRule.PROJECT_MANAGED:
            messages.error(request, "Cộng đồng này không tiếp nhận yêu cầu tham gia tại đây.")
        elif request.POST.get("decision") not in ("approve", "reject"):
            messages.error(request, "Quyết định xử lý yêu cầu không hợp lệ.")
        elif not yc.nguoi_dung.is_active:
            messages.error(request, "Tài khoản người yêu cầu không còn hoạt động.")
        elif not la_chu_so_huu(tu_cach(request.user, cd)):                 # B4e
            messages.error(request, "Chỉ chủ sở hữu cộng đồng mới được xử lý yêu cầu tham gia.")
        elif yc.trang_thai != YeuCauThamGia.Status.PENDING:
            messages.error(request, "Yêu cầu này đã được xử lý trước đó.")
        elif not duyet and not ly_do:
            messages.error(request, "Vui lòng nhập lý do từ chối.")
        elif duyet and ThanhVienCongDong.objects.filter(cong_dong=cd, nguoi_dung=yc.nguoi_dung,
                                                        trang_thai=MemberStatus.SUSPENDED).exists():
            messages.error(request, "Người này đang bị tạm dừng tư cách thành viên, không thể duyệt.")
        else:
            if duyet:                                                    # B4: tạo thành viên
                if tu_cach(yc.nguoi_dung, cd) is None:   # đã là thành viên thì giữ nguyên vai trò, không hạ quyền
                    kich_hoat_thanh_vien(cd, yc.nguoi_dung)
                yc.trang_thai = YeuCauThamGia.Status.ACCEPTED
            else:                                                        # B4a: từ chối
                yc.trang_thai = YeuCauThamGia.Status.REJECTED
            yc.nguoi_xu_ly = request.user
            yc.ngay_xu_ly = timezone.now()
            yc.ly_do_xu_ly = ly_do
            yc.save()
            ghi_nhat_ky(request, "duyet_yeu_cau_tham_gia" if duyet else "tu_choi_yeu_cau_tham_gia",
                        "YEU_CAU_THAM_GIA", yc.pk, truoc={"trang_thai": "cho_duyet"},
                        sau={"trang_thai": yc.trang_thai}, ly_do=ly_do)
            messages.success(request, f"Đã {'duyệt' if duyet else 'từ chối'} yêu cầu của {ho_ten(yc.nguoi_dung)}.")
    return redirect("communities:requests")
