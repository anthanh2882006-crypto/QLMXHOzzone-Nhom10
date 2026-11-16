from pathlib import Path

from django import forms
from django.contrib.auth import get_user_model

from projectp.models import CongDong, DuAn, DinhKem, PhongBan, ThongBaoChinhThuc
from social.forms import MultipleFileField


MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
MAX_ATTACHMENTS = 5
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".zip",
}


class OfficialNoticeForm(forms.Form):
    tieu_de = forms.CharField(
        label="Tiêu đề", max_length=250, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Nhập tiêu đề thông báo"}),
    )
    noi_dung = forms.CharField(
        label="Nội dung", max_length=30000,
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Nhập nội dung thông báo chính thức..."}),
    )
    che_do_doc = forms.ChoiceField(
        label="Phạm vi quyền xem",
        choices=ThongBaoChinhThuc._meta.get_field("che_do_doc").choices,
        initial="toan_cong_ty",
    )
    doc_phong_ban = forms.ModelMultipleChoiceField(
        label="Phòng ban được đọc", queryset=PhongBan.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    doc_cong_dong = forms.ModelMultipleChoiceField(
        label="Cộng đồng được đọc", queryset=CongDong.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    doc_du_an = forms.ModelMultipleChoiceField(
        label="Dự án được đọc", queryset=DuAn.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    doc_nguoi_dung = forms.ModelMultipleChoiceField(
        label="Nhân viên được đọc", queryset=get_user_model().objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    che_do_phan_phoi = forms.ChoiceField(
        label="Cấu hình người nhận",
        choices=ThongBaoChinhThuc._meta.get_field("che_do_phan_phoi").choices,
        initial="toan_cong_ty",
    )
    phan_phoi_phong_ban = forms.ModelMultipleChoiceField(
        label="Phân phối đến phòng ban", queryset=PhongBan.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    phan_phoi_cong_dong = forms.ModelMultipleChoiceField(
        label="Phân phối đến cộng đồng", queryset=CongDong.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    phan_phoi_du_an = forms.ModelMultipleChoiceField(
        label="Phân phối đến dự án", queryset=DuAn.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    phan_phoi_nguoi_dung = forms.ModelMultipleChoiceField(
        label="Phân phối đến nhân viên", queryset=get_user_model().objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    yeu_cau_xac_nhan = forms.BooleanField(
        label="Yêu cầu người nhận xác nhận đã tiếp nhận", required=False,
    )
    tep_dinh_kem = MultipleFileField(
        label="Tệp đính kèm (tối đa 5 tệp, 10 MB/tệp)", required=False,
    )
    remove_attachment_ids = forms.ModelMultipleChoiceField(
        queryset=DinhKem.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Gỡ tệp khỏi bản nháp",
    )
    thong_bao_tham_chieu = forms.ModelChoiceField(
        queryset=ThongBaoChinhThuc.objects.filter(trang_thai="da_cong_bo"),
        required=False, widget=forms.HiddenInput,
    )
    publish_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, notice=None, **kwargs):
        self.notice = notice
        super().__init__(*args, **kwargs)
        self.fields["doc_phong_ban"].queryset = PhongBan.objects.filter(dang_hoat_dong=True).order_by("ten_phong_ban")
        self.fields["phan_phoi_phong_ban"].queryset = self.fields["doc_phong_ban"].queryset
        self.fields["doc_cong_dong"].queryset = CongDong.objects.filter(da_xoa_mem=False).order_by("ten_cong_dong")
        self.fields["phan_phoi_cong_dong"].queryset = self.fields["doc_cong_dong"].queryset
        self.fields["doc_du_an"].queryset = DuAn.objects.exclude(trang_thai=DuAn.Status.ARCHIVED).order_by("ten_du_an")
        self.fields["phan_phoi_du_an"].queryset = self.fields["doc_du_an"].queryset
        user_qs = get_user_model().objects.filter(
            is_active=True, ho_so_nhan_vien__isnull=False
        ).order_by("last_name", "first_name", "username")
        self.fields["doc_nguoi_dung"].queryset = user_qs
        self.fields["phan_phoi_nguoi_dung"].queryset = user_qs
        if notice:
            self.fields["remove_attachment_ids"].queryset = DinhKem.objects.filter(bai_viet=notice.bai_viet).select_related("tep_tin")

    def clean_noi_dung(self):
        value = self.cleaned_data["noi_dung"].strip()
        if not value:
            raise forms.ValidationError("Nội dung thông báo không được để trống.")
        return value

    def clean_tieu_de(self):
        return (self.cleaned_data.get("tieu_de") or "").strip()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("che_do_doc") == "theo_tieu_chi":
            if not any(cleaned.get(name) for name in ("doc_phong_ban", "doc_cong_dong", "doc_du_an", "doc_nguoi_dung")):
                self.add_error("che_do_doc", "Chọn ít nhất một tiêu chí quyền đọc.")
        if cleaned.get("che_do_phan_phoi") == "theo_tieu_chi":
            if not any(cleaned.get(name) for name in ("phan_phoi_phong_ban", "phan_phoi_cong_dong", "phan_phoi_du_an", "phan_phoi_nguoi_dung")):
                self.add_error("che_do_phan_phoi", "Chọn ít nhất một nhóm người nhận.")
        if cleaned.get("che_do_doc") == "theo_tieu_chi" and cleaned.get("che_do_phan_phoi") == "toan_cong_ty":
            self.add_error("che_do_phan_phoi", "Không thể phân phối toàn công ty khi quyền đọc chỉ giới hạn theo tiêu chí.")
        files = cleaned.get("tep_dinh_kem", [])
        if len(files) > MAX_ATTACHMENTS:
            self.add_error("tep_dinh_kem", f"Tối đa {MAX_ATTACHMENTS} tệp cho mỗi thông báo.")
        errors = []
        for uploaded in files:
            ext = Path(uploaded.name).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                errors.append(f"{uploaded.name}: định dạng chưa được hỗ trợ.")
            if uploaded.size > MAX_ATTACHMENT_SIZE:
                errors.append(f"{uploaded.name}: vượt quá 10 MB.")
        if errors:
            self.add_error("tep_dinh_kem", forms.ValidationError(errors))
        return cleaned


def initial_from_notice(notice, publish_key):
    criteria = list(notice.tieu_chi.select_related("phong_ban", "cong_dong", "du_an", "nguoi_dung"))
    initial = {
        "tieu_de": notice.bai_viet.tieu_de,
        "noi_dung": notice.bai_viet.noi_dung,
        "che_do_doc": notice.che_do_doc,
        "che_do_phan_phoi": notice.che_do_phan_phoi,
        "yeu_cau_xac_nhan": notice.yeu_cau_xac_nhan,
        "publish_key": publish_key,
        "thong_bao_tham_chieu": notice.thong_bao_tham_chieu_id,
    }
    mapping = {
        ("doc", "phong_ban"): "doc_phong_ban",
        ("doc", "cong_dong"): "doc_cong_dong",
        ("doc", "du_an"): "doc_du_an",
        ("doc", "nguoi_dung"): "doc_nguoi_dung",
        ("phan_phoi", "phong_ban"): "phan_phoi_phong_ban",
        ("phan_phoi", "cong_dong"): "phan_phoi_cong_dong",
        ("phan_phoi", "du_an"): "phan_phoi_du_an",
        ("phan_phoi", "nguoi_dung"): "phan_phoi_nguoi_dung",
    }
    for criterion in criteria:
        field = mapping.get((criterion.muc_dich, criterion.loai_tieu_chi))
        if field:
            initial.setdefault(field, []).append(getattr(criterion, f"{criterion.loai_tieu_chi}_id"))
    return initial
