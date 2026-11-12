"""UC-PRJ-01, thu thập thông tin khởi tạo dự án và cộng đồng liên kết."""

from django import forms
from django.utils import timezone
from .forms_common import RequestForm


class ProjectCreateForm(RequestForm):
    field_order = [
        "ten_du_an",
        "ma_du_an_nghiep_vu",
        "ngay_bat_dau",
        "pham_vi_truy_cap",
        "mo_ta",
    ]
    ma_du_an_nghiep_vu = forms.CharField(label="Mã dự án", max_length=50)
    ten_du_an = forms.CharField(label="Tên dự án", max_length=200)
    mo_ta = forms.CharField(
        label="Mô tả", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    pham_vi_truy_cap = forms.ChoiceField(
        label="Phạm vi hiển thị cộng đồng liên kết",
        choices=[("thanh_vien", "Chỉ thành viên"), ("noi_bo", "Toàn công ty")],
        help_text="Phạm vi hiển thị cộng đồng không tự cấp quyền quản lý hoặc ghi dữ liệu dự án.",
    )
    ngay_bat_dau = forms.DateField(
        label="Ngày bắt đầu",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Để trống để ghi nhận ngày khởi tạo dự án.",
    )

    def clean_ngay_bat_dau(self):
        return self.cleaned_data["ngay_bat_dau"] or timezone.localdate()
