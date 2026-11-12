from django import forms
from projects.forms_common import MultipleFiles

from projectp.models import (
    BaiViet,
    ChuDeTriThuc,
    CongDong,
    DuAn,
    NguonThamKhao,
    PhienBanTriThuc,
    TepTin,
)


class BaiVietTriThucDraftForm(forms.Form):
    """
    GD-089: Form kiểm tra dữ liệu biên tập bài viết tri thức.
    Không tạo model hoặc bảng dữ liệu mới.
    """

    request_token = forms.CharField(widget=forms.HiddenInput)
    revision_token = forms.CharField(widget=forms.HiddenInput, required=False)
    reference_id = forms.IntegerField(widget=forms.HiddenInput, required=False, min_value=1)
    minh_chung = MultipleFiles(required=False, label="Tệp đính kèm")
    remove_reference_ids = forms.TypedMultipleChoiceField(
        coerce=int, required=False, label="Gỡ nguồn khỏi bản nháp", widget=forms.CheckboxSelectMultiple
    )
    remove_attachment_ids = forms.TypedMultipleChoiceField(
        coerce=int, required=False, label="Gỡ tệp khỏi bản nháp", widget=forms.CheckboxSelectMultiple
    )
    bai_viet_nguon = forms.ModelChoiceField(
        queryset=BaiViet.objects.none(), required=False, label="Bài viết nguồn"
    )
    tep_nguon = forms.ModelChoiceField(queryset=TepTin.objects.none(), required=False, label="Tệp nguồn")

    loai_nguon = forms.ChoiceField(
        label="Loại nguồn tri thức", choices=PhienBanTriThuc._meta.get_field("loai_nguon").choices
    )

    tieu_de = forms.CharField(
        label="Tiêu đề",
        max_length=250,
        widget=forms.TextInput(attrs={"placeholder": "Nhập tiêu đề bài viết"}),
    )

    tom_tat = forms.CharField(label="Tóm tắt", widget=forms.Textarea(attrs={"rows": 3}))

    noi_dung = forms.CharField(label="Nội dung", widget=forms.Textarea(attrs={"rows": 10}))

    pham_vi_ap_dung = forms.CharField(label="Phạm vi áp dụng", widget=forms.Textarea(attrs={"rows": 3}))

    pham_vi_chia_se = forms.ChoiceField(
        label="Phạm vi chia sẻ", choices=PhienBanTriThuc._meta.get_field("pham_vi_chia_se").choices
    )

    cong_dong = forms.ModelChoiceField(label="Cộng đồng", queryset=CongDong.objects.none(), required=False)

    du_an = forms.ModelChoiceField(label="Dự án", queryset=DuAn.objects.none(), required=False)

    chu_de = forms.ModelMultipleChoiceField(
        label="Chủ đề tri thức", queryset=ChuDeTriThuc.objects.all(), required=False
    )

    # Thông tin nguồn tham khảo của phiên bản đang biên tập
    loai_tham_chieu = forms.ChoiceField(
        label="Loại tham chiếu",
        choices=NguonThamKhao._meta.get_field("loai_tham_chieu").choices,
        required=False,
    )

    tieu_de_nguon = forms.CharField(label="Tên nguồn tham khảo", max_length=250, required=False)

    tac_gia = forms.CharField(label="Tác giả nguồn", max_length=200, required=False)

    url_nguon = forms.URLField(label="Đường dẫn nguồn", required=False)

    trich_dan = forms.CharField(label="Trích dẫn", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(
        self, *args, allowed_communities=None, allowed_projects=None, user=None, version=None, **kwargs
    ):
        super().__init__(*args, **kwargs)

        # Chỉ cung cấp lựa chọn mà người biên tập được phép sử dụng.
        if allowed_communities is not None:
            self.fields["cong_dong"].queryset = allowed_communities

        if allowed_projects is not None:
            self.fields["du_an"].queryset = allowed_projects
        if user:
            from social.permissions import accessible_posts

            self.fields["bai_viet_nguon"].queryset = accessible_posts(user).filter(
                du_an__isnull=True, che_do_xu_ly=False
            )
            self.fields["tep_nguon"].queryset = TepTin.objects.filter(
                nguoi_tai_len=user, da_xoa_mem=False, trang_thai="san_sang"
            )
        if version:
            from projectp.models import DinhKem

            self.fields["remove_reference_ids"].choices = [
                (r.pk, str(r)) for r in version.nguon_tham_khao.all()
            ]
            self.fields["remove_attachment_ids"].choices = [
                (a.pk, a.tep_tin.ten_tep)
                for a in DinhKem.objects.filter(phien_ban_tri_thuc=version).select_related("tep_tin")
            ]
        self.fields["loai_tham_chieu"].choices = [("", "Giữ các nguồn đã có")] + list(
            NguonThamKhao._meta.get_field("loai_tham_chieu").choices
        )

    def clean(self):
        cleaned_data = super().clean()

        scope = cleaned_data.get("pham_vi_chia_se")
        community = cleaned_data.get("cong_dong")
        project = cleaned_data.get("du_an")

        if scope == "noi_bo" and (community or project):
            self.add_error("pham_vi_chia_se", "Phạm vi nội bộ không gắn với dự án hoặc cộng đồng.")

        elif scope == "cong_dong":
            if not community:
                self.add_error("cong_dong", "Vui lòng chọn cộng đồng.")
            if project:
                self.add_error("du_an", "Phạm vi cộng đồng không chọn dự án.")

        elif scope == "du_an" and not project:
            self.add_error("du_an", "Vui lòng chọn dự án.")

        reference_type = cleaned_data.get("loai_tham_chieu")

        if reference_type:
            if not cleaned_data.get("tieu_de_nguon"):
                self.add_error("tieu_de_nguon", "Vui lòng nhập tên nguồn tham khảo.")

            if reference_type == "url" and not cleaned_data.get("url_nguon"):
                self.add_error("url_nguon", "Nguồn đường dẫn cần có URL.")

            if reference_type == "tai_lieu" and not cleaned_data.get("trich_dan"):
                self.add_error("trich_dan", "Nguồn tài liệu cần có nội dung trích dẫn.")

            if reference_type == "bai_viet" and not cleaned_data.get("bai_viet_nguon"):
                self.add_error("bai_viet_nguon", "Chọn bài viết nguồn hợp lệ.")
            if reference_type == "tep" and not cleaned_data.get("tep_nguon"):
                self.add_error("tep_nguon", "Chọn tệp nguồn hợp lệ.")

        return cleaned_data
