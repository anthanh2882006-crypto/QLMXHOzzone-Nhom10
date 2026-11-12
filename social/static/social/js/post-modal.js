(function () {
    "use strict";

    function initPostModal() {
        const modal = document.querySelector("[data-post-modal]");
        if (!modal) return;

        const dialog = modal.querySelector(".social-modal-dialog");
        const steps = Array.from(modal.querySelectorAll("[data-post-modal-step]"));
        let lastFocused = null;

        function showStep(name) {
            steps.forEach((step) => {
                step.hidden = step.dataset.postModalStep !== name;
            });
            if (name === "compose") {
                const textarea = modal.querySelector("#id_noi_dung");
                if (textarea) window.setTimeout(() => textarea.focus(), 30);
            } else {
                const firstAction = modal.querySelector('[data-post-modal-next="compose"]');
                if (firstAction) firstAction.focus();
            }
        }

        function openModal(stepName) {
            lastFocused = document.activeElement;
            modal.hidden = false;
            modal.setAttribute("aria-hidden", "false");
            document.body.classList.add("social-modal-open");
            showStep(stepName || "choice");
            dialog.focus();
        }

        function closeModal() {
            modal.hidden = true;
            modal.setAttribute("aria-hidden", "true");
            document.body.classList.remove("social-modal-open");
            if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
        }

        document.addEventListener("click", function (event) {
            const opener = event.target.closest("[data-post-modal-open]");
            if (opener) {
                event.preventDefault();
                openModal("choice");
                return;
            }

            if (event.target.closest("[data-post-modal-close]")) {
                closeModal();
                return;
            }

            const next = event.target.closest("[data-post-modal-next]");
            if (next) {
                showStep(next.dataset.postModalNext);
                return;
            }

            if (event.target.closest("[data-post-modal-back]")) {
                showStep("choice");
            }
        });

        document.addEventListener("keydown", function (event) {
            if (modal.hidden) return;
            if (event.key === "Escape") {
                event.preventDefault();
                closeModal();
            }
        });

        const fileInput = modal.querySelector("#id_tep_dinh_kem");
        const fileNames = modal.querySelector("[data-file-names]");
        if (fileInput && fileNames) {
            fileInput.addEventListener("change", function () {
                const files = Array.from(fileInput.files || []);
                if (!files.length) {
                    fileNames.textContent = "Đính kèm tối đa 5 tệp, 10 MB/tệp.";
                } else if (files.length <= 2) {
                    fileNames.textContent = files.map((file) => file.name).join(", ");
                } else {
                    fileNames.textContent = files.length + " tệp đã chọn";
                }
            });
        }

        const form = modal.querySelector("[data-post-modal-form]");
        if (form) {
            form.addEventListener("submit", function () {
                const button = form.querySelector('button[type="submit"]');
                if (button) {
                    button.disabled = true;
                    button.textContent = "Đang đăng...";
                }
            });
        }

        if (modal.dataset.initialStep === "compose") {
            openModal("compose");
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initPostModal, { once: true });
    } else {
        initPostModal();
    }
})();
