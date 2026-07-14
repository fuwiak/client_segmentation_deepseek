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

  function openTagRulesDrawer() {
    closeClientDrawer();
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

  function initPageScripts() {
    disableBoostOnDownloads(document.getElementById("page-content"));
    if (typeof window.initClientsPage === "function") {
      window.initClientsPage();
    }
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
    if (target && target.id === "page-content") {
      document.documentElement.classList.add("is-navigating");
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

  document.body.addEventListener("htmx:responseError", function () {
    document.documentElement.classList.remove("is-navigating");
  });

  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && e.detail.target.id === "page-content") {
      updateActiveNav();
      updateDocumentTitle();
      initPageScripts();
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
