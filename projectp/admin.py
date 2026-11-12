"""Django Admin cho quản trị dữ liệu và kiểm duyệt theo UC-SOC-10."""

from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone

from . import models


def _can_view_moderation(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
        and (
            user.is_superuser
            or user.has_perm("projectp.view_baiviet")
            or user.has_perm("projectp.change_baiviet")
        )
    )


def _can_moderate(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
        and (user.is_superuser or user.has_perm("projectp.change_baiviet"))
    )


BUSINESS_MODELS = [
    # Tài khoản và Cộng đồng đăng ký tám model này trong admin.py của từng app.
    models.ThanhVienDuAn,
    models.MaThietBi,
    models.TaiSanThietBi,
    models.PhanCongTriThuc,
    models.BinhLuan,
    models.CamXuc,
    models.BaiVietDaLuu,
    models.ThongBaoChinhThuc,
    models.TieuChiThongBao,
    models.NguoiNhanThongBao,
    models.PhuongAnXuLy,
    models.LanThuPhuongAn,
    models.KetQuaThu,
    models.KetLuanXuLy,
    models.ChoDanhGiaTriThuc,
    models.TepTin,
    models.DinhKem,
    models.ThongBaoHeThong,
]


class WorkflowReadOnlyAdmin(admin.ModelAdmin):
    """Nguồn và chứng cứ được ghi qua use case nghiệp vụ, không qua CRUD tự do."""

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def get_queryset(self, request):
        from social.permissions import accessible_posts
        from projects.permissions import readable_projects

        queryset = super().get_queryset(request)
        posts = accessible_posts(request.user).values("pk")
        projects = readable_projects(request.user).values("pk")
        scope = {
            models.ThanhVienDuAn: "du_an_id",
            models.MaThietBi: "du_an_id",
            models.TaiSanThietBi: "ma_the_thiet_bi__du_an_id",
            models.PhanCongTriThuc: "du_an_id",
        }
        source = {
            models.BinhLuan: "bai_viet_id",
            models.CamXuc: "bai_viet_id",
            models.BaiVietDaLuu: "bai_viet_id",
            models.PhuongAnXuLy: "bai_viet_id",
            models.LanThuPhuongAn: "phuong_an__bai_viet_id",
            models.KetQuaThu: "lan_thu__phuong_an__bai_viet_id",
            models.KetLuanXuLy: "bai_viet_nguon_id",
            models.ChoDanhGiaTriThuc: "bai_viet_nguon_id",
        }
        if self.model in scope:
            return queryset.filter(**{scope[self.model] + "__in": projects})
        if self.model in source:
            return queryset.filter(**{source[self.model] + "__in": posts})
        from knowledge.views import _knowledge_sources_for

        knowledge = _knowledge_sources_for(request.user)
        version_ids = models.PhienBanTriThuc.objects.filter(
            Q(bai_viet_tri_thuc_id__in=knowledge["articles"].values("pk")) | Q(nguoi_bien_tap=request.user)
        ).values("pk")
        if self.model is models.PhienBanTriThuc:
            return queryset.filter(pk__in=version_ids)
        if self.model in (models.NguonThamKhao, models.GanChuDePhienBan):
            return queryset.filter(phien_ban_id__in=version_ids)
        if self.model is models.ThongBaoHeThong:
            return queryset.filter(nguoi_nhan=request.user)
        if self.model is models.NguoiNhanThongBao:
            return queryset.filter(nguoi_dung=request.user)
        if self.model in (models.ThongBaoChinhThuc, models.TieuChiThongBao):
            from notifications.views import _published_notices_for

            notices = _published_notices_for(request.user)
            ids = [notice.pk for notice in notices if notice.can_read_for_request_user]
            return (
                queryset.filter(pk__in=ids)
                if self.model is models.ThongBaoChinhThuc
                else queryset.filter(thong_bao_id__in=ids)
            )
        if self.model in (models.TepTin, models.DinhKem):
            attachments = models.DinhKem.objects.filter(
                Q(bai_viet_id__in=posts)
                | Q(binh_luan__bai_viet_id__in=posts)
                | Q(ket_qua_thu__lan_thu__phuong_an__bai_viet_id__in=posts)
                | Q(phuong_an__bai_viet_id__in=posts)
                | Q(bai_hoc_id__in=knowledge["lessons"].values("pk"))
                | Q(phien_ban_tri_thuc_id__in=version_ids)
            )
            if self.model is models.DinhKem:
                return queryset.filter(pk__in=attachments.values("pk"))
            return queryset.filter(Q(nguoi_tai_len=request.user) | Q(pk__in=attachments.values("tep_tin_id")))
        return queryset


