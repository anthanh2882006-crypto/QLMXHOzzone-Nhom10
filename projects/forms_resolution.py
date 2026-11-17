"""UC-PRJ-09, thành viên dự án chọn một kết quả thành công làm căn cứ kết luận."""

from django import forms
from projectp.models import KetQuaThu, LanThuPhuongAn
from .forms_common import RequestForm


class ResultChoice(forms.ModelChoiceField):
    def label_from_instance(self, result):
        trial = result.lan_thu
        return f"PA-{trial.phuong_an_id} · Lần {trial.so_lan} · {result.mo_ta_ket_qua[:80]}"


class ResolutionForm(RequestForm):
    pending_trial_ids = forms.CharField(required=False, widget=forms.HiddenInput)
    xac_nhan_dung_thu = forms.BooleanField(
        required=False, label="Tôi xác nhận ghi kết luận thành công và dừng các lần thử còn chờ bên trên"
    )
    ket_qua = ResultChoice(label="Kết quả thành công làm căn cứ", queryset=KetQuaThu.objects.none())
    noi_dung_ket_luan = forms.CharField(
        label="Nội dung / lý do đề nghị kết luận", widget=forms.Textarea(attrs={"rows": 5})
    )

    def __init__(self, *args, post, **kwargs):
        super().__init__(*args, **kwargs)
        self.post = post
        self.fields["ket_qua"].queryset = KetQuaThu.objects.filter(
            lan_thu__phuong_an__bai_viet=post, thanh_cong=True, lan_thu__trang_thai="da_co_ket_qua"
        ).select_related("lan_thu__phuong_an")
        self.refresh_pending_confirmation()

    def refresh_pending_confirmation(self):
        self.pending_trials = list(LanThuPhuongAn.objects.filter(
            phuong_an__bai_viet=self.post,
            trang_thai__in=("cho_ket_qua", "dang_thuc_hien"),
            ket_qua__isnull=True,
        ).select_related("phuong_an", "nguoi_thuc_hien").order_by("pk"))
        self.fields["xac_nhan_dung_thu"].required = bool(self.pending_trials)
        self.initial["pending_trial_ids"] = ",".join(str(trial.pk) for trial in self.pending_trials)
        if self.is_bound and self._errors:
            self.data = self.data.copy()
            self.data["pending_trial_ids"] = self.initial["pending_trial_ids"]
            self.data.pop("xac_nhan_dung_thu", None)
