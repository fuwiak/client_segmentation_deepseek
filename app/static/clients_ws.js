(function () {
  var pollTimer = null;
  var sinceSeq = 0;
  var pollIntervalMs = 2500;
  var COLUMN_ORDER_KEY = "clients_table_column_order";
  var COLUMN_HIDDEN_KEY = "clients_table_hidden_columns";

  function esc(text) {
    var d = document.createElement("div");
    d.textContent = text == null ? "" : String(text);
    return d.innerHTML;
  }

  function renderAiCell(state, text) {
    if (state === "running") {
      return '<span class="ai-cell-running" title="DeepSeek ещё не обработал это поле">running</span>';
    }
    if (state === "unknown") {
      return '<span class="ai-cell-unknown" title="AI не смог определить значение">no data</span>';
    }
    return esc(text);
  }

  function updateRow(patch) {
    if (!patch || !patch.client_id) return;
    var row = document.querySelector('tr[data-client-id="' + CSS.escape(patch.client_id) + '"]');
    if (!row) return;
    var cells = patch.cells || {};
    Object.keys(cells).forEach(function (col) {
      var td = row.querySelector('td[data-col="' + CSS.escape(col) + '"]');
      if (!td) return;
      if (col === "Наименование" && td.querySelector(".client-name-link")) return;
      var info = cells[col];
      td.innerHTML = renderAiCell(info.state, info.text);
    });
  }

  function updateProgress(data) {
    var block = document.getElementById("ai-progress-block");
    if (!block) return;
    var status = data.status || "idle";
    var done = data.done || 0;
    var total = data.total || 0;
    var percent = data.percent || (total ? Math.floor(done / total * 100) : 0);
    var error = data.error || "";
    if (status === "running") {
      block.innerHTML =
        '<p class="hint">AI-сегментация в фоне… ' + done + "/" + total + " (" + percent + '%)</p>' +
        '<div class="progress-bar"><div class="progress-fill" style="width: ' + percent + '%"></div></div>';
    } else if (status === "done" && total > 0) {
      block.innerHTML = '<p class="hint ok">AI готово: ' + total + " клиентов обработано.</p>";
    } else if (status === "error") {
      block.innerHTML = '<p class="hint warn">AI: ' + esc(error || "ошибка") + "</p>";
    }
  }

  function scheduleNextPoll(delayMs) {
    if (pollTimer) {
      clearTimeout(pollTimer);
    }
    pollTimer = setTimeout(pollOnce, delayMs);
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function pollOnce() {
    if (!document.getElementById("clients-table-block")) {
      stopPolling();
      return;
    }
    fetch("/clients/ai/poll?since=" + encodeURIComponent(String(sinceSeq)), {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("poll failed");
        return resp.json();
      })
      .then(function (data) {
        if (typeof data.seq === "number" && data.seq > sinceSeq) {
          sinceSeq = data.seq;
        }
        updateProgress(data);
        if (Array.isArray(data.rows)) {
          data.rows.forEach(updateRow);
        }
        var delay = data.status === "running" ? 1500 : 4000;
        scheduleNextPoll(delay);
      })
      .catch(function () {
        scheduleNextPoll(5000);
      });
  }

  function currentColumnOrder(table) {
    return Array.prototype.map.call(
      table.querySelectorAll("thead th[data-col]"),
      function (th) {
        return th.getAttribute("data-col");
      }
    );
  }

  function loadColumnOrder() {
    try {
      var raw = localStorage.getItem(COLUMN_ORDER_KEY);
      if (!raw) return null;
      var order = JSON.parse(raw);
      return Array.isArray(order) ? order : null;
    } catch (_err) {
      return null;
    }
  }

  function saveColumnOrder(order) {
    try {
      localStorage.setItem(COLUMN_ORDER_KEY, JSON.stringify(order));
    } catch (_err) {
      /* ignore quota / private mode */
    }
  }

  function mergeColumnOrder(saved, current) {
    var merged = saved.filter(function (col) {
      return current.indexOf(col) >= 0;
    });
    current.forEach(function (col) {
      if (merged.indexOf(col) < 0) merged.push(col);
    });
    return merged;
  }

  function moveColumnNode(row, col, beforeNode) {
    var cell = row.querySelector('th[data-col="' + CSS.escape(col) + '"], td[data-col="' + CSS.escape(col) + '"]');
    if (!cell) return;
    if (beforeNode) {
      row.insertBefore(cell, beforeNode);
    } else {
      row.appendChild(cell);
    }
  }

  function applyColumnOrder(table, order) {
    var current = currentColumnOrder(table);
    if (!current.length) return;
    var next = mergeColumnOrder(order, current);
    var theadRow = table.querySelector("thead tr");
    if (!theadRow) return;
    next.forEach(function (col) {
      moveColumnNode(theadRow, col, null);
    });
    table.querySelectorAll("tbody tr").forEach(function (row) {
      next.forEach(function (col) {
        moveColumnNode(row, col, null);
      });
    });
  }

  function loadHiddenColumns() {
    try {
      var raw = localStorage.getItem(COLUMN_HIDDEN_KEY);
      if (!raw) return [];
      var hidden = JSON.parse(raw);
      return Array.isArray(hidden) ? hidden : [];
    } catch (_err) {
      return [];
    }
  }

  function saveHiddenColumns(hidden) {
    try {
      localStorage.setItem(COLUMN_HIDDEN_KEY, JSON.stringify(hidden));
    } catch (_err) {
      /* ignore */
    }
  }

  function applyColumnVisibility(table, hidden) {
    var hideSet = {};
    (hidden || []).forEach(function (col) {
      hideSet[col] = true;
    });
    table.querySelectorAll("th[data-col], td[data-col]").forEach(function (cell) {
      var col = cell.getAttribute("data-col");
      if (!col) return;
      cell.classList.toggle("col-hidden", !!hideSet[col]);
    });
    var panel = document.getElementById("columns-picker-panel");
    if (!panel) return;
    panel.querySelectorAll(".col-visibility-toggle").forEach(function (input) {
      var col = input.getAttribute("data-col");
      input.checked = !hideSet[col];
    });
  }

  function initColumnVisibility(table) {
    var hidden = loadHiddenColumns();
    applyColumnVisibility(table, hidden);
    var panel = document.getElementById("columns-picker-panel");
    if (!panel || panel.dataset.visInit === "1") return;
    panel.dataset.visInit = "1";
    panel.addEventListener("change", function (e) {
      var input = e.target;
      if (!input || !input.classList || !input.classList.contains("col-visibility-toggle")) return;
      var nextHidden = [];
      panel.querySelectorAll(".col-visibility-toggle").forEach(function (el) {
        if (!el.checked) nextHidden.push(el.getAttribute("data-col"));
      });
      // Нельзя скрыть все колонки.
      if (nextHidden.length >= currentColumnOrder(table).length) {
        input.checked = true;
        return;
      }
      saveHiddenColumns(nextHidden);
      applyColumnVisibility(table, nextHidden);
    });
  }

  function initColumnDragDrop(table) {
    var saved = loadColumnOrder();
    if (saved && saved.length) {
      applyColumnOrder(table, saved);
    }

    table.querySelectorAll(".col-drag-handle").forEach(function (handle) {
      if (handle.dataset.dragInit === "1") return;
      handle.dataset.dragInit = "1";
      var th = handle.closest("th[data-col]");
      if (!th) return;
      var col = th.getAttribute("data-col");

      handle.addEventListener("dragstart", function (e) {
        e.stopPropagation();
        e.dataTransfer.setData("text/plain", col);
        e.dataTransfer.effectAllowed = "move";
        th.classList.add("col-dragging");
      });

      handle.addEventListener("dragend", function () {
        th.classList.remove("col-dragging");
        table.querySelectorAll("th.col-drag-over").forEach(function (el) {
          el.classList.remove("col-drag-over");
        });
      });
    });

    table.querySelectorAll("thead th[data-col]").forEach(function (th) {
      if (th.dataset.dropInit === "1") return;
      th.dataset.dropInit = "1";

      th.addEventListener("dragover", function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        th.classList.add("col-drag-over");
      });

      th.addEventListener("dragleave", function () {
        th.classList.remove("col-drag-over");
      });

      th.addEventListener("drop", function (e) {
        e.preventDefault();
        th.classList.remove("col-drag-over");
        var fromCol = e.dataTransfer.getData("text/plain");
        var toCol = th.getAttribute("data-col");
        if (!fromCol || !toCol || fromCol === toCol) return;
        var order = currentColumnOrder(table);
        var fromIdx = order.indexOf(fromCol);
        var toIdx = order.indexOf(toCol);
        if (fromIdx < 0 || toIdx < 0) return;
        order.splice(fromIdx, 1);
        order.splice(toIdx, 0, fromCol);
        applyColumnOrder(table, order);
        saveColumnOrder(order);
      });
    });
  }

  function initClientsTable() {
    var block = document.getElementById("clients-table-block");
    if (!block) return;
    var table = block.querySelector(".clients-table");
    if (table) {
      initColumnDragDrop(table);
      initColumnVisibility(table);
    }
  }

  window.initClientsPage = function () {
    if (document.getElementById("clients-table-block")) {
      initClientsTable();
      if (!pollTimer) {
        pollOnce();
      }
    } else {
      stopPolling();
    }
  };

  window.initClientsPage();
})();