WORKFLOW_MODELS = {
    models.ThanhVienDuAn,
    models.MaThietBi,
    models.TaiSanThietBi,
    models.PhanCongTriThuc,
    models.BinhLuan,
    models.CamXuc,
    models.BaiVietDaLuu,
    models.PhuongAnXuLy,
    models.LanThuPhuongAn,
    models.KetQuaThu,
    models.KetLuanXuLy,
    models.ChoDanhGiaTriThuc,
    models.ThongBaoChinhThuc,
    models.TieuChiThongBao,
    models.NguoiNhanThongBao,
    models.TepTin,
    models.DinhKem,
    models.ThongBaoHeThong,
}
for business_model in BUSINESS_MODELS:
    admin.site.register(
        business_model, WorkflowReadOnlyAdmin if business_model in WORKFLOW_MODELS else admin.ModelAdmin
    )


@admin.register(models.BaiViet)
class BaiVietModerationAdmin(admin.ModelAdmin):
    """Read-only admin list with explicit hide/restore confirmation and audit."""

    list_display = (
        "ma_bai_viet",
        "tieu_de_ngan",
        "nguoi_dang",
        "pham_vi_hien_thi",
        "get_loai_bai_viet_display",
        "trang_thai_hien_thi",
        "ngay_tao",
    )
    list_display_links = ("ma_bai_viet",)
    list_filter = ("loai_bai_viet", "trang_thai", "da_xoa_mem", "ngay_tao")
    search_fields = (
        "tieu_de",
        "noi_dung",
        "nguoi_dang__username",
        "nguoi_dang__first_name",
        "nguoi_dang__last_name",
        "cong_dong__ten_cong_dong",
        "du_an__ten_du_an",
    )
    date_hierarchy = "ngay_tao"
    ordering = ("-ngay_tao", "-ma_bai_viet")
    actions = ("request_hide_selected", "request_restore_selected")
    actions_on_top = True
    actions_on_bottom = False

    def has_module_permission(self, request):
        return _can_view_moderation(request.user)

    def has_view_permission(self, request, obj=None):
        return _can_view_moderation(request.user)

    def has_change_permission(self, request, obj=None):
        return _can_moderate(request.user)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Không xóa cứng bài viết trong UC-SOC-10.
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("nguoi_dang", "cong_dong", "du_an", "nguoi_xoa")

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST":
            raise PermissionDenied(
                "Bài viết chỉ được xem tại Admin; hãy dùng hành động kiểm duyệt có xác nhận."
            )
        return super().changeform_view(request, object_id, form_url, extra_context)

    @admin.display(description="Nội dung")
    def tieu_de_ngan(self, obj):
        return obj.tieu_de or (obj.noi_dung or "").replace("\n", " ")[:90]

    @admin.display(description="Ngữ cảnh")
    def pham_vi_hien_thi(self, obj):
        if obj.du_an_id:
            return f"Dự án · {obj.du_an.ten_du_an}"
        if obj.cong_dong_id:
            return f"Cộng đồng · {obj.cong_dong.ten_cong_dong}"
        return "Cấp công ty"

    @admin.display(description="Trạng thái kiểm duyệt")
    def trang_thai_hien_thi(self, obj):
        if obj.da_xoa_mem:
            return "Đã xóa mềm"
        return "Hiển thị" if obj.trang_thai == "hien" else "Đã ẩn"

    def _redirect_to_confirmation(self, request, queryset, action):
        ids = list(queryset.order_by("pk").values_list("pk", flat=True))
        if not ids:
            self.message_user(request, "Bạn chưa chọn nội dung cần kiểm duyệt.", level=messages.WARNING)
            return HttpResponseRedirect(reverse("admin:projectp_baiviet_changelist"))
        url = reverse("admin:projectp_baiviet_moderation_confirm")
        return HttpResponseRedirect(f"{url}?{urlencode({'action': action, 'ids': ','.join(map(str, ids))})}")

    @admin.action(description="Ẩn nội dung đã chọn", permissions=["change"])
    def request_hide_selected(self, request, queryset):
        return self._redirect_to_confirmation(request, queryset, "hide")

    @admin.action(description="Khôi phục nội dung đã chọn", permissions=["change"])
    def request_restore_selected(self, request, queryset):
        return self._redirect_to_confirmation(request, queryset, "restore")

    def get_urls(self):
        custom = [
            path(
                "moderation-confirm/",
                self.admin_site.admin_view(self.moderation_confirmation_view),
                name="projectp_baiviet_moderation_confirm",
            ),
        ]
        return custom + super().get_urls()

    def _parse_selection(self, request):
        raw_ids = (
            request.POST.getlist("post_ids")
            if request.method == "POST"
            else request.GET.get("ids", "").split(",")
        )
        try:
            ids = sorted({int(value) for value in raw_ids if str(value).strip()})
        except (TypeError, ValueError):
            raise ValidationError("Danh sách nội dung được chọn không hợp lệ.")
        if not ids:
            raise ValidationError("Bạn chưa chọn nội dung cần kiểm duyệt.")
        posts = list(self.get_queryset(request).filter(pk__in=ids).order_by("pk"))
        if len(posts) != len(ids):
            raise ValidationError(
                "Một hoặc nhiều nội dung đã bị xóa hoặc không còn trong phạm vi quản trị. Hãy tải lại danh sách."
            )
        return ids, posts

    def _render_moderation_confirmation(
        self, request, *, action, ids, posts, error=None, reason="", status=200
    ):
        from social.permissions import protected_source_reason

        for post in posts:
            post.moderation_protected_reason = protected_source_reason(post)
            post.moderation_state = (
                "Đã xóa mềm" if post.da_xoa_mem else ("Đã ẩn" if post.trang_thai == "an" else "Hiển thị")
            )
        context = {
            **self.admin_site.each_context(request),
            "title": "Xác nhận kiểm duyệt nội dung",
            "opts": self.model._meta,
            "action": action,
            "action_label": "Ẩn nội dung" if action == "hide" else "Khôi phục nội dung",
            "posts": posts,
            "ids": ids,
            "error": error,
            "reason": reason,
            "changelist_url": reverse("admin:projectp_baiviet_changelist"),
            "can_confirm": all(not post.moderation_protected_reason for post in posts),
            "requires_reason": action == "hide",
        }
        return render(request, "admin/projectp/baiviet/moderation_confirm.html", context, status=status)

    def moderation_confirmation_view(self, request):
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        if not _can_moderate(request.user):
            raise PermissionDenied("Bạn không có quyền kiểm duyệt nội dung toàn hệ thống.")
        action = request.POST.get("action") if request.method == "POST" else request.GET.get("action")
        if action not in {"hide", "restore"}:
            raise PermissionDenied("Hành động kiểm duyệt không hợp lệ.")

        try:
            ids, posts = self._parse_selection(request)
        except ValidationError as exc:
            self.message_user(request, " ".join(exc.messages), level=messages.ERROR)
            return redirect("admin:projectp_baiviet_changelist")

        reason = (request.POST.get("reason") or "").strip()[:2000] if request.method == "POST" else ""
        if request.method == "POST":
            if action == "hide" and not reason:
                return self._render_moderation_confirmation(
                    request,
                    action=action,
                    ids=ids,
                    posts=posts,
                    error="Vui lòng nhập lý do khi ẩn nội dung.",
                    status=400,
                )
            try:
                self._apply_moderation(request, action=action, ids=ids, reason=reason)
            except (ValidationError, DatabaseError) as exc:
                if isinstance(exc, ValidationError):
                    error = " ".join(exc.messages)
                else:
                    error = "Không thể lưu thao tác kiểm duyệt. Trạng thái cũ được giữ nguyên; vui lòng tải lại và thử lại."
                return self._render_moderation_confirmation(
                    request,
                    action=action,
                    ids=ids,
                    posts=posts,
                    error=error,
                    reason=reason,
                    status=503 if isinstance(exc, DatabaseError) else 400,
                )
            verb = "đã được ẩn" if action == "hide" else "đã được khôi phục"
            self.message_user(
                request,
                f"{len(ids)} nội dung {verb}. Nhật ký kiểm duyệt đã được ghi.",
                level=messages.SUCCESS,
            )
            return redirect("admin:projectp_baiviet_changelist")

        return self._render_moderation_confirmation(request, action=action, ids=ids, posts=posts)

    def _apply_moderation(self, request, *, action, ids, reason):
        from social.permissions import protected_source_reason
        from django.db.models import F
        from .admin_permissions import current_admin

        with transaction.atomic():
            project_ids = models.BaiViet.objects.filter(pk__in=ids, du_an__isnull=False).values("du_an_id")
            models.DuAn.objects.filter(pk__in=project_ids).update(ngay_cap_nhat=F("ngay_cap_nhat"))
            request.user = current_admin(request, "projectp.change_baiviet")
            posts = list(models.BaiViet.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
            if len(posts) != len(ids):
                raise ValidationError("Danh sách đã thay đổi trong lúc bạn đang thao tác. Hãy tải lại.")
            protected = [(post.pk, protected_source_reason(post)) for post in posts]
            protected = [(pk, message) for pk, message in protected if message]
            if protected:
                details = "; ".join(f"#{pk}: {message}" for pk, message in protected)
                raise ValidationError(
                    f"Không thể kiểm duyệt nội dung là nguồn nghiệp vụ được bảo vệ. {details}"
                )

            now = timezone.now()
            for post in posts:
                before = {
                    "trang_thai": post.trang_thai,
                    "da_xoa_mem": post.da_xoa_mem,
                    "ngay_xoa": post.ngay_xoa.isoformat() if post.ngay_xoa else None,
                    "nguoi_xoa_id": post.nguoi_xoa_id,
                }
                if action == "hide":
                    if post.da_xoa_mem:
                        raise ValidationError(
                            f"Bài viết #{post.pk} đã xóa mềm; hãy dùng Khôi phục hoặc giữ nguyên trạng thái."
                        )
                    if post.trang_thai == "an":
                        continue
                    post.trang_thai = "an"
                    post.save(update_fields=["trang_thai", "ngay_cap_nhat"])
                    action_code = "kiem_duyet_an_bai_viet"
                else:
                    if not post.da_xoa_mem and post.trang_thai == "hien":
                        continue
                    post.trang_thai = "hien"
                    post.da_xoa_mem = False
                    post.ngay_xoa = None
                    post.nguoi_xoa = None
                    post.full_clean()
                    post.save(
                        update_fields=["trang_thai", "da_xoa_mem", "ngay_xoa", "nguoi_xoa", "ngay_cap_nhat"]
                    )
                    action_code = "kiem_duyet_khoi_phuc_bai_viet"
                after = {
                    "trang_thai": post.trang_thai,
                    "da_xoa_mem": post.da_xoa_mem,
                    "ngay_xoa": post.ngay_xoa.isoformat() if post.ngay_xoa else None,
                    "nguoi_xoa_id": post.nguoi_xoa_id,
                }
                models.NhatKyNghiepVu.objects.create(
                    nguoi_dung=request.user,
                    hanh_dong=action_code,
                    loai_tai_nguyen="BAI_VIET",
                    ma_tai_nguyen=str(post.pk),
                    du_lieu_truoc=before,
                    du_lieu_sau=after,
                    ly_do=reason,
                    dia_chi_ip=request.META.get("REMOTE_ADDR"),
                    thoi_diem=now,
                )


@admin.register(models.NhatKyNghiepVu)
class NhatKyNghiepVuAdmin(admin.ModelAdmin):
    list_display = ("ma_nhat_ky", "thoi_diem", "nguoi_dung", "hanh_dong", "loai_tai_nguyen", "ma_tai_nguyen")
    list_filter = ("hanh_dong", "loai_tai_nguyen", "thoi_diem")
    search_fields = (
        "ma_tai_nguyen",
        "hanh_dong",
        "nguoi_dung__username",
        "nguoi_dung__first_name",
        "nguoi_dung__last_name",
    )
    date_hierarchy = "thoi_diem"
    readonly_fields = tuple(f.name for f in models.NhatKyNghiepVu._meta.fields)

    def get_queryset(self, request):
        from django.db.models import Q
        from projects.permissions import readable_projects
        from social.permissions import accessible_posts

        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        projects = [str(pk) for pk in readable_projects(request.user).values_list("pk", flat=True)]
        posts = [str(pk) for pk in accessible_posts(request.user).values_list("pk", flat=True)]
        return queryset.filter(
            Q(nguoi_dung=request.user)
            | Q(loai_tai_nguyen="DU_AN", ma_tai_nguyen__in=projects)
            | Q(loai_tai_nguyen="BAI_VIET", ma_tai_nguyen__in=posts)
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(
            request.user.is_active
            and request.user.is_staff
            and request.user.has_perm("projectp.view_nhatkynghiepvu")
        )

    def has_delete_permission(self, request, obj=None):
        return False


from . import admin_knowledge  # noqa: F401 — đăng ký UC-KNW-06 trong khu vực Admin chung
