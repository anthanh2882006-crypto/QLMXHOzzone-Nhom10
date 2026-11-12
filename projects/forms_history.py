"""UC-PRJ-10, kiểm tra bộ lọc lịch sử trước khi truy vấn dữ liệu được phép đọc."""

from django import forms
from projectp.models import MaThietBi


class HistoryForm(forms.Form):
    q = forms.CharField(label="Từ khóa", required=False, max_length=100)
    tu_ngay = forms.DateField(
        label="Từ ngày", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    den_ngay = forms.DateField(
        label="Đến ngày", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    loai = forms.ChoiceField(
        label="Loại hoạt động",
        required=False,
        choices=[
            ("", "Tất cả"),
            ("post", "Bài đăng / hiện trường"),
            ("analysis", "Trao đổi phân tích"),
            ("solution", "Phương án"),
            ("trial", "Lần thử"),
            ("result", "Kết quả"),
            ("resolution", "Kết luận"),
            ("management", "Quản lý dự án"),
        ],
    )

    def clean(self):
        data = super().clean()
        start, end = data.get("tu_ngay"), data.get("den_ngay")
        if start and end and start > end:
            self.add_error("den_ngay", "Ngày kết thúc cần từ ngày bắt đầu trở đi.")
        return data

    ma_thiet_bi = forms.ModelChoiceField(
        label="Thiết bị nguồn",
        required=False,
        queryset=MaThietBi.objects.none(),
        empty_label="Tất cả thiết bị",
        help_text="Lọc các hoạt động gắn với nguồn của thiết bị.",
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ma_thiet_bi"].queryset = (
            MaThietBi.objects.filter(du_an=project).order_by("ma_thiet_bi")
            if project
            else MaThietBi.objects.none()
        )
