"""UC-PRJ-06, bổ sung ngữ cảnh thiết bị vào biểu mẫu tạo bài dự án."""

from django import forms
from projectp.models import BaiViet
from .forms_posts import ProjectPostForm


class FieldUpdateForm(ProjectPostForm):
    asset_context = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["noi_dung"].label = "Hiện trạng ghi nhận"
        self.fields["loai_bai_viet"].choices = [(BaiViet.Kind.FIELD_UPDATE, "Cập nhật hiện trường")]
        self.fields["loai_bai_viet"].initial = BaiViet.Kind.FIELD_UPDATE
        self.fields["loai_bai_viet"].help_text = (
            "Thiết bị và tài sản được kiểm tra lại trước khi ghi."
        )
