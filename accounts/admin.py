"""UC-ACC-05 Quản trị tài khoản qua Django Admin.

Tài khoản (User), nhóm và phân quyền dùng trang có sẵn của Django: /admin/auth/user/.
Ở đây tùy chỉnh trang quản lý hồ sơ nhân viên và danh mục phòng ban, vị trí, kỹ năng.
"""

from django import forms
from django.contrib import admin, messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.models import F
from django.shortcuts import redirect

from projectp.models import HoSoNhanVien, KyNang, KyNangNhanVien, NhatKyNghiepVu, PhongBan, ViTriCongViec
from . import admin_users  # noqa: F401 — tùy chỉnh UserAdmin của Django

class EmployeeProfileAdminForm(forms.ModelForm):
    revision_token = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "revision_token" in self.fields:
            self.fields["revision_token"].initial = signing.dumps(
                [self.instance.pk, self.instance.ngay_cap_nhat.isoformat()], salt="accounts.employee_profile",
            )

    def clean(self):
        data = super().clean()
        if not self.instance.pk:
            return data
        current = HoSoNhanVien.objects.filter(pk=self.instance.pk)
        current.update(ngay_cap_nhat=F("ngay_cap_nhat"))
        try:
            reviewed = signing.loads(data.get("revision_token") or "", salt="accounts.employee_profile", max_age=28800)
        except signing.BadSignature:
            reviewed = None
        timestamp = current.values_list("ngay_cap_nhat", flat=True).get()
        if reviewed != [self.instance.pk, timestamp.isoformat()]:
            raise ValidationError("Hồ sơ đã thay đổi. Hãy tải lại trước khi lưu.")
        return data


@admin.register(HoSoNhanVien)
class HoSoNhanVienAdmin(admin.ModelAdmin):
    form = EmployeeProfileAdminForm
    list_display = (
        "ma_nhan_vien",
        "ho_ten",
        "phong_ban",
        "vi_tri",
        "dang_hoat_dong",
        "bat_buoc_doi_mat_khau",
    )
    list_filter = ("phong_ban", "vi_tri", "bat_buoc_doi_mat_khau")
    search_fields = (
        "ma_nhan_vien",
        "nguoi_dung__username",
        "nguoi_dung__first_name",
        "nguoi_dung__last_name",
    )
    fieldsets = (
        ("Tài khoản", {"fields": ("nguoi_dung", "ma_nhan_vien", "bat_buoc_doi_mat_khau")}),
        ("Tổ chức", {"fields": ("phong_ban", "vi_tri")}),
        ("Thông tin cá nhân", {"fields": ("anh_dai_dien", "so_dien_thoai", "gioi_thieu", "revision_token")}),
    )

    def get_readonly_fields(self, request, obj=None):
        fields = ["nguoi_dung"] if obj else []
        if not request.user.is_superuser:
            fields.append("bat_buoc_doi_mat_khau")
        return fields

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except DatabaseError:
            messages.error(request, "Chưa lưu được hồ sơ. Dữ liệu cũ được giữ, vui lòng thử lại.")
            return redirect(request.path)

    def save_model(self, request, obj, form, change):
        from projectp.admin_permissions import current_admin

        actor = current_admin(
            request, "projectp.change_hosonhanvien" if change else "projectp.add_hosonhanvien",
        )
        if change and not actor.is_superuser:
            obj.bat_buoc_doi_mat_khau = HoSoNhanVien.objects.values_list(
                "bat_buoc_doi_mat_khau", flat=True,
            ).get(pk=obj.pk)
        fields = ("nguoi_dung_id", "ma_nhan_vien", "phong_ban_id", "vi_tri_id", "bat_buoc_doi_mat_khau")
        before = HoSoNhanVien.objects.filter(pk=obj.pk).values(*fields).first() if change else None
        super().save_model(request, obj, form, change)
        NhatKyNghiepVu.objects.create(
            nguoi_dung=actor, hanh_dong="UC-ACC-05:employee_profile",
            loai_tai_nguyen="HO_SO_NHAN_VIEN", ma_tai_nguyen=str(obj.pk),
            du_lieu_truoc=before, du_lieu_sau={name: getattr(obj, name) for name in fields},
        )

    @admin.display(description="Họ tên")
    def ho_ten(self, obj):
        return f"{obj.nguoi_dung.last_name} {obj.nguoi_dung.first_name}"

    @admin.display(description="Hoạt động", boolean=True)
    def dang_hoat_dong(self, obj):
        return obj.nguoi_dung.is_active


@admin.register(PhongBan)
class PhongBanAdmin(admin.ModelAdmin):
    list_display = ("ma_nghiep_vu", "ten_phong_ban", "dang_hoat_dong")
    list_filter = ("dang_hoat_dong",)
    search_fields = ("ma_nghiep_vu", "ten_phong_ban")


@admin.register(ViTriCongViec)
class ViTriCongViecAdmin(admin.ModelAdmin):
    list_display = ("ma_nghiep_vu", "ten_vi_tri", "dang_hoat_dong")
    list_filter = ("dang_hoat_dong",)
    search_fields = ("ma_nghiep_vu", "ten_vi_tri")


@admin.register(KyNang)
class KyNangAdmin(admin.ModelAdmin):
    list_display = ("ten_ky_nang", "mo_ta")
    search_fields = ("ten_ky_nang",)


@admin.register(KyNangNhanVien)
class KyNangNhanVienAdmin(admin.ModelAdmin):
    list_display = ("ho_so", "ky_nang")
    list_filter = ("ky_nang",)
    search_fields = ("ho_so__ma_nhan_vien", "ky_nang__ten_ky_nang")
