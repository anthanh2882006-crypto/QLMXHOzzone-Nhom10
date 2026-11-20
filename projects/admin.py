"""UC-PRJ-11: xem, sửa tên/mô tả và lưu trữ có kiểm tra; không tạo/xóa dự án."""

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import F
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from projectp.models import CommunityRole, DuAn, NhatKyNghiepVu, ThanhVienCongDong
from .permissions import administrable_projects, readable_projects, readable_project_posts
from .services_manage import revision, state
from .policies import archive_reasons, pending_knowledge_sources


class ProjectAdminForm(forms.ModelForm):
    revision_token = forms.CharField(widget=forms.HiddenInput)
    luu_tru = forms.BooleanField(required=False, label="Xác nhận lưu trữ dự án")

    class Meta:
        model = DuAn
        fields = ("ten_du_an", "mo_ta")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["revision_token"].initial = revision(self.instance)
            if self.instance.da_luu_tru:
                self.fields["luu_tru"].disabled = True

    def clean(self):
        data = super().clean()
        if not self.instance.pk:
            raise ValidationError("Tạo dự án qua UC-PRJ-01.")
        # Admin giữ transaction bao quanh form và save_model. Lấy khóa ghi trước
        # khi đối chiếu để các đường website/Admin dùng cùng thứ tự khóa SQLite.
        with transaction.atomic():
            DuAn.objects.filter(pk=self.instance.pk).update(ngay_cap_nhat=F("ngay_cap_nhat"))
            current = DuAn.objects.select_related("cong_dong").get(pk=self.instance.pk)
            from django.core import signing
            from .services_manage import SALT, digest

            try:
                version = signing.loads(data.get("revision_token", ""), salt=SALT, max_age=8 * 60 * 60)
            except signing.BadSignature:
                raise ValidationError("Biểu mẫu hết hiệu lực. Tải lại để đối chiếu.")
            if version.get("pk") != current.pk or version.get("hash") != digest(state(current)):
                raise ValidationError("Dữ liệu đã thay đổi. Tải lại để đối chiếu trước khi lưu.")
            if current.da_luu_tru or current.cong_dong.da_xoa_mem:
                raise ValidationError(
                    "Dự án đã lưu trữ hoặc cộng đồng liên kết không còn hợp lệ; chỉ được xem."
                )
            if not ThanhVienCongDong.objects.filter(
                cong_dong_id=current.cong_dong_id,
                vai_tro=CommunityRole.OWNER,
                trang_thai="hoat_dong",
                ket_thuc_luc__isnull=True,
                nguoi_dung__is_active=True,
            ).exists():
                raise ValidationError("Cần OWNER hoạt động của cộng đồng liên kết.")
            if data.get("luu_tru"):
                reasons = archive_reasons(current)
                if reasons:
                    raise ValidationError(reasons)
            self.current = current
        return data


@admin.register(DuAn)
class ProjectAdmin(admin.ModelAdmin):
    form = ProjectAdminForm
    change_form_template = "admin/projectp/duan/change_form.html"
    list_display = ("ma_du_an_nghiep_vu", "ten_du_an", "trang_thai", "history_link")
    search_fields = ("ma_du_an_nghiep_vu", "ten_du_an")
    list_filter = ("trang_thai",)
    readonly_fields = (
        "ma_du_an_nghiep_vu",
        "cong_dong",
        "nguoi_tao",
        "trang_thai",
        "ngay_bat_dau",
        "ngay_ket_thuc",
        "luu_tru_luc",
        "nguoi_luu_tru",
    )
    fields = (
        "ma_du_an_nghiep_vu",
        "cong_dong",
        "nguoi_tao",
        "ten_du_an",
        "mo_ta",
        "trang_thai",
        "ngay_bat_dau",
        "ngay_ket_thuc",
        "luu_tru_luc",
        "nguoi_luu_tru",
        "revision_token",
        "luu_tru",
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return (
            queryset
            if request.user.is_superuser
            else queryset.filter(pk__in=administrable_projects(request.user).values("pk"))
        )

    def get_fields(self, request, obj=None):
        if obj is not None and not self.has_change_permission(request, obj):
            return tuple(field for field in self.fields if field not in ("revision_token", "luu_tru"))
        return self.fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        return obj is None or (
            not obj.da_luu_tru
            and not obj.cong_dong.da_xoa_mem
            and (request.user.is_superuser or administrable_projects(request.user).filter(pk=obj.pk).exists())
        )

    @admin.display(description="Lịch sử theo quyền nguồn")
    def history_link(self, obj):
        return format_html('<a href="{}">Xem lịch sử</a>', reverse(f"{self.admin_site.name}:projectp_duan_business_history", args=[obj.pk]))

    def get_urls(self):
        return [
            path("<path:object_id>/business-history/",
                 self.admin_site.admin_view(self.business_history),
                 name="projectp_duan_business_history"),
            path("<path:object_id>/business-history/<int:log_id>/",
                 self.admin_site.admin_view(self.business_history_detail),
                 name="projectp_duan_business_history_detail"),
        ] + super().get_urls()

    def business_history(self, request, object_id):
        from .views_history import project_history
        return project_history(request, object_id, admin_site=self.admin_site)

    def business_history_detail(self, request, object_id, log_id):
        from .views_history import history_detail
        return history_detail(request, object_id, log_id, admin_site=self.admin_site)

    def save_model(self, request, obj, form, change):
        from projectp.admin_permissions import current_admin
        request.user = current_admin(request, "projectp.change_duan")
        if not change or not self.has_change_permission(request, form.current):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Không có quyền cập nhật dự án này.")
        before = state(form.current)
        # Không tin những trường định danh/trạng thái được gửi thêm trong POST.
        obj = form.current
        obj.ten_du_an = form.cleaned_data["ten_du_an"]
        obj.mo_ta = form.cleaned_data["mo_ta"]
        if form.cleaned_data.get("luu_tru"):
            reasons = archive_reasons(obj)
            if reasons:
                raise ValidationError(reasons)
            obj.trang_thai = DuAn.Status.ARCHIVED
            obj.luu_tru_luc, obj.nguoi_luu_tru = timezone.now(), request.user
        obj.full_clean()
        obj.save()
        NhatKyNghiepVu.objects.create(
            nguoi_dung=request.user,
            hanh_dong="UC-PRJ-11:archive" if form.cleaned_data.get("luu_tru") else "UC-PRJ-11:info",
            loai_tai_nguyen="DU_AN",
            ma_tai_nguyen=str(obj.pk),
            du_lieu_truoc=before,
            du_lieu_sau=state(obj),
        )

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = dict(extra_context or {})
        project = self.get_object(request, object_id) if object_id else None
        if project is not None and self.has_view_or_change_permission(request, project):
            visible = readable_project_posts(request.user, project)
            extra_context.update(
                archive_reasons=archive_reasons(project),
                unresolved_issues=visible.filter(
                    che_do_xu_ly=True, trang_thai_xu_ly="chua_giai_quyet"
                ),
                pending_review_sources=pending_knowledge_sources(project).filter(
                    pk__in=visible.values("pk")
                ),
                project=project,
            )
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except (DatabaseError, ValidationError):
            messages.error(request, "Chưa lưu được thay đổi. Dữ liệu cũ được giữ; tải lại để đối chiếu.")
            return redirect(request.path)
