(function () {
  var pollTimer = null;
  var sinceSeq = 0;
  var pollIntervalMs = 2500;

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

  window.initClientsPage = function () {
    if (document.getElementById("clients-table-block")) {
      if (!pollTimer) {
        pollOnce();
      }
    } else {
      stopPolling();
    }
  };

  window.initClientsPage();
})();
