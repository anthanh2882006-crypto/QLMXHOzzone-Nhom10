"""UC-PRJ-02, danh sách và tổng quan dự án theo tư cách người đang đăng nhập."""

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.shortcuts import render, redirect
from django.http import Http404
from django.views.decorators.http import require_GET
from projectp.models import BaiViet, DuAn, MaThietBi, MemberStatus, ThanhVienDuAn
from .forms import ProjectSearchForm
from .permissions import (
    active_memberships,
    explicit_permission,
    project_access,
    readable_projects,
    readable_project_posts,
)
from .presentation import handled, screen
from .ui import with_issue_state
from projectp.models import LanThuPhuongAn, PhanCongTriThuc


@login_required(login_url="projects:login")
@require_GET
@handled
def project_list(request):
    """GD-043. Tìm và hiển thị các dự án thuộc phạm vi người dùng được xem."""
    form = ProjectSearchForm(request.GET)
    query = readable_projects(request.user)
    context = screen(title="Dự án của tôi")
    context.update(
        form=form, page_obj=None, can_create=explicit_permission(request.user, "add_duan")
    )
    context["stats"] = {
        "active": query.filter(trang_thai=DuAn.Status.ACTIVE).count(),
        "archived": query.filter(trang_thai=DuAn.Status.ARCHIVED).count(),
        "issues": readable_issues(request.user).count(),
    }
    if form.is_valid():
        keyword = form.cleaned_data["q"]
        if keyword:
            query = query.filter(
                Q(ten_du_an__icontains=keyword) | Q(ma_du_an_nghiep_vu__icontains=keyword)
            )
        if form.cleaned_data["status"]:
            query = query.filter(trang_thai=form.cleaned_data["status"])
        if form.cleaned_data["role"]:
            query = query.filter(
                pk__in=active_memberships(request.user)
                .filter(vai_tro=form.cleaned_data["role"])
                .values("du_an_id")
            )
        page = Paginator(query.order_by("-ngay_tao", "-pk"), 12).get_page(
            request.GET.get("page")
        )
        roles = {m.du_an_id: m for m in active_memberships(request.user)}
        cards = []
        for project in page:
            cards.append(
                {
                    "project": project,
                    "membership": roles[project.pk],
                    "members": ThanhVienDuAn.objects.filter(
                        du_an=project, trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True
                    ).count(),
                    "devices": MaThietBi.objects.filter(
                        du_an=project, dang_su_dung=True
                    ).count(),
                    "issues": readable_project_posts(request.user, project)
                    .filter(che_do_xu_ly=True, trang_thai_xu_ly=BaiViet.TechnicalStatus.OPEN)
                    .count(),
                }
            )
        context.update(page_obj=page, cards=cards)
    return render(request, "projects/project_list.html", context)


def readable_issues(user):
    """Đếm vấn đề đang mở mà người dùng thực sự được đọc."""
    return BaiViet.objects.filter(
        du_an__in=readable_projects(user),
        che_do_xu_ly=True,
        trang_thai_xu_ly=BaiViet.TechnicalStatus.OPEN,
        trang_thai="hien",
        da_xoa_mem=False,
    ).filter(Q(cong_dong__isnull=True) | Q(cong_dong_id=F("du_an__cong_dong_id")))


@login_required(login_url="projects:login")
@require_GET
@handled
def project_detail(request, pk):
    """GD-045/GD-046. Tổng quan dự án và các lối vào nghiệp vụ theo quyền."""
    try:
        project, membership = project_access(request.user, pk)
    except (PermissionDenied, Http404):
        # UC-02 B2e đưa người dùng về GD-043, cùng một thông báo cho các trường hợp bị từ chối.
        messages.error(request, "Không thể mở dự án hoặc quyền truy cập đã thay đổi.")
        return redirect("projects:list")
    posts = with_issue_state(readable_project_posts(request.user, project))
    context = screen(project, membership, project.ten_du_an, "detail")
    context.update(
        activities=list(posts.select_related("nguoi_dang")[:5]),
        assigned_trials=list(
            LanThuPhuongAn.objects.filter(
                phuong_an__bai_viet__in=posts.filter(
                    che_do_xu_ly=True, trang_thai_xu_ly=BaiViet.TechnicalStatus.OPEN
                ),
                nguoi_thuc_hien=request.user,
                trang_thai__in=["cho_ket_qua", "dang_thuc_hien"],
                ket_qua__isnull=True,
            )
            .select_related("phuong_an__bai_viet")
            .order_by("ngay_thu", "pk")[:5]
        ),
        curators=PhanCongTriThuc.objects.filter(
            du_an=project, ket_thuc_luc__isnull=True
        ).select_related("nguoi_phu_trach"),
        issue_count=posts.filter(
            che_do_xu_ly=True, trang_thai_xu_ly=BaiViet.TechnicalStatus.OPEN
        ).count(),
        issues=list(posts.filter(che_do_xu_ly=True).select_related("ma_the_thiet_bi")[:5]),
        member_count=ThanhVienDuAn.objects.filter(
            du_an=project, trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True
        ).count(),
        device_count=MaThietBi.objects.filter(du_an=project, dang_su_dung=True).count(),
        can_manage=membership.vai_tro == "quan_ly" and not project.da_luu_tru,
    )
    return render(request, "projects/project_detail.html", context)
