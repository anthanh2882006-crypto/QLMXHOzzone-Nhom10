/* UC-PRJ-06. Giữ bản nhập trên trang khi người dùng chọn tiếp tục soạn. */
document.addEventListener("DOMContentLoaded", function () {
    const form = document.querySelector("form[data-confirm-leave]");
    const dialog = document.getElementById("leave-dialog");
    if (!form || !dialog) return;

    // Biểu mẫu trả về sau lỗi vẫn chứa bản nhập chưa lưu của người dùng.
    let dirty = form.dataset.dirty === "true";
    let submitting = false;
    let destination = null;

    form.addEventListener("input", function () { dirty = true; });
    form.addEventListener("change", function () { dirty = true; });
    form.addEventListener("submit", function () { submitting = true; });

    document.querySelectorAll("a[href]").forEach(function (link) {
        link.addEventListener("click", function (event) {
            if (!dirty || submitting || event.ctrlKey || event.metaKey || event.shiftKey) return;
            if (link.getAttribute("href").startsWith("#")) return;
            event.preventDefault();
            destination = link.href;
            dialog.showModal();
        });
    });

    dialog.querySelector("[data-continue-edit]").addEventListener("click", function () {
        dialog.close();
        destination = null;
    });
    dialog.querySelector("[data-leave-page]").addEventListener("click", function () {
        dirty = false;
        window.location.assign(destination);
    });
    window.addEventListener("beforeunload", function (event) {
        if (dirty && !submitting) {
            event.preventDefault();
            event.returnValue = "";
        }
    });
});
