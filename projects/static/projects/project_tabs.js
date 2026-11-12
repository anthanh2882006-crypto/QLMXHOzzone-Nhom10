/* Các vùng của GD-059 dùng chung một nguồn vấn đề và giữ liên kết đến từng lần thử. */
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-project-tabs]").forEach(function (navigation) {
        const links = Array.from(navigation.querySelectorAll('a[href^="#"]'));
        const panels = links.map(function (link) {
            return document.getElementById(link.getAttribute("href").slice(1));
        });
        if (!links.length || panels.some(function (panel) { return !panel; })) return;
        navigation.setAttribute("role", "tablist");
        links.forEach(function (link, index) {
            link.setAttribute("role", "tab");
            link.setAttribute("aria-controls", panels[index].id);
            panels[index].setAttribute("role", "tabpanel");
            panels[index].setAttribute("aria-labelledby", link.id);
            panels[index].tabIndex = 0;
        });
        function select(index, focus) {
            links.forEach(function (link, current) {
                const active = current === index;
                link.setAttribute("aria-selected", String(active));
                link.tabIndex = active ? 0 : -1;
                link.classList.toggle("is-active", active);
                panels[current].hidden = !active;
            });
            if (focus) links[index].focus();
        }
        function fromHash() {
            let target;
            try { target = document.getElementById(decodeURIComponent(window.location.hash.slice(1))); }
            catch (_) { target = null; }
            const panel = target && target.closest("[data-project-panel]");
            const index = panels.indexOf(panel);
            select(index < 0 ? 0 : index, false);
        }
        links.forEach(function (link, index) {
            link.addEventListener("click", function (event) {
                if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                window.history.replaceState(null, "", link.getAttribute("href"));
                select(index, false);
            });
            link.addEventListener("keydown", function (event) {
                let next = index;
                if (event.key === "ArrowRight") next = (index + 1) % links.length;
                else if (event.key === "ArrowLeft") next = (index + links.length - 1) % links.length;
                else if (event.key === "Home") next = 0;
                else if (event.key === "End") next = links.length - 1;
                else return;
                event.preventDefault();
                window.history.replaceState(null, "", links[next].getAttribute("href"));
                select(next, true);
            });
        });
        window.addEventListener("hashchange", fromHash);
        fromHash();
    });
});
