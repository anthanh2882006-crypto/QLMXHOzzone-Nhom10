"""Form của phân hệ Cộng đồng (Chương 4, Chương 6 — tải tệp)."""

from pathlib import Path

from django import forms

from projectp.models import CommunityRole


class JoinRequestForm(forms.Form):
    loi_nhan = forms.CharField(
        label="Lý do",
        required=False,
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "Ví dụ: Muốn trao đổi kinh nghiệm điều khiển và vận hành."}),
    )


class MemberFilterForm(forms.Form):
    q = forms.CharField(label="Tìm thành viên", required=False, max_length=100)
    vai_tro = forms.ChoiceField(
        label="Vai trò",
        required=False,
        choices=[("", "Tất cả vai trò")] + list(CommunityRole.choices),
    )

    def clean_q(self):
        return " ".join(self.cleaned_data["q"].split())


class PostForm(forms.Form):
    tieu_de = forms.CharField(label="Tiêu đề", required=False, max_length=250)
    noi_dung = forms.CharField(label="Nội dung", widget=forms.Textarea(attrs={"rows": 7}))
    tep = forms.FileField(
        label="Tệp đính kèm",
        required=False,
        help_text="Tùy chọn. PDF, Office, ảnh, TXT/CSV hoặc ZIP; tối đa 10 MB.",
    )

    def clean_tep(self):
        """Chỉ nhận đuôi tệp cho phép, tối đa 10 MB (Chương 4: clean_<trường>; Chương 6: tải tệp)."""
        tep = self.cleaned_data.get("tep")
        if tep:
            cho_phep = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                        ".txt", ".csv", ".png", ".jpg", ".jpeg", ".zip"}
            if Path(tep.name).suffix.lower() not in cho_phep:
                raise forms.ValidationError("Định dạng tệp không được phép.")
            if tep.size > 10 * 1024 * 1024:
                raise forms.ValidationError("Tệp vượt quá dung lượng 10 MB.")
        return tep

    def clean_noi_dung(self):
        value = self.cleaned_data["noi_dung"].strip()
        if not value:
            raise forms.ValidationError("Nội dung bài đăng không được để trống.")
        return value
