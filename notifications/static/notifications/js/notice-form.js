(() => {
  const selectors = [
    { select: "#id_che_do_doc", group: '[data-scope-group="read"]' },
    { select: "#id_che_do_phan_phoi", group: '[data-scope-group="distribution"]' },
  ];

  function sync() {
    selectors.forEach(({ select, group }) => {
      const control = document.querySelector(select);
      const panel = document.querySelector(group);
      if (!control || !panel) return;
      const byCriteria = control.value === "theo_tieu_chi";
      panel.hidden = !byCriteria;
      panel.setAttribute("aria-hidden", String(!byCriteria));
    });
  }

  selectors.forEach(({ select }) => {
    document.querySelector(select)?.addEventListener("change", sync);
  });
  sync();

  const form = document.querySelector("[data-preview-url]");
  const dialog = document.getElementById("oz-notice-preview");
  if (!form || !dialog || typeof dialog.showModal !== "function") return;
  const status = dialog.querySelector("[data-preview-status]");
  const content = dialog.querySelector("[data-preview-content]");
  const warning = dialog.querySelector("[data-preview-warning]");
  const publish = dialog.querySelector("[data-preview-publish]");
  let controller;
  let confirmed = false;
  let trigger;

  function fill(field, value) {
    dialog.querySelector(`[data-preview-${field}]`).textContent = value;
  }

  function scopeLabel(field, group) {
    const select = form.elements[field];
    const label = select.selectedOptions[0]?.textContent.trim() || "";
    if (select.value !== "theo_tieu_chi") return label;
    const selected = [...form.querySelectorAll('[data-scope-group="' + group + '"] input:checked')]
      .map(input => input.closest("label")?.textContent.trim())
      .filter(Boolean);
    return selected.length ? selected.join(" · ") : label;
  }

  form.addEventListener("submit", async event => {
    if (event.submitter?.value !== "publish" || confirmed) return;
    event.preventDefault();
    if (dialog.open) return;
    trigger = event.submitter;
    controller = new AbortController();
    const signal = controller.signal;
    publish.disabled = true;
    status.textContent = "Đang kiểm tra người nhận…";
    content.hidden = true;
    warning.hidden = true;
    dialog.showModal();

    const data = new FormData(form);
    data.delete("tep_dinh_kem");
    data.delete("remove_attachment_ids");
    try {
      const result = await fetch(form.dataset.previewUrl, {method: "POST", body: data, signal});
      const report = await result.json();
      if (signal.aborted) return;
      if (!result.ok) {
        status.textContent = report.errors?.join(" ") || "Chưa kiểm tra được thông báo.";
        return;
      }
      fill("title", data.get("tieu_de"));
      fill("body", data.get("noi_dung"));
      fill("read", scopeLabel("che_do_doc", "read"));
      fill("distribution", scopeLabel("che_do_phan_phoi", "distribution"));
      fill("ack", data.has("yeu_cau_xac_nhan") ? "Có" : "Không");
      fill("count", `${report.recipient_count} người sau khi loại trùng`);
      status.textContent = "";
      content.hidden = false;
      warning.hidden = false;
      publish.disabled = false;
    } catch {
      if (!signal.aborted) status.textContent = "Chưa kiểm tra được thông báo. Quay lại và thử lại.";
    }
  });

  dialog.querySelector("[data-preview-back]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    controller?.abort();
    trigger?.focus();
  });
  publish.addEventListener("click", () => {
    if (publish.disabled || !trigger) return;
    confirmed = true;
    dialog.close();
    try {
      form.requestSubmit(trigger);
    } finally {
      confirmed = false;
    }
  });
})();
