"""UC-PRJ-08, ghi kết quả thực tế của một lần thử đã xác định người thực hiện."""

from django import forms
from .forms_common import EvidenceForm


class ResultForm(EvidenceForm):
    field_order = ["mo_ta_ket_qua", "thanh_cong", "hoan_tat_luc", "minh_chung"]
    mo_ta_ket_qua = forms.CharField(
        label="Mô tả kết quả", widget=forms.Textarea(attrs={"rows": 5})
    )
    thanh_cong = forms.TypedChoiceField(
        label="Kết quả thực hiện",
        choices=[("1", "Thành công"), ("0", "Chưa thành công")],
        widget=forms.RadioSelect,
        coerce=lambda value: value == "1",
    )
    hoan_tat_luc = forms.DateTimeField(
        label="Thời điểm hoàn tất tại hiện trường",
        required=False,
        help_text="Có thể để trống để dùng thời điểm ghi nhận kết quả.",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
