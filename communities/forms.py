"""Biểu mẫu tạo bài đăng và tải tệp của phân hệ Cộng đồng."""

from pathlib import Path

from django import forms

from projectp.models import CommunityRole
from social.forms import attachment_input_attributes


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


COMMUNITY_ATTACHMENT_MAX_SIZE = 10 * 1024 * 1024
COMMUNITY_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".png", ".jpg", ".jpeg", ".zip",
}


class PostForm(forms.Form):
    tieu_de = forms.CharField(label="Tiêu đề", required=False, max_length=250)
    noi_dung = forms.CharField(label="Nội dung", widget=forms.Textarea(attrs={"rows": 7}))
    tep = forms.FileField(
        label="Tệp đính kèm",
        required=False,
        help_text="Tùy chọn. PDF, Office, ảnh, TXT/CSV hoặc ZIP; tối đa 10 MB.",
        widget=forms.ClearableFileInput(
            attrs=attachment_input_attributes(COMMUNITY_ATTACHMENT_EXTENSIONS, COMMUNITY_ATTACHMENT_MAX_SIZE)
        ),
    )

    def clean_tep(self):
        """Kiểm tra định dạng được phép và dung lượng tệp tối đa 10 MB."""
        tep = self.cleaned_data.get("tep")
        if tep:
            if Path(tep.name).suffix.lower() not in COMMUNITY_ATTACHMENT_EXTENSIONS:
                raise forms.ValidationError("Định dạng tệp không được phép.")
            if tep.size > COMMUNITY_ATTACHMENT_MAX_SIZE:
                raise forms.ValidationError("Tệp vượt quá dung lượng 10 MB.")
        return tep

    def clean_noi_dung(self):
        value = self.cleaned_data["noi_dung"].strip()
        if not value:
            raise forms.ValidationError("Nội dung bài đăng không được để trống.")
        return value
