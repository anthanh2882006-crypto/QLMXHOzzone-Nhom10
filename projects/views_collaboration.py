"""UC-PRJ-07, một màn chi tiết vấn đề dùng chung cho phương án, lần thử và kết quả."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from projectp.models import BaiViet, KetLuanXuLy, LanThuPhuongAn, PhuongAnXuLy
from .forms_collaboration import AnalysisForm, SolutionForm, TrialForm
from .permissions import can_choose_trial, can_resolve, project_access, readable_project_posts
from .presentation import form_page, handled, screen
from .services_common import request_token
from .services_technical import add_analysis, choose_trial, propose_solution, writable_issue
from .views_feed import attachments_for
from .ui import with_issue_state


def get_issue(user, project, post_id):
    return get_object_or_404(
        with_issue_state(readable_project_posts(user, project)).select_related(
            "nguoi_dang", "ma_the_thiet_bi", "tai_san"
        ),
        pk=post_id,
        che_do_xu_ly=True,
    )


@login_required(login_url="projects:login")
@require_GET
@handled
def issue_list(request, pk):
    """Liệt kê các vấn đề kỹ thuật được phép đọc trong đúng dự án."""
    from django.core.paginator import Paginator

    project, membership = project_access(request.user, pk)
    posts = with_issue_state(readable_project_posts(request.user, project)).filter(
        che_do_xu_ly=True
    )
    status = request.GET.get("status", "")
    if status in (BaiViet.TechnicalStatus.OPEN, BaiViet.TechnicalStatus.RESOLVED):
        posts = posts.filter(trang_thai_xu_ly=status)
    q = request.GET.get("q", "").strip()[:100]
    if q:
        from django.db.models import Q

        posts = posts.filter(Q(tieu_de__icontains=q) | Q(noi_dung__icontains=q))
    context = screen(project, membership, "Vấn đề kỹ thuật", "issues")
    context.update(
        page_obj=Paginator(posts.select_related("ma_the_thiet_bi"), 20).get_page(
            request.GET.get("page")
        ),
        q=q,
        status=status,
    )
    return render(request, "projects/issue_list.html", context)


@login_required(login_url="projects:login")
@require_GET
@handled
def issue_detail(request, pk, post_id):
    """GD-059. Ghép nguồn, trao đổi, phương án, lần thử, kết quả và kết luận."""
    project, membership = project_access(request.user, pk)
    post = get_issue(request.user, project, post_id)
    open_issue = (
        post.trang_thai_xu_ly == BaiViet.TechnicalStatus.OPEN and not project.da_luu_tru
    )
    trials = (
        LanThuPhuongAn.objects.filter(phuong_an__bai_viet=post)
        .select_related("phuong_an", "nguoi_thuc_hien", "nguoi_xac_nhan_dung", "ket_qua__nguoi_ghi_nhan")
        .order_by("-ngay_thu", "-pk")
    )
    trial_rows = []
    for trial in trials:
        result = getattr(trial, "ket_qua", None)
        trial_rows.append(
            {
                "trial": trial,
                "result": result,
                "attachments": attachments_for(ket_qua_thu=result) if result else [],
                "can_record": open_issue
                and post.nguoi_dang_id == request.user.pk
                and trial.trang_thai in ("cho_ket_qua", "dang_thuc_hien")
                and result is None,
                "can_assign": open_issue
                and trial.nguoi_thuc_hien_id != post.nguoi_dang_id
                and trial.trang_thai in ("cho_ket_qua", "dang_thuc_hien")
                and can_choose_trial(request.user, project),
            }
        )
    context = screen(project, membership, post.tieu_de or "Chi tiết xử lý vấn đề", "issues")
    context.update(
        post=post,
        attachments=attachments_for(bai_viet=post),
        open_issue=open_issue,
        comments=[
            {"comment": comment, "attachments": attachments_for(binh_luan=comment)}
            for comment in post.binhluan_set.filter(da_xoa_mem=False)
            .select_related("nguoi_dung")
            .order_by("ngay_tao", "pk")
        ],
        solutions=[
            {"solution": solution, "attachments": attachments_for(phuong_an=solution)}
            for solution in post.phuong_an.select_related("nguoi_de_xuat").order_by(
                "ngay_tao", "pk"
            )
        ],
        trials=trial_rows,
        can_choose=open_issue and can_choose_trial(request.user, project),
        can_resolve=open_issue
        and can_resolve(request.user, project)
        and any(row["result"] and row["result"].thanh_cong for row in trial_rows),
        conclusion=KetLuanXuLy.objects.filter(bai_viet_nguon=post)
        .select_related("ket_qua__lan_thu__phuong_an", "nguoi_de_nghi")
        .first(),
        queue=getattr(post, "muc_cho_tri_thuc", None),
    )
    conclusion = context["conclusion"]
    context["stopped_trial_count"] = (
        LanThuPhuongAn.objects.filter(
            ket_luan_dung=conclusion, trang_thai="dung_thu",
            phuong_an__bai_viet=post,
        ).count() if conclusion else 0
    )
    return render(request, "projects/issue_detail.html", context)


def technical_form(
    request, pk, post, form_class, action, title, save, target=None, form_kwargs=None, **extra
):
    """Các UC dùng một cách hiển thị lỗi và giữ dữ liệu nhập, mỗi URL có hàm nghiệp vụ riêng."""
    project, membership = project_access(request.user, pk, write=request.method == "GET")
    if request.method == "GET":
        writable_issue(request.user, project, post.pk)
    form = form_class(
        request.POST if request.method == "POST" else None,
        request.FILES or None,
        initial={"request_token": request_token(request.user, action, pk, target or post.pk)},
        **(form_kwargs or {})
    )
    status_code = 200
    if request.method == "POST" and form.is_valid():
        try:
            result_post_id = save(form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        except PermissionDenied as exc:
            form.add_error(None, str(exc))
            status_code = 403
        except DatabaseError:
            form.add_error(
                None,
                "Chưa hoàn tất lưu. Thay đổi dở dang được hoàn tác. Bạn có thể thử lại cùng yêu cầu.",
            )
        else:
            messages.success(request, "Đã ghi nhận thao tác.")
            fragment = {
                "UC-PRJ-07:analysis": "analysis",
                "UC-PRJ-07:solution": "solutions",
                "UC-PRJ-07:trial": "trials",
                "UC-PRJ-07:performer": "trials",
                "UC-PRJ-08": "trials",
                "UC-PRJ-09": "resolution",
            }.get(action, "issue")
            return redirect(
                reverse("projects:issue", kwargs={"pk": pk, "post_id": result_post_id})
                + "#"
                + fragment
            )
    if action == "UC-PRJ-08" and form.errors and extra.get("trial"):
        trial = extra["trial"]
        trial.refresh_from_db()
        extra["trial"] = trial
        if trial.trang_thai == "dung_thu" and readable_project_posts(request.user, project).filter(pk=post.pk).exists():
            extra["result_blocked"] = True
            for field in form.fields.values():
                field.disabled = True
    if action == "UC-PRJ-09":
        if form.errors:
            form.refresh_pending_confirmation()
        extra["pending_trials"] = form.pending_trials
    return form_page(
        request,
        form,
        title,
        reverse("projects:issue", kwargs={"pk": pk, "post_id": post.pk}),
        project,
        membership,
        section="issues",
        post=post,
        status=status_code,
        **extra
    )


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def analysis_create(request, pk, post_id):
    """UC-07. Gửi phân tích vào đúng vấn đề đang mở."""
    project, _ = project_access(request.user, pk, write=request.method == "GET")
    post = get_issue(request.user, project, post_id)
    return technical_form(
        request,
        pk,
        post,
        AnalysisForm,
        "UC-PRJ-07:analysis",
        "Trao đổi phân tích",
        lambda data: add_analysis(request.user, project, post, data),
        submit_label="Gửi trao đổi",
    )


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def solution_create(request, pk, post_id):
    """GD-060. Lưu phương án và cơ sở đề xuất, chưa tạo lần thử."""
    project, _ = project_access(request.user, pk, write=request.method == "GET")
    post = get_issue(request.user, project, post_id)
    return technical_form(
        request,
        pk,
        post,
        SolutionForm,
        "UC-PRJ-07:solution",
        "Đề xuất phương án xử lý",
        lambda data: propose_solution(request.user, project, post, data),
        submit_label="Gửi phương án",
        notice="Phương án lưu làm căn cứ đề xuất. Việc chọn thử thực hiện ở bước riêng.",
    )


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def trial_create(request, pk, target):
    """UC-07. Thành viên dự án chọn phương án để tạo một lần thử riêng."""
    project, _ = project_access(request.user, pk, write=request.method == "GET")
    if not can_choose_trial(request.user, project):
        raise PermissionDenied("Bạn cần có tư cách thành viên hợp lệ trong dự án để chọn phương án thử.")
    solution = get_object_or_404(PhuongAnXuLy, pk=target, bai_viet__du_an=project)
    post = get_issue(request.user, project, solution.bai_viet_id)
    return technical_form(
        request,
        pk,
        post,
        TrialForm,
        "UC-PRJ-07:trial",
        "Ghi nhận phương án được chọn thử",
        lambda data: choose_trial(request.user, project, solution, data),
        target=target,
        submit_label="Tạo lần thử",
        solution=solution,
        trial_performer=post.nguoi_dang,
        notice="Sau khi lưu, lần thử chờ kết quả thực tế. Hoạt động thử diễn ra ngoài hệ thống.",
    )


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def trial_assign(request, pk, target):
    """UC-07. Bổ sung người thực hiện cho lần thử còn thiếu thông tin trách nhiệm."""
    project, _ = project_access(request.user, pk, write=request.method == "GET")
    if not can_choose_trial(request.user, project):
        raise PermissionDenied("Bạn cần có tư cách thành viên hợp lệ trong dự án để xác định người thực hiện.")
    trial = get_object_or_404(
        LanThuPhuongAn.objects.select_related("phuong_an"),
        pk=target,
        phuong_an__bai_viet__du_an=project,
    )
    post = get_issue(request.user, project, trial.phuong_an.bai_viet_id)
    if request.method == "GET" and (
        trial.nguoi_thuc_hien_id == post.nguoi_dang_id
        or trial.trang_thai not in ("cho_ket_qua", "dang_thuc_hien")
    ):
        messages.info(
            request, "Lần thử đã có người thực hiện hoặc đã kết thúc. Xem thông tin hiện hành."
        )
        return redirect(
            reverse("projects:issue", kwargs={"pk": pk, "post_id": post.pk}) + "#trials"
        )
    return technical_form(
        request,
        pk,
        post,
        TrialForm,
        "UC-PRJ-07:performer",
        "Xác định người thực hiện",
        lambda data: choose_trial(request.user, project, trial.phuong_an, data, trial=trial),
        target=target,
        form_kwargs={"assign_only": True},
        submit_label="Xác nhận người đăng bài thực hiện",
        trial=trial,
        trial_performer=post.nguoi_dang,
    )
