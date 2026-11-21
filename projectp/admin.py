"""Django Admin cho quản trị dữ liệu và kiểm duyệt theo UC-SOC-10."""

import json
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from . import models
from .admin_scopes import SOC_MODERATION_PREFIX, assigned_scopes, scope_ids


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
        from .admin_knowledge import readable_admin_versions

        knowledge = _knowledge_sources_for(request.user)
        version_ids = readable_admin_versions(request.user, knowledge["articles"]).values("pk")
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
        return _can_view_moderation(request.user) and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def has_change_permission(self, request, obj=None):
        return _can_moderate(request.user) and (
            obj is None or self.has_view_permission(request, obj)
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Không xóa cứng bài viết trong UC-SOC-10.
        return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("nguoi_dang", "cong_dong", "du_an", "nguoi_xoa")
        if not _can_view_moderation(request.user):
            return queryset.none()
        if request.user.is_superuser:
            return queryset
        scopes = assigned_scopes(request.user, SOC_MODERATION_PREFIX)
        projects = scope_ids(scopes, "du_an")
        communities = scope_ids(scopes, "cong_dong")
        scope = (
            (Q(du_an_id__in=projects) & (Q(cong_dong__isnull=True) | Q(cong_dong_id=F("du_an__cong_dong_id"))))
            | Q(du_an__isnull=True, cong_dong__loai_cong_dong=models.CongDong.Type.PROJECT,
                cong_dong__du_an_lien_ket__pk__in=projects)
            | Q(du_an__isnull=True, cong_dong_id__in=communities, cong_dong__loai_cong_dong=models.CongDong.Type.GENERAL)
        )
        if "toan_cong_ty" in scopes:
            scope |= Q(du_an__isnull=True, cong_dong__isnull=True)
        return queryset.filter(scope)

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

    @staticmethod
    def _moderation_revision(request, action, posts):
        return [request.user.pk, action, [[post.pk, post.trang_thai, post.da_xoa_mem,
                                          post.ngay_cap_nhat.isoformat()] for post in posts]]

    def _render_moderation_confirmation(
        self, request, *, action, ids, posts, error=None, reason="", status=200
    ):
        from social.permissions import moderation_block_reason

        for post in posts:
            post.moderation_protected_reason = moderation_block_reason(post, action)
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
            "revision_token": signing.dumps(
                self._moderation_revision(request, action, posts), salt="ozzone.moderation",
            ),
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
                self._apply_moderation(
                    request, action=action, ids=ids, reason=reason,
                    revision_token=request.POST.get("revision_token", ""),
                )
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

    def _apply_moderation(self, request, *, action, ids, reason, revision_token):
        from social.permissions import moderation_block_reason
        from .admin_permissions import current_admin

        with transaction.atomic():
            project_ids = models.BaiViet.objects.filter(pk__in=ids, du_an__isnull=False).values("du_an_id")
            models.DuAn.objects.filter(pk__in=project_ids).update(ngay_cap_nhat=F("ngay_cap_nhat"))
            request.user = current_admin(request, "projectp.change_baiviet")
            scoped_posts = self.get_queryset(request).filter(pk__in=ids)
            scoped_posts.update(ngay_cap_nhat=F("ngay_cap_nhat"))
            posts = list(scoped_posts.select_related(None).select_for_update().order_by("pk"))
            if len(posts) != len(ids):
                raise ValidationError("Danh sách đã thay đổi trong lúc bạn đang thao tác. Hãy tải lại.")
            try:
                reviewed = signing.loads(revision_token, salt="ozzone.moderation", max_age=60 * 60)
            except signing.BadSignature:
                reviewed = None
            if reviewed != self._moderation_revision(request, action, posts):
                raise ValidationError("Nội dung hoặc trạng thái đã thay đổi. Hãy kiểm tra lại trước khi xác nhận.")
            protected = [(self.tieu_de_ngan(post) or "Bài viết", moderation_block_reason(post, action)) for post in posts]
            protected = [(title, message) for title, message in protected if message]
            if protected:
                details = "; ".join(f"{title}: {message}" for title, message in protected)
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
                            f"“{self.tieu_de_ngan(post) or 'Bài viết'}” đã xóa mềm. Hãy dùng Khôi phục hoặc giữ nguyên trạng thái."
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


AUDIT_ACTION_LABELS = {
    "UC-ACC-05:create": "Tạo tài khoản",
    "UC-ACC-05:update": "Cập nhật tài khoản",
    "UC-ACC-05:grant_denied": "Từ chối cấp quyền",
    "UC-ACC-05:temporary_password": "Đặt mật khẩu tạm thời",
    "UC-ACC-05:disable_password": "Vô hiệu hóa mật khẩu",
    "UC-ACC-05:group_permissions": "Cập nhật nhóm quyền",
    "UC-ACC-05:employee_profile": "Cập nhật hồ sơ nhân viên",
    "UC-COM-08:create": "Tạo cộng đồng",
    "UC-COM-08:update": "Cập nhật cộng đồng",
    "UC-PRJ-01": "Tạo dự án",
    "UC-PRJ-03:info": "Cập nhật thông tin dự án",
    "UC-PRJ-03:member_add": "Thêm thành viên dự án",
    "UC-PRJ-03:member_role": "Đổi vai trò thành viên",
    "UC-PRJ-03:member_end": "Kết thúc tư cách thành viên",
    "UC-PRJ-03:equipment": "Cập nhật thiết bị và tài sản",
    "UC-PRJ-03:knowledge": "Phân công tri thức",
    "UC-PRJ-03:knowledge_end": "Kết thúc phân công tri thức",
    "UC-PRJ-03:archive": "Lưu trữ dự án",
    "UC-PRJ-11:info": "Cập nhật dữ liệu dự án",
    "UC-PRJ-11:archive": "Lưu trữ dự án từ khu vực quản trị",
    "UC-PRJ-05": "Tạo bài đăng dự án",
    "UC-PRJ-06": "Tạo cập nhật hiện trường",
    "UC-PRJ-07:analysis": "Phân tích vấn đề",
    "UC-PRJ-07:solution": "Đề xuất phương án",
    "UC-PRJ-07:trial": "Tạo lần thử",
    "UC-PRJ-07:performer": "Giao người thực hiện lần thử",
    "UC-PRJ-08": "Ghi kết quả thực hiện",
    "UC-PRJ-09": "Ghi kết luận xử lý",
    "UC-KNW-05:save": "Lưu bản nháp tri thức",
    "UC-KNW-05:clone": "Tạo bản nháp từ bản công bố",
    "UC-KNW-05:publish": "Công bố bài viết tri thức",
    "UC-KNW-06:status": "Cập nhật trạng thái tri thức",
    "tao_bai_viet_ca_nhan": "Tạo bài viết cá nhân",
    "cap_nhat_bai_viet_ca_nhan": "Cập nhật bài viết cá nhân",
    "xoa_mem_bai_viet_ca_nhan": "Xóa bài viết cá nhân",
    "tao_binh_luan_bai_viet": "Viết bình luận",
    "tham_gia_cong_dong": "Tham gia cộng đồng",
    "roi_cong_dong": "Rời cộng đồng",
    "tao_bai_cong_dong": "Tạo bài đăng cộng đồng",
    "ban_giao_chu_so_huu": "Bàn giao quyền chủ sở hữu",
    "kiem_duyet_pin": "Ghim bài trong cộng đồng",
    "kiem_duyet_unpin": "Bỏ ghim bài trong cộng đồng",
    "kiem_duyet_hide": "Ẩn bài trong cộng đồng",
    "kiem_duyet_restore": "Khôi phục bài trong cộng đồng",
    "kiem_duyet_an_bai_viet": "Ẩn bài viết",
    "kiem_duyet_khoi_phuc_bai_viet": "Khôi phục bài viết",
    "tao_ban_nhap_thong_bao_chinh_thuc": "Tạo bản nháp thông báo",
    "cap_nhat_ban_nhap_thong_bao_chinh_thuc": "Cập nhật bản nháp thông báo",
    "cong_bo_thong_bao_chinh_thuc": "Phát hành thông báo",
    "huy_ban_nhap_thong_bao_chinh_thuc": "Hủy bản nháp thông báo",
    "xac_nhan_tiep_nhan_thong_bao": "Xác nhận tiếp nhận thông báo",
    "chuan_hoa_bai_hoc_kinh_nghiem": "Chuẩn hóa bài học kinh nghiệm",
    "khong_chuyen_thanh_bai_hoc": "Không chuyển thành bài học",
    "mo_lai_danh_gia_tri_thuc": "Mở lại đánh giá tri thức",
    "configure_knowledge_editor_role": "Cấu hình nhóm biên tập tri thức",
}
AUDIT_RESOURCE_LABELS = {
    "NGUOI_DUNG": "Tài khoản",
    "NHOM_QUYEN": "Nhóm quyền",
    "DJANGO_GROUP": "Nhóm quyền Django",
    "HO_SO_NHAN_VIEN": "Hồ sơ nhân viên",
    "BAI_VIET": "Bài viết",
    "BINH_LUAN": "Bình luận",
    "CONG_DONG": "Cộng đồng",
    "THANH_VIEN_CONG_DONG": "Thành viên cộng đồng",
    "DU_AN": "Dự án",
    "THONG_BAO_CHINH_THUC": "Thông báo chính thức",
    "CHO_DANH_GIA_TRI_THUC": "Nguồn chờ đánh giá tri thức",
    "BAI_HOC_KINH_NGHIEM": "Bài học kinh nghiệm",
    "BAI_VIET_TRI_THUC": "Bài viết tri thức",
}
AUDIT_INTERNAL_FIELDS = {
    "id", "pk", "ma_yeu_cau", "ma_tai_nguyen", "request_hash", "request_token", "fingerprint",
    "ma_binh_luan_cha",
    *(model._meta.pk.name for model in models.NhatKyNghiepVu._meta.app_config.get_models()),
}


class AuditLabelFilter(admin.AllValuesFieldListFilter):
    def choices(self, changelist):
        is_action = self.field_path == "hanh_dong"
        labels = AUDIT_ACTION_LABELS if is_action else AUDIT_RESOURCE_LABELS
        fallback = "Thao tác nghiệp vụ" if is_action else "Dữ liệu nghiệp vụ"
        choices = super().choices(changelist)
        yield next(choices)
        for choice in choices:
            code, separator, count = choice["display"].partition(" (")
            yield {**choice, "display": labels.get(code, fallback) + separator + count}


def audit_display_snapshot(snapshot):
    if isinstance(snapshot, dict):
        return {
            key: audit_display_snapshot(value)
            for key, value in snapshot.items()
            if key not in AUDIT_INTERNAL_FIELDS and not key.endswith(("_id", "_ids"))
        }
    if isinstance(snapshot, list):
        return [audit_display_snapshot(value) for value in snapshot]
    return snapshot


@admin.register(models.NhatKyNghiepVu)
class NhatKyNghiepVuAdmin(admin.ModelAdmin):
    list_display = ("thoi_diem", "nguoi_dung", "action_label", "resource_label")
    list_filter = (("hanh_dong", AuditLabelFilter), ("loai_tai_nguyen", AuditLabelFilter), "thoi_diem")
    search_fields = (
        "ma_tai_nguyen",
        "hanh_dong",
        "nguoi_dung__username",
        "nguoi_dung__first_name",
        "nguoi_dung__last_name",
    )
    date_hierarchy = "thoi_diem"
    fields = readonly_fields = (
        "thoi_diem", "nguoi_dung", "action_label", "resource_label", "ly_do",
        "before_display", "after_display", "dia_chi_ip",
    )

    @admin.display(description="Hành động", ordering="hanh_dong")
    def action_label(self, obj):
        return AUDIT_ACTION_LABELS.get(obj.hanh_dong, "Thao tác nghiệp vụ")

    @admin.display(description="Đối tượng", ordering="loai_tai_nguyen")
    def resource_label(self, obj):
        return AUDIT_RESOURCE_LABELS.get(obj.loai_tai_nguyen, "Dữ liệu nghiệp vụ")

    @admin.display(description="Dữ liệu trước thay đổi")
    def before_display(self, obj):
        return self._display_snapshot(obj.du_lieu_truoc)

    @admin.display(description="Dữ liệu sau thay đổi")
    def after_display(self, obj):
        return self._display_snapshot(obj.du_lieu_sau)

    @staticmethod
    def _display_snapshot(snapshot):
        display = audit_display_snapshot(snapshot)
        return format_html("<pre>{}</pre>", json.dumps(display, ensure_ascii=False, indent=2)) if display else "—"

    def get_queryset(self, request):
        from django.db.models import Q
        from projects.permissions import administrable_projects
        from social.permissions import accessible_posts

        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        posts = [str(pk) for pk in accessible_posts(request.user).values_list("pk", flat=True)]
        may_read_projects = any(request.user.has_perm(perm) for perm in ("projectp.view_duan", "projectp.change_duan"))
        delegated_management = Q(pk__in=[])
        project_records = Q(loai_tai_nguyen="DU_AN")
        if may_read_projects:
            delegated_projects = [str(pk) for pk in administrable_projects(request.user).values_list("pk", flat=True)]
            delegated_management = project_records & Q(ma_tai_nguyen__in=delegated_projects)
        return queryset.filter(
            (Q(nguoi_dung=request.user) & ~project_records)
            | Q(loai_tai_nguyen="BAI_VIET", ma_tai_nguyen__in=posts)
            | delegated_management
        )

    def has_add_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return bool(
            request.user.is_active
            and request.user.is_staff
            and request.user.has_perm("projectp.view_nhatkynghiepvu")
        )

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from . import admin_knowledge  # noqa: F401 — đăng ký UC-KNW-06 trong khu vực Admin chung
