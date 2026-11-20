(() => {
    const dialog = document.getElementById("oz-confirm-dialog");
    if (!dialog) return;
    const approved = new WeakSet();
    let pending = null;
    document.addEventListener("submit", event => {
        const form = event.target;
        const submitter = event.submitter;
        const source = submitter?.hasAttribute("data-confirm-message") ? submitter : form;
        if (!source.hasAttribute("data-confirm-message") || approved.has(form)) return;
        event.preventDefault();
        if (dialog.open) return;
        pending = {form, submitter};
        dialog.querySelector("#oz-confirm-title").textContent = source.dataset.confirmTitle || "Xác nhận thao tác";
        dialog.querySelector("#oz-confirm-message").textContent = source.dataset.confirmMessage;
        dialog.querySelector("[data-confirm-accept]").textContent = source.dataset.confirmLabel || "Xác nhận";
        dialog.showModal();
    });
    dialog.querySelector("[data-confirm-cancel]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
        pending?.submitter?.focus();
        pending = null;
    });
    dialog.querySelector("[data-confirm-accept]").addEventListener("click", () => {
        if (!pending) return;
        const {form, submitter} = pending;
        pending = null;
        dialog.close();
        approved.add(form);
        try { form.requestSubmit(submitter || undefined); }
        finally { approved.delete(form); }
    });
})();
