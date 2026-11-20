from pathlib import Path

from django import forms


MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
MAX_ATTACHMENTS = 5
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".txt", ".csv", ".zip",
}


def attachment_input_attributes(extensions, max_size, max_files=1):
    return {
        "accept": ",".join(sorted(extensions)),
        "data-max-bytes": max_size,
        "data-max-files": max_files,
    }


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(item, initial) for item in files]


class PostForm(forms.Form):
    request_token = forms.CharField(widget=forms.HiddenInput)
    tieu_de = forms.CharField(
        label="Tiêu đề (không bắt buộc)",
        max_length=250,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Tiêu đề bài viết (nếu cần)"}),
    )
    noi_dung = forms.CharField(
        label="Nội dung",
        max_length=20000,
        widget=forms.Textarea(attrs={
            "rows": 5,
            "placeholder": "Bạn muốn chia sẻ điều gì với đồng nghiệp?",
        }),
    )
    tep_dinh_kem = MultipleFileField(
        label="Tệp đính kèm (tối đa 5 tệp, 10 MB/tệp)",
        required=False,
        widget=MultipleFileInput(attrs=attachment_input_attributes(ALLOWED_EXTENSIONS, MAX_ATTACHMENT_SIZE, MAX_ATTACHMENTS)),
    )
    remove_attachment_ids = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=(),
        label="Gỡ tệp khỏi bài viết",
    )

    def clean_noi_dung(self):
        value = self.cleaned_data["noi_dung"].strip()
        if not value:
            raise forms.ValidationError("Nội dung bài viết không được để trống.")
        return value

    def clean_tep_dinh_kem(self):
        files = self.cleaned_data.get("tep_dinh_kem", [])
        if len(files) > MAX_ATTACHMENTS:
            raise forms.ValidationError(f"Bạn chỉ được đính kèm tối đa {MAX_ATTACHMENTS} tệp.")
        errors = []
        for uploaded in files:
            ext = Path(uploaded.name).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                errors.append(f"Tệp {uploaded.name}: định dạng chưa được hỗ trợ.")
            if uploaded.size > MAX_ATTACHMENT_SIZE:
                errors.append(f"Tệp {uploaded.name}: vượt quá 10 MB.")
        if errors:
            raise forms.ValidationError(errors)
        return files


class CommentForm(forms.Form):
    noi_dung = forms.CharField(
        label="Bình luận",
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Viết bình luận..."}),
    )
    request_token = forms.CharField(widget=forms.HiddenInput)

    def clean_noi_dung(self):
        value = self.cleaned_data["noi_dung"].strip()
        if not value:
            raise forms.ValidationError("Bình luận không được để trống.")
        return value
