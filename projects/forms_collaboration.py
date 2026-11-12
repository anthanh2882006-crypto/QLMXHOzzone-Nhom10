"""UC-PRJ-07, trao đổi, đề xuất phương án và xác định người thử thực tế."""

from django import forms
from django.contrib.auth import get_user_model
from projectp.models import MemberStatus, ThanhVienDuAn
from .forms_common import EmployeeChoice, EvidenceForm, RequestForm


class AnalysisForm(EvidenceForm):
    field_order = ["noi_dung", "minh_chung"]
    noi_dung = forms.CharField(
        label="Trao đổi phân tích", widget=forms.Textarea(attrs={"rows": 4})
    )


class SolutionForm(EvidenceForm):
    field_order = ["noi_dung_phuong_an", "co_so_de_xuat", "minh_chung"]
    noi_dung_phuong_an = forms.CharField(
        label="Phương án và cách thực hiện", widget=forms.Textarea(attrs={"rows": 5})
    )
    co_so_de_xuat = forms.CharField(
        label="Cơ sở đề xuất", widget=forms.Textarea(attrs={"rows": 3})
    )


class TrialForm(RequestForm):
    nguoi_thuc_hien = EmployeeChoice(
        label="Người thực hiện",
        required=False,
        queryset=get_user_model().objects.none(),
        empty_label="Chưa xác định",
        help_text="Cần xác định người thực hiện hợp lệ trước khi ghi kết quả.",
    )
    mo_ta_thuc_hien = forms.CharField(
        label="Nội dung giao thực hiện",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, project, assign_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        if assign_only:
            self.fields["nguoi_thuc_hien"].required = True
            self.fields.pop("mo_ta_thuc_hien")
        ids = ThanhVienDuAn.objects.filter(
            du_an=project, trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True
        ).values("nguoi_dung_id")
        self.fields["nguoi_thuc_hien"].queryset = (
            get_user_model()
            .objects.filter(pk__in=ids, is_active=True)
            .order_by("first_name", "pk")
        )
