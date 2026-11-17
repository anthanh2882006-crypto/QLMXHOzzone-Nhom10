"""UC-07 đến UC-09. Giữ liên kết vấn đề → phương án → lần thử → kết quả → kết luận."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Max
from django.utils import timezone

from projectp.models import (
    BaiViet,
    BinhLuan,
    ChoDanhGiaTriThuc,
    KetLuanXuLy,
    KetQuaThu,
    LanThuPhuongAn,
    PhanCongTriThuc,
    PhuongAnXuLy,
)
from .permissions import (
    active_memberships,
    can_choose_trial,
    can_resolve,
    readable_project_posts,
)
from .services_common import attach_files, command, save_model


def writable_issue(user, project, post_id):
    post = readable_project_posts(user, project).filter(pk=post_id, che_do_xu_ly=True).first()
    if post is None:
        raise PermissionDenied("Nguồn xử lý không khả dụng trong dự án này.")
    if (
        post.trang_thai_xu_ly != BaiViet.TechnicalStatus.OPEN
        or KetLuanXuLy.objects.filter(bai_viet_nguon=post).exists()
    ):
        raise ValidationError("Vấn đề đã có kết luận, chỉ được xem lịch sử.")
    return post


def add_analysis(user, project, post, data):
    with command(
        user, "UC-PRJ-07:analysis", data["request_token"], data, project.pk, post.pk
    ) as task:
        if not task["replay"]:
            post = writable_issue(user, task["project"], post.pk)
            comment = save_model(
                BinhLuan(bai_viet=post, nguoi_dung=user, noi_dung=data["noi_dung"])
            )
            attach_files(user, data["minh_chung"], {"binh_luan": comment}, task["files"])
            task.update(result_id=post.pk, audit={"post_id": post.pk, "comment_id": comment.pk})
    return task["result_id"]


def propose_solution(user, project, post, data):
    with command(
        user, "UC-PRJ-07:solution", data["request_token"], data, project.pk, post.pk
    ) as task:
        if not task["replay"]:
            post = writable_issue(user, task["project"], post.pk)
            solution = save_model(
                PhuongAnXuLy(
                    bai_viet=post,
                    nguoi_de_xuat=user,
                    noi_dung_phuong_an=data["noi_dung_phuong_an"],
                    co_so_de_xuat=data["co_so_de_xuat"],
                )
            )
            attach_files(user, data["minh_chung"], {"phuong_an": solution}, task["files"])
            task.update(
                result_id=post.pk, audit={"post_id": post.pk, "solution_id": solution.pk}
            )
    return task["result_id"]


def choose_trial(user, project, solution, data, trial=None):
    action = "UC-PRJ-07:performer" if trial else "UC-PRJ-07:trial"
    target = trial.pk if trial else solution.pk
    with command(user, action, data["request_token"], data, project.pk, target) as task:
        if not can_choose_trial(user, task["project"]):
            raise PermissionDenied("Bạn cần có tư cách thành viên hợp lệ trong dự án để chọn thử hoặc xác định người thực hiện.")
        if not task["replay"]:
            post = writable_issue(user, task["project"], solution.bai_viet_id)
            solution = PhuongAnXuLy.objects.get(pk=solution.pk, bai_viet=post)
            if solution.trang_thai == "ngung_dung":
                raise ValidationError(
                    "Phương án đã ngừng dùng. Cần chọn một phương án còn hợp lệ."
                )
            performer = data["nguoi_thuc_hien"]
            if (
                performer
                and not active_memberships(performer)
                .filter(du_an=project, nguoi_dung__is_active=True)
                .exists()
            ):
                raise ValidationError("Người thực hiện không còn tư cách hợp lệ trong dự án.")
            if trial:
                trial = LanThuPhuongAn.objects.get(pk=trial.pk, phuong_an=solution)
                if trial.nguoi_thuc_hien_id or trial.trang_thai not in (
                    "cho_ket_qua",
                    "dang_thuc_hien",
                ):
                    raise ValidationError(
                        "Chỉ bổ sung người thực hiện cho lần thử đang chờ và chưa xác định."
                    )
                if performer is None:
                    raise ValidationError(
                        "Cần chọn người thực hiện để hoàn tất thông tin trách nhiệm."
                    )
                trial.nguoi_thuc_hien = performer
                save_model(trial)
            else:
                number = (solution.lan_thu.aggregate(value=Max("so_lan"))["value"] or 0) + 1
                trial = save_model(
                    LanThuPhuongAn(
                        phuong_an=solution,
                        nguoi_khoi_tao=user,
                        nguoi_thuc_hien=performer,
                        so_lan=number,
                        mo_ta_thuc_hien=data["mo_ta_thuc_hien"],
                    )
                )
                solution.trang_thai = "da_chon_thu"
                save_model(solution)
            task.update(result_id=post.pk, audit={"post_id": post.pk, "trial_id": trial.pk})
    return task["result_id"]


def record_result(user, project, trial, data):
    with command(user, "UC-PRJ-08", data["request_token"], data, project.pk, trial.pk) as task:
        if not task["replay"]:
            post = writable_issue(user, task["project"], trial.phuong_an.bai_viet_id)
            trial = LanThuPhuongAn.objects.get(pk=trial.pk, phuong_an__bai_viet=post)
            if trial.nguoi_thuc_hien_id != user.pk:
                raise PermissionDenied(
                    "Chỉ người thực hiện đã được xác định mới ghi kết quả lần thử này."
                )
            if (
                trial.trang_thai not in ("cho_ket_qua", "dang_thuc_hien")
                or KetQuaThu.objects.filter(lan_thu=trial).exists()
            ):
                raise ValidationError("Lần thử đã có kết quả hoặc không còn chờ kết quả.")
            completed = data.get("hoan_tat_luc") or timezone.now()
            if completed < trial.ngay_thu or completed > timezone.now():
                raise ValidationError(
                    "Thời điểm hoàn tất cần nằm từ thời điểm bắt đầu thử đến hiện tại."
                )
            result = save_model(
                KetQuaThu(
                    lan_thu=trial,
                    nguoi_ghi_nhan=user,
                    mo_ta_ket_qua=data["mo_ta_ket_qua"],
                    thanh_cong=data["thanh_cong"],
                    hoan_tat_luc=completed,
                )
            )
            attach_files(user, data["minh_chung"], {"ket_qua_thu": result}, task["files"])
            trial.trang_thai, trial.ket_thuc_luc = "da_co_ket_qua", completed
            save_model(trial)
            task.update(
                result_id=post.pk,
                audit={
                    "post_id": post.pk,
                    "trial_id": trial.pk,
                    "result_id_business": result.pk,
                },
            )
    return task["result_id"]


def record_resolution(user, project, post, data):
    with command(user, "UC-PRJ-09", data["request_token"], data, project.pk, post.pk) as task:
        if not can_resolve(user, task["project"]):
            raise PermissionDenied("Bạn cần có tư cách thành viên hợp lệ trong dự án để đề nghị kết luận xử lý.")
        if not task["replay"]:
            post = writable_issue(user, task["project"], post.pk)
            result = KetQuaThu.objects.filter(
                pk=data["ket_qua"].pk,
                thanh_cong=True,
                lan_thu__phuong_an__bai_viet=post,
                lan_thu__trang_thai="da_co_ket_qua",
            ).first()
            if result is None:
                raise ValidationError(
                    "Căn cứ không phải kết quả thành công hợp lệ của vấn đề này."
                )
            conclusion = save_model(
                KetLuanXuLy(
                    bai_viet_nguon=post,
                    ket_qua=result,
                    nguoi_de_nghi=user,
                    noi_dung_ket_luan=data["noi_dung_ket_luan"],
                )
            )
            post.trang_thai_xu_ly = BaiViet.TechnicalStatus.RESOLVED
            post.giai_quyet_boi, post.giai_quyet_luc = user, timezone.now()
            save_model(post)
            pending_trials = LanThuPhuongAn.objects.filter(
                phuong_an__bai_viet=post,
                trang_thai__in=("cho_ket_qua", "dang_thuc_hien"),
                ket_qua__isnull=True,
            )
            stopped_ids = list(pending_trials.values_list("pk", flat=True))
            pending_trials.update(
                trang_thai="da_huy",
                ket_thuc_luc=post.giai_quyet_luc,
                ly_do_huy="Dừng thử vì vấn đề đã được kết luận xử lý thành công.",
                ngay_cap_nhat=post.giai_quyet_luc,
            )
            # Giữ hàng chờ kể cả chưa có người phụ trách, tránh làm mất nguồn cần đánh giá.
            assignments = PhanCongTriThuc.objects.filter(
                du_an=project,
                ket_thuc_luc__isnull=True,
                ngay_phan_cong__lte=timezone.now(),
                nguoi_phu_trach__is_active=True,
            ).order_by("pk")
            valid_assignments = [
                a
                for a in assignments
                if readable_project_posts(a.nguoi_phu_trach, project)
                .filter(pk=post.pk)
                .exists()
            ]
            assignment = valid_assignments[0] if len(valid_assignments) == 1 else None
            save_model(
                ChoDanhGiaTriThuc(
                    bai_viet_nguon=post,
                    ket_luan=conclusion,
                    phan_cong=assignment,
                    ly_do_cho=(
                        ""
                        if assignment
                        else "Quản lý dự án cần giao nguồn cho một người phụ trách tri thức phù hợp."
                    ),
                )
            )
            task.update(
                result_id=post.pk,
                audit={"post_id": post.pk, "conclusion_id": conclusion.pk, "stopped_trial_ids": stopped_ids},
            )
    return task["result_id"]
