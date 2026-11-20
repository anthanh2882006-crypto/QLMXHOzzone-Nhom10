"""UC-PRJ-10, đọc diễn biến từ dữ liệu cũ và nhật ký, chỉ mở nguồn còn quyền đọc."""

from accounts.views._chung import ho_ten
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from projectp.models import (
    BaiViet,
    BinhLuan,
    DuAn,
    KetLuanXuLy,
    KetQuaThu,
    LanThuPhuongAn,
    NhatKyNghiepVu,
    PhuongAnXuLy,
)
from .forms_history import HistoryForm
from .permissions import active_memberships, project_access, readable_project_posts
from .presentation import handled, screen
from .history_details import snapshot_changes

MANAGEMENT_LABELS = {
    "info": "Cập nhật thông tin dự án",
    "member_add": "Thêm thành viên",
    "member_role": "Điều chỉnh vai trò",
    "member_end": "Kết thúc tư cách thành viên",
    "equipment": "Cập nhật thiết bị / tài sản",
    "knowledge": "Phân công tri thức",
    "knowledge_end": "Kết thúc phân công tri thức",
    "archive": "Lưu trữ dự án",
}


def _history_access(request, pk, admin_site):
    if admin_site is None:
        return project_access(request.user, pk)
    actor = get_user_model().objects.get(pk=request.user.pk)
    request.user = actor
    model_admin = admin_site._registry[DuAn]
    project = model_admin.get_object(request, str(pk))
    if not admin_site.has_permission(request) or project is None or not model_admin.has_view_or_change_permission(request, project):
        raise PermissionDenied("Không có quyền xem lịch sử quản trị của dự án này.")
    return project, active_memberships(actor).filter(du_an=project).first()


def _history_context(request, project, membership, title, admin_site):
    context = screen(project, membership, title, "history")
    context["history_url"] = reverse("projects:history", kwargs={"pk": project.pk})
    if admin_site is not None:
        context.update(admin_site.each_context(request))
        context.update(
            history_base="admin/projectp/duan/history_base.html",
            history_url=reverse(f"{admin_site.name}:projectp_duan_business_history", args=[project.pk]),
            back_url=reverse(f"{admin_site.name}:projectp_duan_change", args=[project.pk]),
        )
    return context


