"""Form của phân hệ Tài khoản — Chương 4 (Django Forms, ModelForm, clean_<trường>)."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.exceptions import ValidationError

from projectp.models import HoSoNhanVien, KyNang, PhongBan, ViTriCongViec

User = get_user_model()


# ---------------------------------------------------------------- UC-ACC-01 Đăng nhập


class LoginForm(AuthenticationForm):
    """Đăng nhập bằng tên đăng nhập; email là thông tin liên hệ theo ACC-05."""

    username = forms.CharField(
        label="Tài khoản",
        widget=forms.TextInput(attrs={"autofocus": True, "placeholder": "Tên đăng nhập"}),
    )
    password = forms.CharField(
        label="Mật khẩu",
        widget=forms.PasswordInput(attrs={"placeholder": "Mật khẩu"}),
    )

    error_messages = {
        "invalid_login": "Tài khoản hoặc mật khẩu không đúng.",
        "inactive": "Tài khoản đã bị vô hiệu hóa. Liên hệ quản trị viên để được hỗ trợ.",
    }

    def clean(self):
        username = self.cleaned_data.get("username", "").strip()
        password = self.cleaned_data.get("password")

        self.cleaned_data["username"] = username

        # Luồng B2f: tài khoản bị vô hiệu hóa phải báo riêng
        user = User.objects.filter(username=username).first()
        if user and not user.is_active and password and user.check_password(password):
            raise ValidationError(self.error_messages["inactive"], code="inactive")

        return super().clean()  # Django kiểm tra mật khẩu như bình thường


# ---------------------------------------------------------------- UC-ACC-01 (B2a) / UC-ACC-02 (B1b)


class DoiMatKhauForm(PasswordChangeForm):
    """Form đổi mật khẩu có sẵn của Django: hỏi mật khẩu hiện tại, mật khẩu mới 2 lần,
    tự kiểm tra 2 ô khớp nhau và chạy AUTH_PASSWORD_VALIDATORS trong settings."""

    error_messages = {
        "password_mismatch": "Hai mật khẩu mới không khớp.",
        "password_incorrect": "Mật khẩu hiện tại không đúng.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Mật khẩu hiện tại"
        self.fields["new_password1"].label = "Mật khẩu mới"
        self.fields["new_password2"].label = "Nhập lại mật khẩu mới"


# ---------------------------------------------------------------- UC-ACC-03 Quản lý hồ sơ cá nhân


class ProfileForm(forms.ModelForm):
    """ModelForm chỉ gồm các trường cá nhân được phép sửa.
    Phòng ban, vị trí, mã nhân viên KHÔNG có trong fields nên người dùng không sửa được."""

    last_name = forms.CharField(label="Họ và tên đệm", max_length=150)
    first_name = forms.CharField(label="Tên", max_length=150)
    ky_nang = forms.ModelMultipleChoiceField(
        label="Kỹ năng",
        queryset=KyNang.objects.order_by("ten_ky_nang"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = HoSoNhanVien
        fields = ["so_dien_thoai", "gioi_thieu", "anh_dai_dien"]
        labels = {
            "so_dien_thoai": "Điện thoại công việc",
            "gioi_thieu": "Thông tin giới thiệu",
            "anh_dai_dien": "Ảnh đại diện",
        }
        widgets = {"gioi_thieu": forms.Textarea(attrs={"rows": 4})}

    def clean_first_name(self):
        value = " ".join(self.cleaned_data["first_name"].split())  # gộp khoảng trắng thừa
        if not value:
            raise ValidationError("Tên hiển thị không được để trống.")
        return value

    def clean_last_name(self):
        return " ".join(self.cleaned_data["last_name"].split())

    def clean_so_dien_thoai(self):
        value = self.cleaned_data["so_dien_thoai"].strip()
        so_chu_so = sum(1 for ch in value if ch.isdigit())
        if value and (so_chu_so < 8 or not all(ch in "0123456789 +.-()" for ch in value)):
            raise ValidationError("Số điện thoại không hợp lệ.")
        return value

    def clean_anh_dai_dien(self):
        image = self.cleaned_data.get("anh_dai_dien")
        if image and hasattr(image, "size") and image.size > 2 * 1024 * 1024:
            raise ValidationError("Ảnh đại diện tối đa 2 MB.")
        return image


# ---------------------------------------------------------------- UC-ACC-04 Tra cứu nhân viên


class DirectorySearchForm(forms.Form):
    """Bộ lọc danh bạ. ModelChoiceField chỉ nhận giá trị có trong CSDL."""

    q = forms.CharField(label="Họ tên / chuyên môn", required=False, max_length=100)
    phong_ban = forms.ModelChoiceField(
        label="Phòng ban",
        required=False,
        empty_label="Tất cả phòng ban",
        queryset=PhongBan.objects.filter(dang_hoat_dong=True).order_by("ten_phong_ban"),
    )
    vi_tri = forms.ModelChoiceField(
        label="Vị trí",
        required=False,
        empty_label="Tất cả vị trí",
        queryset=ViTriCongViec.objects.filter(dang_hoat_dong=True).order_by("ten_vi_tri"),
    )
    ky_nang = forms.ModelChoiceField(
        label="Kỹ năng",
        required=False,
        empty_label="Tất cả kỹ năng",
        queryset=KyNang.objects.order_by("ten_ky_nang"),
    )

    def clean_q(self):
        return " ".join(self.cleaned_data["q"].split())
