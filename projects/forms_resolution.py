"""UC-PRJ-09, thành viên dự án chọn một kết quả thành công làm căn cứ kết luận."""

from django import forms
from projectp.models import KetQuaThu
from .forms_common import RequestForm


class ResultChoice(forms.ModelChoiceField):
    def label_from_instance(self, result):
        trial = result.lan_thu
        return f"PA-{trial.phuong_an_id} · Lần {trial.so_lan} · {result.mo_ta_ket_qua[:80]}"


class ResolutionForm(RequestForm):
    ket_qua = ResultChoice(label="Kết quả thành công làm căn cứ", queryset=KetQuaThu.objects.none())
    noi_dung_ket_luan = forms.CharField(
        label="Nội dung / lý do đề nghị kết luận", widget=forms.Textarea(attrs={"rows": 5})
    )

    def __init__(self, *args, post, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ket_qua"].queryset = KetQuaThu.objects.filter(
            lan_thu__phuong_an__bai_viet=post, thanh_cong=True, lan_thu__trang_thai="da_co_ket_qua"
        ).select_related("lan_thu__phuong_an")