@login_required(login_url="projects:login")
@require_GET
@handled
def project_history(request, pk, admin_site=None):
    """GD-063. Tra cứu diễn biến và nguồn lịch sử trong quyền đọc hiện hành."""
    project, membership = _history_access(request, pk, admin_site)
    form = HistoryForm(request.GET, project=project)
    context = _history_context(request, project, membership, f"Lịch sử {project.ten_du_an}", admin_site)
    context.update(form=form, page_obj=None)
    if not project.da_luu_tru:
        from knowledge.uc04_views import _assignment_scoped_queue
        sources = _assignment_scoped_queue(request.user).filter(
            bai_viet_nguon__du_an=project,
            trang_thai__in=("cho_danh_gia", "cho_danh_gia_lai", "khong_tao_bai_hoc"),
        )
        context["knowledge_sources"] = [
            {
                "title": source.bai_viet_nguon.tieu_de or source.bai_viet_nguon.noi_dung[:100],
                "url": (
                    reverse("knowledge:review_queue") + "?status=completed"
                    if source.trang_thai == "khong_tao_bai_hoc"
                    else reverse("knowledge:normalize_lesson", kwargs={"pk": source.pk})
                ),
            }
            for source in sources
        ]
    if form.is_valid():
        readable = readable_project_posts(request.user, project)
        readable_ids = set(readable.values_list("pk", flat=True))
        posts = BaiViet.objects.filter(
            Q(du_an=project, cong_dong__isnull=True) | Q(cong_dong=project.cong_dong, du_an=project)
            | Q(cong_dong=project.cong_dong, du_an__isnull=True)
        ).exclude(loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT)
        post_ids = set(posts.values_list("pk", flat=True))
        post_devices = dict(readable.values_list("pk", "ma_the_thiet_bi_id"))
        technical_ids = set(readable.filter(che_do_xu_ly=True).values_list("pk", flat=True))
        rows = []

        def add(date, kind, label, actor, post_id=None, detail="", detail_url=None):
            if date is None:
                return
            href = (
                reverse("projects:post_detail", kwargs={"pk": pk, "post_id": post_id})
                if post_id in readable_ids
                else None
            )
            if post_id in technical_ids:
                fragment = {
                    "analysis": "analysis",
                    "solution": "solutions",
                    "trial": "trials",
                    "result": "trials",
                    "resolution": "resolution",
                }.get(kind, "issue")
                href = (
                    reverse("projects:issue", kwargs={"pk": pk, "post_id": post_id})
                    + "#"
                    + fragment
                )
            if post_id is not None and post_id not in readable_ids:
                detail = "Không có quyền mở nội dung nguồn."
                if kind == "result":
                    label = "Ghi nhận kết quả thực hiện"
            rows.append(
                {
                    "time": date,
                    "kind": kind,
                    "label": label,
                    "actor": actor,
                    "url": href,
                    "detail": detail,
                    "detail_url": detail_url,
                    "device_id": post_devices.get(post_id),
                }
            )

        add(project.ngay_tao, "management", "Khởi tạo dự án", project.nguoi_tao)
        for post in posts.select_related("nguoi_dang", "ma_the_thiet_bi", "tai_san"):
            device = post.ma_the_thiet_bi.ma_thiet_bi if post.ma_the_thiet_bi else ""
            asset = post.tai_san.ma_tai_san_noi_bo if post.tai_san else "Chưa gắn tài sản"
            add(
                post.ngay_tao,
                "post",
                (post.tieu_de or post.get_loai_bai_viet_display())
                if post.pk in readable_ids else "Đăng nội dung dự án",
                post.nguoi_dang,
                post.pk,
                f"{device} · {asset}",
            )
        for comment in BinhLuan.objects.filter(
            bai_viet_id__in=post_ids,
            bai_viet__che_do_xu_ly=True,
            da_xoa_mem=False,
        ).select_related("nguoi_dung"):
            add(
                comment.ngay_tao,
                "analysis",
                "Trao đổi phân tích",
                comment.nguoi_dung,
                comment.bai_viet_id,
                comment.noi_dung[:160],
            )
        for item in PhuongAnXuLy.objects.filter(bai_viet_id__in=post_ids).select_related(
            "nguoi_de_xuat"
        ):
            add(
                item.ngay_tao,
                "solution",
                "Đề xuất phương án",
                item.nguoi_de_xuat,
                item.bai_viet_id,
                item.noi_dung_phuong_an[:160],
            )
        for item in LanThuPhuongAn.objects.filter(
            phuong_an__bai_viet_id__in=post_ids
        ).select_related("phuong_an", "nguoi_khoi_tao", "nguoi_xac_nhan_dung"):
            add(
                item.ngay_thu,
                "trial",
                f"Tạo lần thử {item.so_lan}",
                item.nguoi_khoi_tao,
                item.phuong_an.bai_viet_id,
                f"Phương án {item.phuong_an_id}",
            )
            if item.trang_thai == "dung_thu":
                add(
                    item.ket_thuc_luc, "trial", "Dừng việc thử", item.nguoi_xac_nhan_dung,
                    item.phuong_an.bai_viet_id, item.ly_do_huy,
                )
        for item in KetQuaThu.objects.filter(
            lan_thu__phuong_an__bai_viet_id__in=post_ids
        ).select_related("lan_thu__phuong_an", "nguoi_ghi_nhan"):
            add(
                item.ngay_ghi_nhan,
                "result",
                "Kết quả thành công" if item.thanh_cong else "Kết quả chưa thành công",
                item.nguoi_ghi_nhan,
                item.lan_thu.phuong_an.bai_viet_id,
                item.mo_ta_ket_qua[:160],
            )
        for item in KetLuanXuLy.objects.filter(bai_viet_nguon_id__in=post_ids).select_related(
            "nguoi_de_nghi"
        ):
            add(
                item.ngay_xac_nhan,
                "resolution",
                "Ghi nhận kết luận xử lý",
                item.nguoi_de_nghi,
                item.bai_viet_nguon_id,
                item.noi_dung_ket_luan[:160],
            )
        # Nhật ký quản lý chỉ hiển thị tóm tắt hành động, không xuất toàn bộ snapshot dữ liệu.
        logs = NhatKyNghiepVu.objects.filter(
            Q(hanh_dong__startswith="UC-PRJ-03:") | Q(hanh_dong__startswith="UC-PRJ-11:"),
            loai_tai_nguyen="DU_AN", ma_tai_nguyen=str(pk)
        ).select_related("nguoi_dung")
        for log in logs:
            label = MANAGEMENT_LABELS.get(
                log.hanh_dong.split(":")[-1], "Cập nhật dữ liệu dự án"
            )
            add(
                log.thoi_diem,
                "management",
                label,
                log.nguoi_dung,
                detail_url=(
                    reverse(f"{admin_site.name}:projectp_duan_business_history_detail", args=[pk, log.pk])
                    if admin_site is not None else
                    reverse("projects:history_detail", kwargs={"pk": pk, "log_id": log.pk})
                ),
            )
        assignments = NhatKyNghiepVu.objects.filter(
            loai_tai_nguyen="DU_AN",
            ma_tai_nguyen=str(pk),
            hanh_dong="UC-PRJ-07:performer",
        ).select_related("nguoi_dung")
        for log in assignments:
            post_id = (
                log.du_lieu_sau.get("post_id") if isinstance(log.du_lieu_sau, dict) else None
            )
            if post_id in post_ids:
                add(
                    log.thoi_diem,
                    "trial",
                    "Xác định người thực hiện lần thử",
                    log.nguoi_dung,
                    post_id,
                )
        data = form.cleaned_data
        selected = []
        for row in rows:
            if data["ma_thiet_bi"] and row["device_id"] != data["ma_thiet_bi"].pk:
                continue
            date = timezone.localtime(row["time"]).date()
            if data["tu_ngay"] and date < data["tu_ngay"]:
                continue
            if data["den_ngay"] and date > data["den_ngay"]:
                continue
            if data["loai"] and row["kind"] != data["loai"]:
                continue
            actor = row["actor"]
            actor_name = ho_ten(actor) if actor else ""
            searchable = f'{row["label"]} {row["detail"]} {actor_name} {actor or ""}'.casefold()
            if data["q"] and data["q"].casefold() not in searchable:
                continue
            selected.append(row)
        selected.sort(key=lambda row: row["time"], reverse=True)
        context["page_obj"] = Paginator(selected, 20).get_page(request.GET.get("page"))
    return render(request, "projects/project_history.html", context)


@login_required(login_url="projects:login")
@require_GET
@handled
def history_detail(request, pk, log_id, admin_site=None):
    """GD-063 B3/B4a. Đọc thay đổi quản lý ở trạng thái lịch sử, không mở biểu mẫu sửa."""
    project, membership = _history_access(request, pk, admin_site)
    log = get_object_or_404(
        NhatKyNghiepVu.objects.filter(
            Q(hanh_dong__startswith="UC-PRJ-03:") | Q(hanh_dong__startswith="UC-PRJ-11:")
        ).select_related("nguoi_dung"),
        pk=log_id,
        loai_tai_nguyen="DU_AN",
        ma_tai_nguyen=str(pk),
    )
    title = MANAGEMENT_LABELS.get(log.hanh_dong.split(":")[-1], "Chi tiết lịch sử dự án")
    context = _history_context(request, project, membership, title, admin_site)
    context.update(log=log, changes=snapshot_changes(log, project))
    return render(request, "projects/history_detail.html", context)
