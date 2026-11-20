(() => {
  function addPicker(picker) {
    const inputBlock = picker.querySelector("[data-attachment-input]");
    const input = inputBlock.querySelector('input[type="file"]');
    const dialog = picker.querySelector("dialog");
    if (!input || typeof dialog?.showModal !== "function") return;
    const drop = picker.querySelector("[data-attachment-drop]");
    const opener = picker.querySelector("[data-attachment-open]");
    const browse = picker.querySelector("[data-attachment-browse]");
    const summary = picker.querySelector("[data-attachment-summary]");
    const status = picker.querySelector("[data-attachment-error]");
    const list = picker.querySelector("[data-attachment-selection]");
    const empty = picker.querySelector("[data-attachment-empty]");
    const clear = picker.querySelector("[data-attachment-clear]");
    const allowed = new Set(input.accept.toLowerCase().split(","));
    let selected = [];

    function showSelection() {
      list.replaceChildren(...selected.map(file => {
        const row = document.createElement("li");
        row.textContent = file.name;
        return row;
      }));
      empty.hidden = selected.length > 0;
      clear.disabled = !selected.length;
      summary.textContent = selected.length ? selected.map(file => file.name).join(", ") : "Chưa chọn tệp.";
    }

    function storeFiles(files) {
      const transfer = new DataTransfer();
      files.forEach(file => transfer.items.add(file));
      input.files = transfer.files;
    }

    function acceptFiles(files, dropped = false) {
      const limit = Number(input.dataset.maxFiles);
      const sizeLimit = Number(input.dataset.maxBytes);
      const invalid = files.find(file => !allowed.has(file.name.slice(file.name.lastIndexOf(".")).toLowerCase()));
      const tooLarge = files.find(file => file.size > sizeLimit);
      let error = "";
      if (files.length > limit) error = "Chỉ chọn tối đa " + limit + " tệp.";
      else if (invalid) error = invalid.name + " có định dạng chưa được hỗ trợ.";
      else if (tooLarge) error = tooLarge.name + " vượt quá " + Math.round(sizeLimit / 1048576) + " MB.";

      status.textContent = error;
      status.hidden = !error;
      if (!error) selected = files;
      if (dropped || error) storeFiles(selected);
      showSelection();
    }

    browse.addEventListener("click", () => input.click());
    input.addEventListener("change", () => acceptFiles(Array.from(input.files)));
    drop.addEventListener("dragover", event => {
      if (event.dataTransfer.types.includes("Files")) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }
    });
    drop.addEventListener("drop", event => {
      if (!event.dataTransfer.files.length) return;
      event.preventDefault();
      acceptFiles(Array.from(event.dataTransfer.files), true);
    });
    clear.addEventListener("click", () => {
      input.value = "";
      acceptFiles([]);
      browse.focus();
    });
    opener.addEventListener("click", () => dialog.showModal());
    picker.querySelector("[data-attachment-done]").addEventListener("click", () => dialog.close());
    drop.append(inputBlock);
    inputBlock.hidden = true;
    opener.hidden = false;
    summary.hidden = false;
    showSelection();
  }

  function addFilter(region) {
    const controls = region.querySelector("[data-attachment-filters]");
    const query = controls.querySelector("[data-attachment-query]");
    const type = controls.querySelector("[data-attachment-type]");
    const noMatch = controls.querySelector("[data-attachment-no-match]");
    const rows = Array.from(region.querySelectorAll("[data-attachment-row]"));
    const searchableText = rows.map(row => row.textContent.toLocaleLowerCase("vi"));
    function filter() {
      const word = query.value.trim().toLocaleLowerCase("vi");
      let count = 0;
      rows.forEach((row, index) => {
        const mime = row.dataset.attachmentRow;
        const group = mime.startsWith("image/") ? "image" : mime === "application/pdf" ? "pdf" : "other";
        const matches = searchableText[index].includes(word) && (!type.value || group === type.value);
        row.hidden = !matches;
        count += Number(matches);
      });
      noMatch.hidden = count > 0;
    }
    query.addEventListener("input", filter);
    type.addEventListener("change", filter);
    controls.hidden = false;
    filter();
  }

  document.addEventListener("submit", event => {
    if (event.defaultPrevented) return;
    event.target.querySelectorAll("[data-attachment-picker]").forEach(picker => {
      if (picker.querySelector('input[type="file"]')?.files.length) {
        picker.querySelector("[data-attachment-summary]").textContent = "Đang tải tệp đính kèm…";
      }
    });
  });

  document.querySelectorAll("[data-attachment-picker]").forEach(addPicker);
  document.querySelectorAll("[data-attachment-list]").forEach(addFilter);
})();
