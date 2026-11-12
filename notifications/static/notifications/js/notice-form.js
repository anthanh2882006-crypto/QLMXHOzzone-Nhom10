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
})();
