"""Trường yêu cầu và minh chứng dùng chung để chống gửi lặp và kiểm tra tệp."""

from accounts.views._chung import ho_ten
from pathlib import Path
from django import forms


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFiles(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        if len(files) > 5:
            raise forms.ValidationError("Mỗi lần gửi tối đa 5 tệp minh chứng.")
        cleaned = []
        for item in files:
            file = super().clean(item, initial)
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError("Mỗi tệp tối đa 10 MB.")
            if Path(file.name).suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg", ".txt"):
                raise forms.ValidationError("Hỗ trợ PDF, PNG, JPG và TXT.")
            cleaned.append(file)
        return cleaned


class RequestForm(forms.Form):
    request_token = forms.CharField(widget=forms.HiddenInput)


class EvidenceForm(RequestForm):
    minh_chung = MultipleFiles(
        label="Minh chứng",
        required=False,
        help_text="Tối đa 5 tệp, mỗi tệp 10 MB. Hỗ trợ PDF, PNG, JPG và TXT.",
    )


class EmployeeChoice(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f"{ho_ten(user)} ({user.get_username()})"
