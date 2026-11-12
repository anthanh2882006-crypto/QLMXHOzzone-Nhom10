from django import forms

from projectp.models import DuAn, ProjectRole


class ProjectSearchForm(forms.Form):
    q = forms.CharField(
        label="Tên hoặc mã dự án",
        required=False,
        max_length=100,
    )

    status = forms.ChoiceField(
        label="Trạng thái",
        required=False,
        choices=[
            ("", "Tất cả trạng thái"),
            *DuAn.Status.choices,
        ],
    )

    role = forms.ChoiceField(
        label="Vai trò của tôi",
        required=False,
        choices=[("", "Tất cả vai trò"), *ProjectRole.choices],
    )
