"""UC-PRJ-03, kiểm tra dữ liệu mỗi nhánh quản lý trước khi chuyển đến giao dịch."""

from accounts.views._chung import ho_ten
from django import forms
from django.contrib.auth import get_user_model
from projectp.models import (
    MemberStatus,
    PhanCongTriThuc,
    ProjectRole,
    ThanhVienDuAn,
)


class EmployeeChoice(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f"{ho_ten(user)} ({user.get_username()})"


class RevisionForm(forms.Form):
    revision = forms.CharField(widget=forms.HiddenInput)


class ProjectInfoForm(RevisionForm):
    ten_du_an = forms.CharField(label="Tên dự án", max_length=200)
    mo_ta = forms.CharField(label="Mô tả", required=False, widget=forms.Textarea(attrs={"rows": 4}))


class AddMemberForm(RevisionForm):
    nguoi_dung = EmployeeChoice(label="Nhân viên", queryset=get_user_model().objects.none())
    vai_tro = forms.ChoiceField(label="Vai trò tại dự án", choices=ProjectRole.choices)

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        occupied = (
            ThanhVienDuAn.objects.filter(du_an=project)
            .exclude(trang_thai=MemberStatus.ENDED)
            .values("nguoi_dung_id")
        )
        self.fields["nguoi_dung"].queryset = (
            get_user_model()
            .objects.filter(is_active=True, ho_so_nhan_vien__isnull=False)
            .exclude(pk__in=occupied)
            .order_by("first_name", "last_name", "pk")
        )


class RoleForm(RevisionForm):
    vai_tro = forms.ChoiceField(label="Vai trò tại dự án", choices=ProjectRole.choices)


class ConfirmForm(RevisionForm):
    xac_nhan = forms.BooleanField(label="Tôi xác nhận thực hiện thao tác này")


class EquipmentForm(RevisionForm):
    ma_thiet_bi = forms.CharField(label="Mã thiết bị", max_length=100)
    ten_thiet_bi = forms.CharField(label="Tên thiết bị", max_length=200)
    mo_ta = forms.CharField(label="Mô tả", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    dang_su_dung = forms.TypedChoiceField(
        label="Trạng thái thiết bị",
        choices=(("1", "Đang sử dụng"), ("0", "Ngừng sử dụng")),
        coerce=lambda value: value == "1",
    )
    tai_san_moi = forms.CharField(
        label="Mã tài sản mới",
        max_length=100,
        required=False,
        help_text="Để trống nếu giữ nguyên tài sản. Khi thay thế, nhập mã tài sản mới chưa sử dụng.",
    )
    so_serial = forms.CharField(label="Số serial tài sản mới", max_length=150, required=False)
    ngay_thay = forms.DateField(
        label="Ngày bắt đầu/thay/ngừng tài sản",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    ngung_tai_san = forms.BooleanField(
        label="Kết thúc tài sản hiện hành, không thay mới", required=False
    )

    def clean(self):
        data = super().clean()
        if data.get("ngung_tai_san") and data.get("tai_san_moi"):
            raise forms.ValidationError("Chọn thay tài sản mới hoặc kết thúc tài sản hiện hành.")
        if (data.get("tai_san_moi") or data.get("ngung_tai_san")) and not data.get("ngay_thay"):
            self.add_error("ngay_thay", "Cần ngày thay đổi tài sản.")
        if data.get("so_serial") and not data.get("tai_san_moi"):
            self.add_error("so_serial", "Chỉ nhập serial khi thêm tài sản mới.")
        return data


class KnowledgeForm(RevisionForm):
    nguoi_phu_trach = EmployeeChoice(
        label="Người được phân công", queryset=get_user_model().objects.none()
    )
    ghi_chu = forms.CharField(
        label="Căn cứ trách nhiệm / lý do phân công", widget=forms.Textarea(attrs={"rows": 3})
    )
    ban_giao = forms.BooleanField(
        label="Xác nhận thay người phụ trách hiện hành và bàn giao trách nhiệm", required=False
    )

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        ids = ThanhVienDuAn.objects.filter(
            du_an=project, trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True
        ).values("nguoi_dung_id")
        self.fields["nguoi_phu_trach"].queryset = (
            get_user_model().objects.filter(pk__in=ids, is_active=True).order_by("first_name", "pk")
        )
        current = PhanCongTriThuc.objects.filter(
            du_an=project, ket_thuc_luc__isnull=True
        ).first()
        if current:
            self.initial.setdefault("nguoi_phu_trach", current.nguoi_phu_trach_id)
