"""UC-ACC-05 Quản trị tài khoản qua Django Admin.

Tài khoản (User), nhóm và phân quyền dùng trang có sẵn của Django: /admin/auth/user/.
Ở đây tùy chỉnh trang quản lý hồ sơ nhân viên và danh mục phòng ban, vị trí, kỹ năng.
"""

from django.contrib import admin

from projectp.models import HoSoNhanVien, KyNang, KyNangNhanVien, PhongBan, ViTriCongViec
from . import admin_users  # noqa: F401 — tùy chỉnh UserAdmin của Django

@admin.register(HoSoNhanVien)
class HoSoNhanVienAdmin(admin.ModelAdmin):
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
        ("Thông tin cá nhân", {"fields": ("anh_dai_dien", "so_dien_thoai", "gioi_thieu")}),
    )

    def get_readonly_fields(self, request, obj=None):
        fields = ["nguoi_dung"] if obj else []
        if not request.user.is_superuser:
            fields.append("bat_buoc_doi_mat_khau")
        return fields

    def has_delete_permission(self, request, obj=None):
        return False

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
