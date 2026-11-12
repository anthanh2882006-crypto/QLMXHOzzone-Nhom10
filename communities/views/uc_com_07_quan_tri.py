"""UC-COM-07, kiểm duyệt và bàn giao OWNER trong đúng cộng đồng."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from projectp.models import BaiViet, CommunityRole, CongDong, DuAn, MemberStatus, ThanhVienDuAn
from social.permissions import protected_source_reason
from ..services import handover_roles
from ._chung import (
    active_community_memberships,
    can_doi_mat_khau,
    community_change,
    community_posts,
    du_an_lien_ket,
    duoc_dang,
    ghi_nhat_ky,
    handled,
    ho_ten,
    la_chu_so_huu,
    la_quan_tri_noi_dung,
    lay_cong_dong,
    sidebar,
    tu_cach,
)


@login_required
@can_doi_mat_khau
@handled
def moderation_home(request):
    managed = (
        active_community_memberships(request.user)
        .filter(
            vai_tro__in=[CommunityRole.OWNER, CommunityRole.MODERATOR],
        )
        .exclude(cong_dong__du_an_lien_ket__trang_thai=DuAn.Status.ARCHIVED)
    )
    managed = managed.select_related("cong_dong").order_by("cong_dong__ten_cong_dong")
    if managed.count() == 1:
        return redirect("communities:moderation", pk=managed.first().cong_dong_id)
    context = {"managed": managed}
    context.update(sidebar(request, "moderation"))
    return render(request, "communities/moderation_home.html", context)


@login_required
@can_doi_mat_khau
@handled
def moderation(request, pk):
    community = lay_cong_dong(request.user, pk)
    membership = tu_cach(request.user, community)
    if not la_quan_tri_noi_dung(membership):
        messages.error(request, "Bạn không còn quyền kiểm duyệt hoặc dự án đã lưu trữ.")
        return redirect("communities:detail", pk=pk)
    status = request.GET.get("status", "")
    keyword = request.GET.get("q", "").strip()
    posts = (
        community_posts(community)
        .exclude(
            loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
        )
        .select_related("nguoi_dang")
        .order_by("-da_ghim", "-ngay_tao")
    )
    if status in ("hien", "an"):
        posts = posts.filter(trang_thai=status)
    elif status == "ghim":
        posts = posts.filter(da_ghim=True)
    if keyword:
        posts = posts.filter(Q(tieu_de__icontains=keyword) | Q(noi_dung__icontains=keyword))
    context = {
        "community": community,
        "membership": membership,
        "posts": posts,
        "status": status,
        "q": keyword,
        "project": du_an_lien_ket(community),
    }
    context.update(sidebar(request, "moderation", community))
    return render(request, "communities/moderation.html", context)


@login_required
@can_doi_mat_khau
@handled
def moderate(request, pk, post_id):
    if request.method != "POST":
        return redirect("communities:moderation", pk=pk)
    with community_change(request.user, pk) as community:
        membership = tu_cach(request.user, community)
        post = get_object_or_404(community_posts(community), pk=post_id)
        action = request.POST.get("action")
        reason = protected_source_reason(post) if action == "hide" else ""
        if not la_quan_tri_noi_dung(membership):
            messages.error(request, "Bạn không còn quyền kiểm duyệt hoặc dự án đã lưu trữ.")
        elif post.loai_bai_viet == BaiViet.Kind.ANNOUNCEMENT:
            messages.error(request, "Thông báo chính thức được quản lý theo quy trình riêng.")
        elif action not in ("pin", "unpin", "hide", "show"):
            messages.error(request, "Thao tác kiểm duyệt không hợp lệ.")
        elif reason:
            messages.error(request, reason)
        elif action == "pin" and post.trang_thai != "hien":
            messages.error(request, "Chỉ ghim được bài đang hiển thị.")
        else:
            before = {"trang_thai": post.trang_thai, "da_ghim": post.da_ghim}
            if action == "pin":
                if not post.da_ghim:
                    post.da_ghim, post.ghim_luc, post.nguoi_ghim = True, timezone.now(), request.user
            elif action == "unpin":
                post.da_ghim, post.ghim_luc, post.nguoi_ghim = False, None, None
            elif action == "hide":
                post.trang_thai = "an"
                post.da_ghim, post.ghim_luc, post.nguoi_ghim = False, None, None
            else:
                post.trang_thai = "hien"
            after = {"trang_thai": post.trang_thai, "da_ghim": post.da_ghim}
            if before != after:
                post.full_clean()
                post.save()
                ghi_nhat_ky(request, f"kiem_duyet_{action}", "BAI_VIET", post.pk, truoc=before, sau=after)
                messages.success(request, "Đã cập nhật trạng thái bài đăng.")
            else:
                messages.info(request, "Bài đăng đã ở trạng thái được yêu cầu.")
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)
    return redirect("communities:moderation", pk=pk)


@login_required
@can_doi_mat_khau
@handled
def transfer(request, pk):
    """Giữ ít nhất một OWNER hoạt động và giữ nguyên vai trò dự án."""
    if request.method != "POST":
        return redirect("communities:members", pk=pk)
    with community_change(request.user, pk) as community:
        membership = tu_cach(request.user, community)
        project = du_an_lien_ket(community)
        candidates = community.thanh_vien.filter(
            trang_thai=MemberStatus.ACTIVE,
            ket_thuc_luc__isnull=True,
            nguoi_dung__is_active=True,
        ).select_related("nguoi_dung")
        if project:
            candidates = candidates.filter(
                nguoi_dung_id__in=ThanhVienDuAn.objects.filter(
                    du_an=project,
                    trang_thai=MemberStatus.ACTIVE,
                    ket_thuc_luc__isnull=True,
                    nguoi_dung__is_active=True,
                ).values("nguoi_dung_id")
            )
        member_id = request.POST.get("member_id", "")
        valid_id = member_id.isascii() and member_id.isdecimal() and len(member_id) < 20
        recipient = (
            candidates.filter(pk=int(member_id)).first()
            if valid_id and 0 < int(member_id) <= 9223372036854775807
            else None
        )
        if request.POST.get("confirm") != "1":
            messages.error(request, "Cần xác nhận trước khi bàn giao.")
        elif not la_chu_so_huu(membership) or not duoc_dang(community, membership):
            messages.error(request, "Bạn không có quyền bàn giao hoặc dự án đã lưu trữ.")
        elif recipient is None:
            messages.error(request, "Người nhận phải đang hoạt động trong đúng cộng đồng và dự án liên kết.")
        elif recipient.vai_tro == CommunityRole.OWNER:
            messages.info(request, "Người nhận đã là chủ sở hữu.")
        else:
            before, after = handover_roles(community, membership.pk, recipient.pk)
            ghi_nhat_ky(
                request, "ban_giao_chu_so_huu", "THANH_VIEN_CONG_DONG", recipient.pk, truoc=before, sau=after
            )
            messages.success(request, f"Đã bàn giao quyền chủ sở hữu cho {ho_ten(recipient.nguoi_dung)}.")
    return redirect("communities:members", pk=pk)
