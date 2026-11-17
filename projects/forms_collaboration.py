"""UC-PRJ-07, trao đổi, đề xuất phương án và xác định người thử thực tế."""

from django import forms
from .forms_common import EvidenceForm, RequestForm


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
    mo_ta_thuc_hien = forms.CharField(
        label="Nội dung thực hiện",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, assign_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        if assign_only:
            self.fields.pop("mo_ta_thuc_hien")
