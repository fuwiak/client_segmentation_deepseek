(function () {
  function toggleMobileNav() {
    var drawer = document.getElementById("mobile-drawer");
    var btn = document.getElementById("nav-toggle-btn");
    if (!drawer || !btn) return;
    var open = drawer.hidden;
    drawer.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.textContent = open ? "✕" : "☰";
  }

  function closeModal() {
    var root = document.getElementById("modal-root");
    if (root) root.innerHTML = "";
  }

  function ensureTagRulesPanel() {
    var panel = document.getElementById("tag-rules-panel");
    if (!panel || panel.dataset.loaded === "1") return;
    panel.dataset.loaded = "1";
    if (typeof htmx !== "undefined") {
      htmx.ajax("GET", "/clients/tag-rules/panel", {
        target: "#tag-rules-panel",
        swap: "innerHTML",
      });
    }
  }

  function openTagRulesDrawer() {
    closeClientDrawer();
    ensureTagRulesPanel();
    var drawer = document.getElementById("tag-rules-drawer");
    var overlay = document.getElementById("tag-rules-overlay");
    if (drawer) drawer.hidden = false;
    if (overlay) overlay.hidden = false;
  }

  function closeTagRulesDrawer() {
    var drawer = document.getElementById("tag-rules-drawer");
    var overlay = document.getElementById("tag-rules-overlay");
    if (drawer) drawer.hidden = true;
    if (overlay) overlay.hidden = true;
  }

  function openClientDrawer() {
    closeTagRulesDrawer();
    var drawer = document.getElementById("client-drawer");
    var overlay = document.getElementById("client-drawer-overlay");
    if (drawer) drawer.hidden = false;
    if (overlay) overlay.hidden = false;
  }

  function prepareClientDrawer() {
    openClientDrawer();
    var panel = document.getElementById("client-drawer-panel");
    if (panel) {
      panel.innerHTML = '<p class="hint drawer-loading">Загрузка карточки…</p>';
    }
  }

  function isClientDrawerRequest(elt) {
    return elt && elt.getAttribute && elt.getAttribute("hx-target") === "#client-drawer-panel";
  }

  function closeClientDrawer() {
    var drawer = document.getElementById("client-drawer");
    var overlay = document.getElementById("client-drawer-overlay");
    if (drawer) drawer.hidden = true;
    if (overlay) overlay.hidden = true;
  }

  window.toggleMobileNav = toggleMobileNav;
  window.closeModal = closeModal;
  window.openTagRulesDrawer = openTagRulesDrawer;
  window.closeTagRulesDrawer = closeTagRulesDrawer;
  window.openClientDrawer = openClientDrawer;
  window.prepareClientDrawer = prepareClientDrawer;
  window.closeClientDrawer = closeClientDrawer;

  function settingsNavActive(path) {
    return path === "/settings" || path.indexOf("/settings/") === 0;
  }

  function navPathMatches(navPath, path) {
    if (navPath === "/settings") return settingsNavActive(path);
    return navPath === path;
  }

  function updateActiveNav() {
    var path = window.location.pathname;
    document.querySelectorAll("[data-nav-path]").forEach(function (el) {
      var navPath = el.getAttribute("data-nav-path");
      el.classList.toggle("active", navPathMatches(navPath, path));
    });
  }

  function updateDocumentTitle() {
    var h1 = document.querySelector("#page-content h1");
    if (h1) {
      document.title = h1.textContent.trim() + " · Client CRM";
    }
  }

  function disableBoostOnDownloads(root) {
    (root || document).querySelectorAll('a[href^="/download/"]').forEach(function (a) {
      a.setAttribute("hx-boost", "false");
    });
  }

  function processHtmxRegion(root) {
    if (typeof htmx === "undefined" || !root) return;
    htmx.process(root);
  }

  function activateLazyWidgets(root) {
    if (!root) return;
    processHtmxRegion(root);
    root.querySelectorAll("[hx-get][hx-trigger]").forEach(function (el) {
      var trigger = el.getAttribute("hx-trigger") || "";
      if (!/\b(load|revealed)\b/.test(trigger)) return;
      if (el.getAttribute("data-lazy-activated") === "1") return;
      el.setAttribute("data-lazy-activated", "1");
      if (/\brevealed\b/.test(trigger)) {
        htmx.trigger(el, "revealed");
      } else {
        htmx.trigger(el, "load");
      }
    });
  }

  function initPageScripts(swapTarget) {
    disableBoostOnDownloads(document.getElementById("page-content"));
    if (typeof window.initClientsPage === "function") {
      window.initClientsPage();
    }
    if (typeof htmx === "undefined") return;
    if (swapTarget) {
      activateLazyWidgets(swapTarget);
    } else {
      var page = document.getElementById("page-content");
      if (page) activateLazyWidgets(page);
    }
    if (!document.body.dataset.headerWidgetsInit) {
      document.body.dataset.headerWidgetsInit = "1";
      var header = document.querySelector(".site-header");
      if (header) activateLazyWidgets(header);
    }
  }

  function isLiveSwapTarget(target) {
    return (
      target &&
      (target.id === "page-content" ||
        target.id === "clients-live-region" ||
        target.id === "settings-live-region")
    );
  }

  function fallbackNavigateFromHtmxEvent(e) {
    var elt = e.detail && e.detail.elt;
    if (!elt || !elt.closest) return;
    var link = elt.closest("a[href]");
    if (!link) return;
    var href = link.getAttribute("href");
    if (!href || href.charAt(0) !== "/" || href.indexOf("/download/") === 0) return;
    window.location.assign(href);
  }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    closeModal();
    closeTagRulesDrawer();
    closeClientDrawer();
    var drawer = document.getElementById("mobile-drawer");
    if (drawer && !drawer.hidden) toggleMobileNav();
  });

  document.body.addEventListener("htmx:beforeRequest", function (e) {
    var target = e.detail.target;
    var elt = e.detail.elt;
    if (isLiveSwapTarget(target)) {
      document.documentElement.classList.add("is-navigating");
    }
    if (isClientDrawerRequest(elt)) {
      prepareClientDrawer();
    }
    if (target && target.id === "page-content") {
      closeTagRulesDrawer();
      closeClientDrawer();
    }
    if (e.detail.elt && e.detail.elt.closest && e.detail.elt.closest(".upload-form")) {
      var modal = document.getElementById("upload-modal");
      if (modal) modal.hidden = false;
    }
  });

  document.body.addEventListener("htmx:afterRequest", function (e) {
    document.documentElement.classList.remove("is-navigating");
    if (e.detail.elt && e.detail.elt.closest && e.detail.elt.closest(".upload-form")) {
      var modal = document.getElementById("upload-modal");
      if (modal) modal.hidden = true;
    }
  });

  document.body.addEventListener("htmx:responseError", function (e) {
    document.documentElement.classList.remove("is-navigating");
    if (isClientDrawerRequest(e.detail && e.detail.elt)) {
      var panel = document.getElementById("client-drawer-panel");
      if (panel) {
        panel.innerHTML = '<p class="hint warn">Не удалось загрузить карточку клиента.</p>';
      }
      openClientDrawer();
    }
  });

  document.body.addEventListener("htmx:sendError", function (e) {
    document.documentElement.classList.remove("is-navigating");
    fallbackNavigateFromHtmxEvent(e);
  });

  document.body.addEventListener("htmx:timeout", function (e) {
    document.documentElement.classList.remove("is-navigating");
    fallbackNavigateFromHtmxEvent(e);
  });

  document.body.addEventListener("htmx:responseError", fallbackNavigateFromHtmxEvent);

  document.body.addEventListener("htmx:afterSwap", function (e) {
    var target = e.detail.target;
    if (target && target.id === "client-drawer-panel") {
      openClientDrawer();
      processHtmxRegion(target);
    } else if (target && target.id && target.id.indexOf("orders-") === 0) {
      var row = target.closest(".orders-expand-row");
      if (row) {
        row.classList.add("is-open");
        processHtmxRegion(target);
      }
    } else if (target && target.id === "clients-table-block") {
      processHtmxRegion(target);
    }
    if (isLiveSwapTarget(target)) {
      updateActiveNav();
      updateDocumentTitle();
      initPageScripts(target);
      var drawer = document.getElementById("mobile-drawer");
      if (drawer && !drawer.hidden) toggleMobileNav();
    }
  });

  document.body.addEventListener("htmx:pushedIntoHistory", function () {
    updateActiveNav();
    updateDocumentTitle();
  });

  disableBoostOnDownloads(document);
  updateActiveNav();
  initPageScripts();
})();
