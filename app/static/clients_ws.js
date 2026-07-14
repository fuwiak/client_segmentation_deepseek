(function () {
  var wsUrl = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/clients";
  var socket = null;
  var reconnectMs = 1500;
  var reconnectTimer = null;

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

  function onMessage(event) {
    var data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (data.type === "ai_progress") {
      updateProgress(data);
    } else if (data.type === "ai_rows" && Array.isArray(data.rows)) {
      data.rows.forEach(updateRow);
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (!socket) return;
    socket.onclose = null;
    socket.onerror = null;
    socket.onmessage = null;
    try {
      socket.close();
    } catch (e) {}
    socket = null;
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    socket = new WebSocket(wsUrl);
    socket.onmessage = onMessage;
    socket.onclose = function () {
      if (document.getElementById("clients-table-block")) {
        reconnectTimer = setTimeout(connect, reconnectMs);
      }
    };
    socket.onerror = function () {
      try {
        socket.close();
      } catch (e) {}
    };
  }

  window.initClientsPage = function () {
    disconnect();
    if (document.getElementById("clients-table-block")) {
      connect();
    }
  };

  window.initClientsPage();
})();
