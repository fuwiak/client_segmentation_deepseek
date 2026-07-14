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

  function toggleDiagPanel(forceOpen) {
    var panel = document.getElementById("diag-panel");
    var body = document.getElementById("diag-panel-body");
    var btn = document.getElementById("diag-panel-toggle");
    if (!panel || !body || !btn) return;
    var open = typeof forceOpen === "boolean" ? forceOpen : body.hidden;
    body.hidden = !open;
    panel.classList.toggle("is-open", open);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function closeDiagPanel() {
    toggleDiagPanel(false);
  }

  function isOrdersModalRequest(elt) {
    return elt && elt.classList && elt.classList.contains("orders-modal-btn");
  }

  function showOrdersModalLoading() {
    closeClientDrawer();
    closeTagRulesDrawer();
    var loading = document.getElementById("orders-modal-loading");
    if (loading) loading.hidden = false;
  }

  function hideOrdersModalLoading() {
    var loading = document.getElementById("orders-modal-loading");
    if (loading) loading.hidden = true;
  }

  function finishOrdersModalRequest(elt, xhr) {
    if (!isOrdersModalRequest(elt)) return;
    hideOrdersModalLoading();
    var root = document.getElementById("modal-root");
    if (!root || !xhr || !xhr.responseText) return;
    if (!root.querySelector(".orders-modal-overlay")) {
      root.innerHTML = xhr.responseText;
      processHtmxRegion(root);
      activateLazyWidgets(root);
    }
  }

  function prepareOrdersModal(event) {
    if (event) {
      event.stopPropagation();
    }
    showOrdersModalLoading();
  }

  function closeModal() {
    hideOrdersModalLoading();
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

  function flashToolbarBtn(elt, ms) {
    if (!elt || !elt.classList) return;
    elt.classList.add("is-busy");
    window.setTimeout(function () {
      elt.classList.remove("is-busy");
    }, ms || 800);
  }

  function openTagRulesDrawer(evt) {
    closeClientDrawer();
    if (evt && evt.currentTarget) {
      flashToolbarBtn(evt.currentTarget, 500);
    }
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

  function showClientDrawerLoading() {
    openClientDrawer();
    var loading = document.getElementById("client-drawer-loading");
    if (loading) loading.hidden = false;
  }

  function hideClientDrawerLoading() {
    var loading = document.getElementById("client-drawer-loading");
    if (loading) loading.hidden = true;
  }

  function isClientDrawerRequest(elt) {
    return elt && elt.getAttribute && elt.getAttribute("hx-target") === "#client-drawer-panel";
  }

  function finishClientDrawerRequest(elt, xhr) {
    if (!isClientDrawerRequest(elt)) return;
    hideClientDrawerLoading();
    var panel = document.getElementById("client-drawer-panel");
    if (!panel || !xhr || !xhr.responseText) return;
    if (!panel.querySelector(".rules-drawer-header")) {
      panel.innerHTML = xhr.responseText;
    }
    processHtmxRegion(panel);
    openClientDrawer();
  }

  function closeClientDrawer() {
    hideClientDrawerLoading();
    var drawer = document.getElementById("client-drawer");
    var overlay = document.getElementById("client-drawer-overlay");
    if (drawer) drawer.hidden = true;
    if (overlay) overlay.hidden = true;
  }

  window.toggleMobileNav = toggleMobileNav;
  window.toggleDiagPanel = toggleDiagPanel;
  window.closeDiagPanel = closeDiagPanel;
  window.closeModal = closeModal;
  window.prepareOrdersModal = prepareOrdersModal;
  window.openTagRulesDrawer = openTagRulesDrawer;
  window.closeTagRulesDrawer = closeTagRulesDrawer;
  window.openClientDrawer = openClientDrawer;
  window.closeClientDrawer = closeClientDrawer;

  function settingsNavActive(path) {
    return path === "/settings" || path.indexOf("/settings/") === 0;
  }

  function currentNavPath() {
    var path = window.location.pathname || "/";
    if (path.length > 1 && path.endsWith("/")) {
      path = path.slice(0, -1);
    }
    return path || "/";
  }

  function navPathMatches(navPath, path) {
    if (navPath === "/settings") return path === "/settings";
    if (navPath === "/") return path === "/";
    return navPath === path;
  }

  function updateActiveNav() {
    var path = currentNavPath();
    document.querySelectorAll("[data-nav-path]").forEach(function (el) {
      var navPath = el.getAttribute("data-nav-path");
      var active = navPathMatches(navPath, path);
      el.classList.toggle("active", active);
      if (active) {
        el.setAttribute("aria-current", "page");
      } else {
        el.removeAttribute("aria-current");
      }
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
    if (!document.body.dataset.diagWidgetsInit) {
      document.body.dataset.diagWidgetsInit = "1";
      var diag = document.getElementById("diag-panel");
      if (diag) activateLazyWidgets(diag);
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
    closeDiagPanel();
    var drawer = document.getElementById("mobile-drawer");
    if (drawer && !drawer.hidden) toggleMobileNav();
  });

  document.body.addEventListener("click", function (e) {
    var exportBtn = e.target.closest && e.target.closest(".export-xlsx-btn");
    if (exportBtn) {
      flashToolbarBtn(exportBtn, 2200);
    }
    var diagLink = e.target.closest && e.target.closest(".diag-panel-nav a[href]");
    if (diagLink) closeDiagPanel();
    var diagPanel = document.getElementById("diag-panel");
    var diagBody = document.getElementById("diag-panel-body");
    if (
      diagPanel &&
      diagBody &&
      !diagBody.hidden &&
      !e.target.closest("#diag-panel")
    ) {
      closeDiagPanel();
    }
  });

  document.body.addEventListener("htmx:beforeRequest", function (e) {
    var target = e.detail.target;
    var elt = e.detail.elt;
    if (isLiveSwapTarget(target)) {
      document.documentElement.classList.add("is-navigating");
    }
    if (isClientDrawerRequest(elt)) {
      showClientDrawerLoading();
    }
    if (isOrdersModalRequest(elt)) {
      showOrdersModalLoading();
    }
    if (target && target.id === "page-content") {
      closeTagRulesDrawer();
      closeClientDrawer();
      closeDiagPanel();
      closeModal();
    }
    if (e.detail.elt && e.detail.elt.closest && e.detail.elt.closest(".upload-form")) {
      var modal = document.getElementById("upload-modal");
      if (modal) modal.hidden = false;
    }
  });

  document.body.addEventListener("htmx:afterRequest", function (e) {
    document.documentElement.classList.remove("is-navigating");
    if (e.detail.successful) {
      finishClientDrawerRequest(e.detail.elt, e.detail.xhr);
      finishOrdersModalRequest(e.detail.elt, e.detail.xhr);
    }
    if (e.detail.elt && e.detail.elt.closest && e.detail.elt.closest(".upload-form")) {
      var modal = document.getElementById("upload-modal");
      if (modal) modal.hidden = true;
    }
  });

  document.body.addEventListener("htmx:responseError", function (e) {
    document.documentElement.classList.remove("is-navigating");
    var elt = e.detail && e.detail.elt;
    if (isClientDrawerRequest(elt)) {
      hideClientDrawerLoading();
      var panel = document.getElementById("client-drawer-panel");
      if (panel) {
        panel.innerHTML = '<p class="hint warn">Не удалось загрузить карточку клиента.</p>';
      }
      openClientDrawer();
    }
    if (isOrdersModalRequest(elt)) {
      hideOrdersModalLoading();
      var root = document.getElementById("modal-root");
      if (root) {
        root.innerHTML =
          '<div class="modal-overlay orders-modal-overlay" onclick="if(event.target===this) closeModal()">' +
          '<div class="modal-card orders-modal">' +
          '<button type="button" class="modal-close" onclick="closeModal()" aria-label="Закрыть">×</button>' +
          '<p class="hint warn">Не удалось загрузить заказы.</p>' +
          "</div></div>";
      }
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
      hideClientDrawerLoading();
      openClientDrawer();
      processHtmxRegion(target);
    } else if (target && target.id === "client-orders-list") {
      target.hidden = false;
      processHtmxRegion(target);
      var elt = e.detail.elt;
      if (elt && elt.classList && elt.classList.contains("client-orders-expand-btn")) {
        elt.setAttribute("aria-expanded", "true");
        elt.classList.add("is-open");
      }
    } else if (target && target.id === "modal-root") {
      hideOrdersModalLoading();
      processHtmxRegion(target);
      activateLazyWidgets(target);
    } else if (target && target.id === "orders-modal-content") {
      processHtmxRegion(target);
    } else if (target && target.id === "clients-table-block") {
      processHtmxRegion(target);
      if (typeof window.initClientsPage === "function") {
        window.initClientsPage();
      }
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
