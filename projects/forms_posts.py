"""UC-PRJ-05, tạo bài dự án và chủ động chọn chế độ xử lý vấn đề."""

from django import forms
from projectp.models import BaiViet
from .forms_common import EvidenceForm


class ProjectPostForm(EvidenceForm):
    field_order = ["loai_bai_viet", "che_do_xu_ly", "tieu_de", "noi_dung", "minh_chung"]
    loai_bai_viet = forms.ChoiceField(
        label="Loại nội dung",
        choices=[(BaiViet.Kind.STANDARD, "Chia sẻ / trao đổi")],
        initial=BaiViet.Kind.STANDARD,
        required=False,
        help_text="Mở chi tiết thiết bị để tạo cập nhật hiện trường gắn đúng ngữ cảnh.",
    )
    tieu_de = forms.CharField(label="Tiêu đề", max_length=250, required=False)
    noi_dung = forms.CharField(label="Nội dung", widget=forms.Textarea(attrs={"rows": 6}))
    che_do_xu_ly = forms.BooleanField(label="Bật chế độ xử lý vấn đề kỹ thuật", required=False)

    def clean_loai_bai_viet(self):
        # Biểu mẫu đã mở từ phiên bản trước vẫn dùng loại mặc định của đúng lối vào.
        return self.cleaned_data["loai_bai_viet"] or self.fields["loai_bai_viet"].choices[0][0]
