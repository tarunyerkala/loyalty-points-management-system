/* LoyaltyHub Frontend Controller (Vanilla JS + Chart.js with offline Canvas fallback) */

const state = {
  currentPage: "dashboard",
  custOffset: 0,
  custLimit: 25,
  custTotal: 0,
  ordOffset: 0,
  ordLimit: 25,
  ordTotal: 0,
  txOffset: 0,
  txLimit: 25,
  txTotal: 0,
  selectedCustomerId: null,
  selectedOrderId: null,
  ordersLoading: false,
  auditLoading: false,
  dashboardData: null,
  anomaliesData: null,
  charts: {},
};

const PAGE_TITLES = {
  dashboard: ["Executive Dashboard", "Real-time loyalty liability, ledger flow, and audit health"],
  customers: ["Customers & Loyalty Accounts", "Search members, register accounts, manage orders & tier progression"],
  orders: ["Orders Management", "Search orders, inspect line items, returns & linked points transactions"],
  transactions: ["Points Transaction Ledger", "Auditable immutable ledger of accruals, redemptions, reversals & expiries"],
  rewards: ["Rewards & Redemptions", "Browse reward catalog and execute atomic balance-safe redemptions"],
  analytics: ["Loyalty Analytics", "Earned vs redeemed trends, tier distribution, expiry lots & anomalies"],
  audit: ["Audit & Validation", "Ledger reconciliation and automated detection across 5 integrity rules"],
};

const API_BASE =
  ["5500", "5501", "3000"].includes(window.location.port) || window.location.protocol === "file:"
    ? "http://127.0.0.1:8001"
    : "";

const fmtNum = (n) => Number(n ?? 0).toLocaleString("en-US");
const fmtCur = (n) => `$${Number(n ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const escapeHtml = (val) =>
  String(val ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

async function apiFetch(url, options = {}) {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function showToast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function tierBadge(tierName) {
  const t = (tierName || "Bronze").toLowerCase();
  const cls = t.includes("gold") ? "badge-gold" : t.includes("silver") ? "badge-silver" : "badge-bronze";
  return `<span class="badge ${cls}">${tierName}</span>`;
}

function txTypeBadge(txType) {
  const map = {
    ACCRUAL: "badge-green",
    REDEMPTION: "badge-blue",
    REVERSAL: "badge-amber",
    EXPIRY: "badge-red",
  };
  return `<span class="badge ${map[txType] || "badge-muted"}">${txType}</span>`;
}

function statusBadge(status) {
  const map = {
    COMPLETED: "badge-green",
    POSTED: "badge-green",
    ACTIVE: "badge-green",
    PARTIALLY_RETURNED: "badge-amber",
    RETURNED: "badge-amber",
    REJECTED: "badge-red",
    CRITICAL: "badge-red",
    HIGH: "badge-red",
    MEDIUM: "badge-amber",
  };
  return `<span class="badge ${map[status] || "badge-muted"}">${status}</span>`;
}

function navigateTo(page) {
  state.currentPage = page;
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.page === page);
  });
  document.querySelectorAll(".page").forEach((sec) => {
    sec.classList.toggle("active", sec.id === `page-${page}`);
  });
  const [title, sub] = PAGE_TITLES[page] || ["LoyaltyHub", ""];
  document.getElementById("page-title").textContent = title;
  document.getElementById("page-subtitle").textContent = sub;
  document.getElementById("sidebar").classList.remove("open");

  if (page === "dashboard") loadDashboard();
  if (page === "customers") loadCustomers();
  if (page === "orders") loadOrders();
  if (page === "transactions") loadTransactions();
  if (page === "rewards") loadRewardsPage();
  if (page === "analytics") loadAnalytics();
  if (page === "audit") loadAuditPage();
}

function renderChart(canvasId, type, labels, datasets, options = {}) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (state.charts[canvasId]) {
    state.charts[canvasId].destroy();
    delete state.charts[canvasId];
  }
  if (typeof window.Chart !== "undefined") {
    state.charts[canvasId] = new window.Chart(canvas, {
      type,
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
        ...options,
      },
    });
    return;
  }
  // Offline fallback rendering directly on 2D canvas if Chart.js CDN is unreachable
  const ctx = canvas.getContext("2d");
  const w = (canvas.width = canvas.parentElement.clientWidth || 400);
  const h = (canvas.height = 250);
  ctx.clearRect(0, 0, w, h);
  const vals = datasets[0]?.data || [];
  const maxVal = Math.max(1, ...vals);
  const barW = Math.max(16, (w - 60) / Math.max(1, labels.length) - 10);
  labels.forEach((lbl, idx) => {
    const val = vals[idx] || 0;
    const barH = ((h - 60) * val) / maxVal;
    const x = 40 + idx * (barW + 10);
    const y = h - 35 - barH;
    ctx.fillStyle = "#4f46e5";
    ctx.fillRect(x, y, barW, barH);
    ctx.fillStyle = "#334155";
    ctx.font = "11px sans-serif";
    ctx.fillText(String(lbl).slice(0, 10), x, h - 16);
  });
}

// ==================== 1. DASHBOARD ====================
async function loadDashboard() {
  try {
    const data = await apiFetch("/analytics/dashboard");
    state.dashboardData = data;
    const k = data.kpis;
    document.getElementById("kpi-customers").textContent = fmtNum(k.total_customers);
    document.getElementById("kpi-orders").textContent = fmtNum(k.total_orders);
    document.getElementById("kpi-earned").textContent = fmtNum(k.points_earned);
    document.getElementById("kpi-redeemed").textContent = fmtNum(k.points_redeemed);
    document.getElementById("kpi-expired").textContent = fmtNum(k.points_expired);
    document.getElementById("kpi-liability").textContent = fmtNum(k.outstanding_points_liability);
    document.getElementById("kpi-anomalies").textContent = fmtNum(k.detected_anomalies);
    document.getElementById("kpi-rejected-meta").textContent =
      `${fmtNum(k.rejected_redemptions)} invalid redemption attempts blocked`;

    const months = data.monthly_trends.map((m) => m.month);
    renderChart("dashFlowChart", "bar", months, [
      { label: "Earned", data: data.monthly_trends.map((m) => m.earned), backgroundColor: "#10b981" },
      { label: "Redeemed", data: data.monthly_trends.map((m) => m.redeemed), backgroundColor: "#3b82f6" },
    ]);

    renderChart(
      "dashTierChart",
      "doughnut",
      data.tier_distribution.map((t) => `${t.tier_name} (${fmtNum(t.customer_count)})`),
      [
        {
          data: data.tier_distribution.map((t) => t.customer_count),
          backgroundColor: ["#d97706", "#94a3b8", "#eab308"],
        },
      ]
    );
  } catch (err) {
    showToast(`Dashboard load error: ${err.message}`, "error");
  }
}

// ==================== 2. CUSTOMERS ====================
async function loadCustomers() {
  const search = document.getElementById("cust-search").value.trim();
  const tierId = document.getElementById("cust-tier-filter").value;
  const segment = document.getElementById("cust-segment-filter").value;
  const params = new URLSearchParams({
    limit: state.custLimit,
    offset: state.custOffset,
  });
  if (search) params.set("search", search);
  if (tierId) params.set("tier_id", tierId);
  if (segment) params.set("segment", segment);

  try {
    const data = await apiFetch(`/customers?${params}`);
    state.custTotal = data.total;
    const tbody = document.getElementById("customers-tbody");
    tbody.innerHTML = data.items
      .map(
        (c) => `
      <tr>
        <td class="mono">${escapeHtml(c.customer_id)}</td>
        <td class="mono">${escapeHtml(c.account_id)}</td>
        <td><strong>${escapeHtml(c.full_name)}</strong><br><span class="muted">${escapeHtml(c.email)}</span></td>
        <td>${escapeHtml(c.city || "-")}</td>
        <td><span class="badge badge-muted">${escapeHtml(c.segment)}</span></td>
        <td>${tierBadge(c.tier_name)}</td>
        <td><strong>${fmtNum(c.points_balance)}</strong></td>
        <td>${fmtCur(c.qualifying_spend)}</td>
        <td><button class="btn btn-secondary btn-sm" onclick="openCustomerDetail('${c.customer_id}')">Inspect</button></td>
      </tr>`
      )
      .join("");

    const start = data.total === 0 ? 0 : state.custOffset + 1;
    const end = Math.min(data.total, state.custOffset + data.items.length);
    document.getElementById("cust-page-info").textContent = `Showing ${start}-${end} of ${fmtNum(data.total)} customers`;
    document.getElementById("cust-prev").disabled = state.custOffset === 0;
    document.getElementById("cust-next").disabled = state.custOffset + state.custLimit >= data.total;
  } catch (err) {
    showToast(`Failed to load customers: ${err.message}`, "error");
  }
}

window.openCustomerDetail = async function (customerId) {
  state.selectedCustomerId = customerId;
  try {
    const detail = await apiFetch(`/customers/${customerId}`);
    const c = detail.customer;
    const a = detail.account;
    const txRes = await apiFetch(`/accounts/${a.account_id}/transactions?limit=25`);

    document.getElementById("customer-detail-card").classList.remove("hidden");
    document.getElementById("detail-cust-name").textContent = `${c.full_name} (${c.customer_id})`;
    document.getElementById("detail-cust-meta").textContent = `${c.email} | ${c.city || "N/A"} | Segment: ${c.segment} | Account: ${a.account_id}`;
    document.getElementById("order-cust-id").value = c.customer_id;
    document.getElementById("rdm-account-id").value = a.account_id;

    document.getElementById("detail-account-stats").innerHTML = `
      <div class="stat-pill"><div class="label">Current Balance</div><div class="val">${fmtNum(a.points_balance)} pts</div></div>
      <div class="stat-pill"><div class="label">Membership Tier</div><div class="val">${tierBadge(a.tier_name)} (${a.earn_rate_multiplier}x)</div></div>
      <div class="stat-pill"><div class="label">Qualifying Net Spend</div><div class="val">${fmtCur(a.qualifying_spend)}</div></div>
      <div class="stat-pill"><div class="label">Lifetime Earned</div><div class="val">${fmtNum(a.lifetime_points_earned)}</div></div>
      <div class="stat-pill"><div class="label">Lifetime Redeemed</div><div class="val">${fmtNum(a.lifetime_points_redeemed)}</div></div>
      <div class="stat-pill"><div class="label">Lifetime Expired</div><div class="val">${fmtNum(a.lifetime_points_expired)}</div></div>
    `;

    document.getElementById("detail-tier-history").innerHTML = detail.tier_history
      .map(
        (h) => `
      <tr>
        <td>${statusBadge(h.change_type)}</td>
        <td class="mono">${escapeHtml(h.old_tier_id || "NEW")} &rarr; ${escapeHtml(h.new_tier_id)}</td>
        <td>${fmtCur(h.qualifying_spend_at_change)}</td>
        <td>${escapeHtml(h.reason)}</td>
      </tr>`
      )
      .join("");

    document.getElementById("detail-orders-tbody").innerHTML = detail.recent_orders
      .map(
        (o) => `
      <tr>
        <td class="mono">${o.order_id}</td>
        <td>${fmtCur(o.gross_amount)}</td>
        <td>${fmtCur(o.net_eligible_amount)}</td>
        <td>${fmtCur(o.returned_amount)}</td>
        <td>${statusBadge(o.status)}</td>
        <td>${
          o.status === "COMPLETED" || o.status === "PARTIALLY_RETURNED"
            ? `<button class="btn btn-danger btn-sm" onclick="reverseOrderQuick('${o.order_id}')">Return</button>`
            : "-"
        }</td>
      </tr>`
      )
      .join("");

    document.getElementById("detail-tx-tbody").innerHTML = txRes.items
      .map(
        (t) => `
      <tr>
        <td class="mono">${t.transaction_id}</td>
        <td>${txTypeBadge(t.transaction_type)}</td>
        <td><strong>${t.points_delta > 0 ? "+" : ""}${fmtNum(t.points_delta)}</strong></td>
        <td>${fmtNum(t.balance_after)}</td>
        <td class="mono">${t.order_id || t.redemption_id || t.expiry_batch_id || "-"}</td>
      </tr>`
      )
      .join("");

    document.getElementById("customer-detail-card").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    showToast(`Detail load error: ${err.message}`, "error");
  }
};

window.reverseOrderQuick = async function (orderId) {
  try {
    const res = await apiFetch("/points/reverse", {
      method: "POST",
      body: JSON.stringify({ order_id: orderId, reason: "Customer return from dashboard" }),
    });
    showToast(`Reversed ${res.points_reversed} pts for ${orderId}`, "success");
    if (state.selectedCustomerId) openCustomerDetail(state.selectedCustomerId);
    loadCustomers();
  } catch (err) {
    showToast(`Reversal rejected: ${err.message}`, "error");
  }
};

// ==================== 2B. ORDERS ====================
function _setOrdersLoadingState(isLoading, fromRefresh = false) {
  const refreshBtn = document.getElementById("btn-refresh-all");
  const searchBtn = document.getElementById("btn-ord-search");
  const prevBtn = document.getElementById("ord-prev");
  const nextBtn = document.getElementById("ord-next");
  const badge = document.getElementById("ord-total-badge");

  if (refreshBtn) {
    refreshBtn.disabled = isLoading;
    if (isLoading) {
      refreshBtn.textContent = "Refreshing...";
      refreshBtn.setAttribute("aria-busy", "true");
    } else {
      refreshBtn.textContent = "Refresh Data";
      refreshBtn.removeAttribute("aria-busy");
    }
  }
  if (searchBtn) searchBtn.disabled = isLoading;

  if (isLoading) {
    if (prevBtn) prevBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = true;
    if (badge) badge.textContent = fromRefresh ? "Refreshing..." : "Loading...";
  } else {
    if (prevBtn) prevBtn.disabled = state.ordOffset === 0;
    if (nextBtn) nextBtn.disabled = state.ordOffset + state.ordLimit >= state.ordTotal;
  }
}

async function loadOrders({ resetPage = false, fromRefresh = false } = {}) {
  if (state.ordersLoading) return;

  state.ordersLoading = true;
  if (resetPage) state.ordOffset = 0;

  const errBox = document.getElementById("ord-error-box");
  if (errBox) {
    errBox.textContent = "";
    errBox.classList.add("hidden");
  }

  _setOrdersLoadingState(true, fromRefresh);

  const search = document.getElementById("ord-search").value.trim();
  const status = document.getElementById("ord-status-filter").value;
  const customerId = document.getElementById("ord-customer-filter").value.trim();
  const params = new URLSearchParams({
    limit: state.ordLimit,
    offset: state.ordOffset,
  });
  if (search) params.set("search", search);
  if (status) params.set("status", status);
  if (customerId) params.set("customer_id", customerId);

  try {
    const data = await apiFetch(`/orders?${params}`, { cache: "no-store" });
    state.ordTotal = data.total;
    document.getElementById("ord-total-badge").textContent = `${fmtNum(data.total)} orders`;
    const tbody = document.getElementById("orders-tbody");
    tbody.innerHTML = data.items
      .map(
        (o) => `
      <tr>
        <td class="mono">${escapeHtml(o.order_id)}</td>
        <td><strong>${escapeHtml(o.customer_name || "-")}</strong><br><span class="muted mono">${escapeHtml(o.customer_id)}</span></td>
        <td class="mono">${escapeHtml(o.order_date)}</td>
        <td>${fmtCur(o.total_amount ?? o.gross_amount)}</td>
        <td>${fmtCur(o.eligible_amount ?? o.net_eligible_amount)}</td>
        <td><strong>${fmtNum(o.points_earned)}</strong>${o.points_reversed > 0 ? `<br><span class="muted">-${fmtNum(o.points_reversed)} reversed</span>` : ""}</td>
        <td>${statusBadge(o.status)}</td>
        <td><button class="btn btn-secondary btn-sm" onclick="openOrderDetail('${escapeHtml(o.order_id)}')">View Details</button></td>
      </tr>`
      )
      .join("");

    const start = data.total === 0 ? 0 : state.ordOffset + 1;
    const end = Math.min(data.total, state.ordOffset + data.items.length);
    document.getElementById("ord-page-info").textContent = `Showing ${start}-${end} of ${fmtNum(data.total)} orders`;

    if (fromRefresh) {
      showToast(`Orders refreshed (${fmtNum(data.total)} orders)`, "success");
    }
  } catch (err) {
    document.getElementById("ord-total-badge").textContent = "Error loading orders";
    const msg = `Unable to refresh orders: ${err.message}. Check that the backend API (${API_BASE || window.location.origin}) is running and try again.`;
    if (errBox) {
      errBox.textContent = msg;
      errBox.classList.remove("hidden");
    }
    showToast(`Failed to load orders: ${err.message}`, "error");
  } finally {
    state.ordersLoading = false;
    _setOrdersLoadingState(false, fromRefresh);
  }
}

window.openOrderDetail = async function (orderId) {
  state.selectedOrderId = orderId;
  try {
    const detail = await apiFetch(`/orders/${encodeURIComponent(orderId)}`);
    const o = detail.order;
    const ret = detail.return_info || {};

    document.getElementById("order-detail-card").classList.remove("hidden");
    document.getElementById("detail-ord-title").textContent = `Order ${o.order_id}`;
    document.getElementById("detail-ord-meta").textContent =
      `Customer: ${o.customer_name || "-"} (${o.customer_id}) | Account: ${o.account_id || "N/A"} | Date: ${o.order_date} | Status: ${o.status}`;

    document.getElementById("detail-order-stats").innerHTML = `
      <div class="stat-pill"><div class="label">Total Amount</div><div class="val">${fmtCur(o.total_amount ?? o.gross_amount)}</div></div>
      <div class="stat-pill"><div class="label">Eligible Amount</div><div class="val">${fmtCur(o.eligible_amount ?? o.net_eligible_amount)}</div></div>
      <div class="stat-pill"><div class="label">Discount / Tax</div><div class="val">${fmtCur(o.discount_amount)} / ${fmtCur(o.tax_amount)}</div></div>
      <div class="stat-pill"><div class="label">Points Earned</div><div class="val">${fmtNum(o.points_earned)} pts</div></div>
      <div class="stat-pill"><div class="label">Points Reversed</div><div class="val">${fmtNum(o.points_reversed)} pts</div></div>
      <div class="stat-pill"><div class="label">Net Points</div><div class="val">${fmtNum(o.net_points)} pts</div></div>
    `;

    const retBox = document.getElementById("detail-ord-return-info");
    const hasReturns = Number(ret.returned_amount || 0) > 0 || Number(ret.points_reversed || 0) > 0;
    retBox.className = `result-box ${hasReturns ? "warn" : "ok"}`;
    retBox.textContent =
      `Return Summary — Status: ${ret.status || o.status} | Returned Amount: ${fmtCur(ret.returned_amount)} | Remaining Returnable: ${fmtCur(ret.remaining_returnable_amount)} | Points Earned: ${fmtNum(ret.points_earned)} pts | Points Reversed: ${fmtNum(ret.points_reversed)} pts | Net Points: ${fmtNum(ret.net_points)} pts`;
    retBox.classList.remove("hidden");

    document.getElementById("detail-ord-lines-tbody").innerHTML =
      detail.lines.length > 0
        ? detail.lines
            .map(
              (line) => `
          <tr>
            <td class="mono">${escapeHtml(line.sku)}<br><span class="muted">${escapeHtml(line.order_line_id)}</span></td>
            <td>${escapeHtml(line.product_name)}</td>
            <td>${escapeHtml(line.category)}</td>
            <td>${fmtNum(line.quantity)}</td>
            <td>${fmtCur(line.unit_price)}</td>
            <td>${fmtCur(line.line_net_amount)}${line.is_points_eligible ? "" : '<br><span class="muted">Excluded</span>'}</td>
            <td>${fmtNum(line.returned_quantity)}</td>
            <td>${statusBadge(line.status)}</td>
          </tr>`
            )
            .join("")
        : `<tr><td colspan="8" class="muted">No order line items recorded.</td></tr>`;

    document.getElementById("detail-ord-tx-tbody").innerHTML =
      detail.transactions.length > 0
        ? detail.transactions
            .map(
              (tx) => `
          <tr>
            <td class="mono">${escapeHtml(tx.transaction_id)}</td>
            <td>${txTypeBadge(tx.transaction_type)}</td>
            <td><strong>${tx.points_delta > 0 ? "+" : ""}${fmtNum(tx.points_delta)}</strong></td>
            <td>${fmtNum(tx.balance_after)}</td>
            <td>${statusBadge(tx.status)}</td>
            <td class="mono">${escapeHtml(tx.created_at)}</td>
          </tr>`
            )
            .join("")
        : `<tr><td colspan="6" class="muted">No points transactions linked to this order.</td></tr>`;

    document.getElementById("order-detail-card").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    showToast(`Order detail error: ${err.message}`, "error");
  }
};

// ==================== 3. TRANSACTIONS ====================
async function loadTransactions() {
  const search = document.getElementById("tx-search").value.trim();
  const txType = document.getElementById("tx-type-filter").value;
  const params = new URLSearchParams({
    limit: state.txLimit,
    offset: state.txOffset,
  });
  if (search) params.set("search", search);
  if (txType) params.set("transaction_type", txType);

  try {
    const data = await apiFetch(`/transactions?${params}`);
    state.txTotal = data.total;
    document.getElementById("tx-total-badge").textContent = `${fmtNum(data.total)} records`;
    document.getElementById("tx-tbody").innerHTML = data.items
      .map(
        (t) => `
      <tr>
        <td class="mono">${t.transaction_id}</td>
        <td class="mono">${t.account_id}</td>
        <td>${txTypeBadge(t.transaction_type)}</td>
        <td><strong>${t.points_delta > 0 ? "+" : ""}${fmtNum(t.points_delta)}</strong></td>
        <td>${fmtNum(t.balance_after)}</td>
        <td>${statusBadge(t.status)}</td>
        <td class="mono">${[t.order_id, t.redemption_id, t.expiry_batch_id, t.reference_transaction_id].filter(Boolean).join(" / ") || "-"}</td>
        <td class="mono">${t.created_at}</td>
      </tr>`
      )
      .join("");

    const start = data.total === 0 ? 0 : state.txOffset + 1;
    const end = Math.min(data.total, state.txOffset + data.items.length);
    document.getElementById("tx-page-info").textContent = `Showing ${start}-${end} of ${fmtNum(data.total)}`;
    document.getElementById("tx-prev").disabled = state.txOffset === 0;
    document.getElementById("tx-next").disabled = state.txOffset + state.txLimit >= data.total;
  } catch (err) {
    showToast(`Failed to load transactions: ${err.message}`, "error");
  }
}

// ==================== 4. REWARDS ====================
async function loadRewardsPage() {
  try {
    const [rwData, rdmData] = await Promise.all([
      apiFetch("/rewards"),
      apiFetch(`/redemptions?limit=30&status=${encodeURIComponent(document.getElementById("rdm-status-filter").value)}`),
    ]);

    const select = document.getElementById("rdm-reward-id");
    const prevVal = select.value;
    select.innerHTML = rwData.items
      .map(
        (r) =>
          `<option value="${r.reward_id}">${r.reward_name} — ${fmtNum(r.points_required)} pts (Min Tier ${r.min_tier_level})</option>`
      )
      .join("");
    if (prevVal) select.value = prevVal;

    document.getElementById("rewards-grid").innerHTML = rwData.items
      .map(
        (r) => `
      <div class="reward-item">
        <div>
          <span class="badge badge-muted">${r.category}</span>
          <h4 style="margin:6px 0 4px">${r.reward_name}</h4>
          <p class="muted">${r.description || ""}</p>
        </div>
        <div>
          <div class="reward-pts">${fmtNum(r.points_required)} pts</div>
          <div class="muted">Min Tier Level: ${r.min_tier_level} | Stock: ${fmtNum(r.stock_quantity)}</div>
        </div>
      </div>`
      )
      .join("");

    document.getElementById("rdm-history-tbody").innerHTML = rdmData.items
      .map(
        (r) => `
      <tr>
        <td class="mono">${r.redemption_id}</td>
        <td class="mono">${r.account_id}</td>
        <td>${r.reward_name}</td>
        <td>${fmtNum(r.points_used)}</td>
        <td>${statusBadge(r.status)}</td>
        <td class="muted">${r.failure_reason || "-"}</td>
        <td class="mono">${r.redeemed_at}</td>
      </tr>`
      )
      .join("");
  } catch (err) {
    showToast(`Failed to load rewards: ${err.message}`, "error");
  }
}

// ==================== 5. ANALYTICS ====================
async function loadAnalytics() {
  try {
    const [data, segData] = await Promise.all([
      apiFetch("/analytics/dashboard"),
      apiFetch("/analytics/segments"),
    ]);
    const k = data.kpis;
    renderChart(
      "anaEarnedRedeemedChart",
      "bar",
      ["Points Earned", "Points Redeemed", "Points Reversed", "Points Expired", "Liability"],
      [
        {
          label: "Points Volume",
          data: [k.points_earned, k.points_redeemed, k.points_reversed, k.points_expired, k.outstanding_points_liability],
          backgroundColor: ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#6366f1"],
        },
      ]
    );

    const months = data.monthly_trends.map((m) => m.month);
    renderChart("anaMonthlyTrendChart", "line", months, [
      { label: "Earned", data: data.monthly_trends.map((m) => m.earned), borderColor: "#10b981", tension: 0.25 },
      { label: "Redeemed", data: data.monthly_trends.map((m) => m.redeemed), borderColor: "#3b82f6", tension: 0.25 },
      { label: "Expired", data: data.monthly_trends.map((m) => m.expired), borderColor: "#ef4444", tension: 0.25 },
    ]);

    renderChart(
      "anaTierDistChart",
      "doughnut",
      data.tier_distribution.map((t) => `${t.tier_name} (${fmtNum(t.customer_count)})`),
      [{ data: data.tier_distribution.map((t) => t.customer_count), backgroundColor: ["#d97706", "#94a3b8", "#eab308"] }]
    );

    renderChart(
      "anaExpiryChart",
      "bar",
      data.expiry_analysis.map((e) => e.status),
      [
        {
          label: "Batch Count",
          data: data.expiry_analysis.map((e) => e.batch_count),
          backgroundColor: ["#10b981", "#6366f1", "#3b82f6", "#ef4444"],
        },
      ]
    );

    const anomEntries = Object.entries(data.anomaly_distribution || {});
    renderChart(
      "anaAnomalyChart",
      "bar",
      anomEntries.map(([key]) => key),
      [
        {
          label: "Detected Cases",
          data: anomEntries.map(([, val]) => val),
          backgroundColor: "#ef4444",
        },
      ]
    );

    document.getElementById("ana-segments-tbody").innerHTML = (segData.items || [])
      .map(
        (s) => `
      <tr>
        <td><span class="badge badge-indigo">${escapeHtml(s.segment)}</span></td>
        <td>${fmtNum(s.customers)}</td>
        <td>${fmtNum(s.avg_points_balance)}</td>
        <td>${fmtNum(s.total_points_earned)}</td>
        <td>${s.redemption_rate_pct}%</td>
        <td>${fmtCur(s.avg_qualifying_spend)}</td>
        <td>${fmtCur(s.median_qualifying_spend)}</td>
        <td>${fmtCur(s.p90_qualifying_spend)}</td>
      </tr>`
      )
      .join("");
  } catch (err) {
    showToast(`Analytics error: ${err.message}`, "error");
  }
}

// ==================== 6. AUDIT & VALIDATION ====================
function _setAuditLoadingState(isLoading) {
  const rerunBtn = document.getElementById("btn-rerun-audit");
  const filterSelect = document.getElementById("audit-type-filter");
  const exportBtn = document.getElementById("btn-export-audit");
  const reconBadge = document.getElementById("recon-badge");

  if (rerunBtn) {
    rerunBtn.disabled = isLoading;
    if (isLoading) {
      rerunBtn.textContent = "Scanning...";
      rerunBtn.setAttribute("aria-busy", "true");
    } else {
      rerunBtn.textContent = "Re-run Audit Scan";
      rerunBtn.removeAttribute("aria-busy");
    }
  }
  if (filterSelect) filterSelect.disabled = isLoading;
  if (exportBtn) exportBtn.disabled = isLoading;
  if (isLoading && reconBadge) {
    reconBadge.textContent = "Scanning...";
    reconBadge.className = "badge badge-amber";
  }
}

async function loadAuditPage({ isManualScan = false } = {}) {
  if (state.auditLoading) return;
  state.auditLoading = true;

  const statusBox = document.getElementById("audit-status-box");
  if (statusBox) {
    statusBox.textContent = "";
    statusBox.className = "result-box hidden";
  }

  _setAuditLoadingState(true);
  const issueType = document.getElementById("audit-type-filter").value;

  try {
    const [recon, anomalies] = await Promise.all([
      apiFetch("/audit/reconciliation", { cache: "no-store" }),
      apiFetch(`/audit/anomalies${issueType ? `?issue_type=${encodeURIComponent(issueType)}` : ""}`, {
        cache: "no-store",
      }),
    ]);
    state.anomaliesData = anomalies;

    document.getElementById("audit-kpis").innerHTML = `
      <div class="kpi-card accent-indigo"><div class="kpi-label">Accounts Audited</div><div class="kpi-value">${fmtNum(recon.total_accounts_checked)}</div></div>
      <div class="kpi-card accent-green"><div class="kpi-label">Clean Reconciled</div><div class="kpi-value">${fmtNum(recon.matched_accounts)}</div></div>
      <div class="kpi-card accent-red"><div class="kpi-label">Balance Mismatches</div><div class="kpi-value">${fmtNum(recon.mismatched_accounts_count)}</div></div>
      <div class="kpi-card accent-amber"><div class="kpi-label">Total Anomalies</div><div class="kpi-value">${fmtNum(anomalies.total_anomalies)}</div></div>
      <div class="kpi-card accent-blue"><div class="kpi-label">Net Variance (pts)</div><div class="kpi-value">${fmtNum(recon.net_reconciliation_variance)}</div></div>
    `;

    const reconBadge = document.getElementById("recon-badge");
    reconBadge.textContent = recon.is_reconciled ? "RECONCILED" : `${recon.mismatched_accounts_count} MISMATCHES`;
    reconBadge.className = `badge ${recon.is_reconciled ? "badge-green" : "badge-red"}`;

    document.getElementById("recon-tbody").innerHTML = recon.mismatches.length
      ? recon.mismatches
          .map(
            (m) => `
          <tr>
            <td class="mono">${escapeHtml(m.account_id)}</td>
            <td>${fmtNum(m.stored_balance)}</td>
            <td>${fmtNum(m.ledger_balance)}</td>
            <td><strong>${m.discrepancy > 0 ? "+" : ""}${fmtNum(m.discrepancy)}</strong></td>
          </tr>`
          )
          .join("")
      : `<tr><td colspan="4" class="muted">All accounts match the immutable ledger sum!</td></tr>`;

    document.getElementById("rejected-attempts-badge").textContent = fmtNum(
      anomalies.rejected_redemption_attempts_count
    );
    document.getElementById("rejected-attempts-tbody").innerHTML = anomalies.rejected_redemption_attempts
      .slice(0, 50)
      .map(
        (r) => `
      <tr>
        <td class="mono">${escapeHtml(r.redemption_id)}</td>
        <td class="mono">${escapeHtml(r.account_id)}</td>
        <td>${fmtNum(r.points_used)}</td>
        <td>${escapeHtml(r.failure_reason)}</td>
      </tr>`
      )
      .join("");

    document.getElementById("anomalies-tbody").innerHTML = anomalies.anomalies.length
      ? anomalies.anomalies
          .map(
            (a) => `
          <tr>
            <td class="mono">${escapeHtml(a.record_id)}</td>
            <td>${escapeHtml(a.record_type)}</td>
            <td class="mono">${escapeHtml(a.issue_type)}</td>
            <td>${statusBadge(a.severity)}</td>
            <td class="mono">${escapeHtml(a.expected_value)}</td>
            <td class="mono">${escapeHtml(a.actual_value)}</td>
            <td>${escapeHtml(a.details)}</td>
          </tr>`
          )
          .join("")
      : `<tr><td colspan="7" class="muted">No anomalies detected for the selected filter.</td></tr>`;

    if (isManualScan) {
      if (statusBox) {
        statusBox.className = "result-box ok";
        statusBox.textContent =
          `Audit scan completed: ${fmtNum(recon.total_accounts_checked)} accounts checked, ` +
          `${fmtNum(anomalies.total_anomalies)} total anomalies detected ` +
          `(${fmtNum(recon.mismatched_accounts_count)} balance mismatches).`;
      }
      showToast(
        `Audit scan complete (${fmtNum(anomalies.total_anomalies)} anomalies, ${fmtNum(recon.mismatched_accounts_count)} mismatches)`,
        "success"
      );
    }
  } catch (err) {
    const reconBadge = document.getElementById("recon-badge");
    if (reconBadge) {
      reconBadge.textContent = "Scan Failed";
      reconBadge.className = "badge badge-red";
    }
    if (statusBox) {
      statusBox.className = "result-box err";
      statusBox.textContent =
        `Audit scan failed: ${err.message}. Check that the backend API (${API_BASE || window.location.origin}) is running and try again.`;
    }
    showToast(`Audit error: ${err.message}`, "error");
  } finally {
    state.auditLoading = false;
    _setAuditLoadingState(false);
  }
}

// ==================== EVENT WIRING ====================
document.addEventListener("DOMContentLoaded", () => {
  // Configure cross-port links when frontend runs on 5500 & backend on 8001
  const swaggerLink = document.getElementById("swagger-docs-link");
  if (swaggerLink) swaggerLink.href = `${API_BASE}/docs`;
  const exportLink = document.getElementById("export-segments-link");
  if (exportLink) exportLink.href = `${API_BASE}/analytics/export`;

  // Navigation
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => navigateTo(btn.dataset.page));
  });
  document.querySelectorAll(".quick-btn").forEach((btn) => {
    btn.addEventListener("click", () => navigateTo(btn.dataset.goto));
  });
  document.getElementById("kpi-anomalies-card").addEventListener("click", () => navigateTo("audit"));
  document.getElementById("menu-toggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("open");
  });

  // Topbar actions
  document.getElementById("btn-refresh-all").addEventListener("click", () => {
    if (state.currentPage === "orders" || document.getElementById("page-orders")?.classList.contains("active")) {
      return loadOrders({ resetPage: true, fromRefresh: true });
    }
    return navigateTo(state.currentPage);
  });
  document.getElementById("btn-run-expire").addEventListener("click", async () => {
    try {
      const res = await apiFetch("/points/expire", {
        method: "POST",
        body: JSON.stringify({ as_of_date: "2026-11-11T23:59:59" }),
      });
      showToast(
        `Expiry job finished: ${res.batches_expired} lots expired (${fmtNum(res.total_points_expired)} pts)`,
        "success"
      );
      navigateTo(state.currentPage);
    } catch (err) {
      showToast(`Expiry job failed: ${err.message}`, "error");
    }
  });

  // Customers controls
  document.getElementById("btn-cust-search").addEventListener("click", () => {
    state.custOffset = 0;
    loadCustomers();
  });
  document.getElementById("cust-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      state.custOffset = 0;
      loadCustomers();
    }
  });
  document.getElementById("cust-tier-filter").addEventListener("change", () => {
    state.custOffset = 0;
    loadCustomers();
  });
  document.getElementById("cust-segment-filter").addEventListener("change", () => {
    state.custOffset = 0;
    loadCustomers();
  });
  document.getElementById("cust-prev").addEventListener("click", () => {
    state.custOffset = Math.max(0, state.custOffset - state.custLimit);
    loadCustomers();
  });
  document.getElementById("cust-next").addEventListener("click", () => {
    state.custOffset += state.custLimit;
    loadCustomers();
  });
  document.getElementById("btn-close-detail").addEventListener("click", () => {
    document.getElementById("customer-detail-card").classList.add("hidden");
  });

  // Register Customer modal
  const modal = document.getElementById("modal-new-customer");
  document.getElementById("btn-open-new-cust").addEventListener("click", () => modal.classList.remove("hidden"));
  document.getElementById("btn-close-modal").addEventListener("click", () => modal.classList.add("hidden"));
  document.getElementById("form-new-customer").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const created = await apiFetch("/customers", {
        method: "POST",
        body: JSON.stringify({
          full_name: document.getElementById("new-cust-name").value,
          email: document.getElementById("new-cust-email").value,
          phone: document.getElementById("new-cust-phone").value || null,
          city: document.getElementById("new-cust-city").value || null,
          segment: document.getElementById("new-cust-segment").value,
        }),
      });
      modal.classList.add("hidden");
      e.target.reset();
      showToast(`Registered ${created.customer_id} (${created.account_id})`, "success");
      loadCustomers();
      openCustomerDetail(created.customer_id);
    } catch (err) {
      showToast(`Registration failed: ${err.message}`, "error");
    }
  });

  // Quick Order & Accrual form
  document.getElementById("form-quick-order").addEventListener("submit", async (e) => {
    e.preventDefault();
    const customerId = document.getElementById("order-cust-id").value;
    try {
      const res = await apiFetch("/orders", {
        method: "POST",
        body: JSON.stringify({
          customer_id: customerId,
          auto_accrue: true,
          lines: [
            {
              sku: "SKU-WEB-100",
              product_name: document.getElementById("order-product").value,
              category: "Retail",
              quantity: Number(document.getElementById("order-qty").value),
              unit_price: Number(document.getElementById("order-price").value),
              discount_amount: Number(document.getElementById("order-discount").value),
              is_points_eligible: document.getElementById("order-eligible").value === "true",
            },
          ],
        }),
      });
      const pts = res.accrual ? res.accrual.points_earned : 0;
      showToast(`Order ${res.order_id} created (+${fmtNum(pts)} pts)`, "success");
      openCustomerDetail(customerId);
      loadCustomers();
    } catch (err) {
      showToast(`Order error: ${err.message}`, "error");
    }
  });

  // Orders page controls
  document.getElementById("btn-ord-search").addEventListener("click", () => {
    state.ordOffset = 0;
    loadOrders();
  });
  document.getElementById("ord-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      state.ordOffset = 0;
      loadOrders();
    }
  });
  document.getElementById("ord-customer-filter").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      state.ordOffset = 0;
      loadOrders();
    }
  });
  document.getElementById("ord-status-filter").addEventListener("change", () => {
    state.ordOffset = 0;
    loadOrders();
  });
  document.getElementById("ord-prev").addEventListener("click", () => {
    state.ordOffset = Math.max(0, state.ordOffset - state.ordLimit);
    loadOrders();
  });
  document.getElementById("ord-next").addEventListener("click", () => {
    state.ordOffset += state.ordLimit;
    loadOrders();
  });
  document.getElementById("btn-close-order-detail").addEventListener("click", () => {
    document.getElementById("order-detail-card").classList.add("hidden");
  });

  // Transactions page controls
  document.getElementById("btn-tx-search").addEventListener("click", () => {
    state.txOffset = 0;
    loadTransactions();
  });
  document.getElementById("tx-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      state.txOffset = 0;
      loadTransactions();
    }
  });
  document.getElementById("tx-type-filter").addEventListener("change", () => {
    state.txOffset = 0;
    loadTransactions();
  });
  document.getElementById("tx-prev").addEventListener("click", () => {
    state.txOffset = Math.max(0, state.txOffset - state.txLimit);
    loadTransactions();
  });
  document.getElementById("tx-next").addEventListener("click", () => {
    state.txOffset += state.txLimit;
    loadTransactions();
  });

  document.getElementById("form-reverse-order").addEventListener("submit", async (e) => {
    e.preventDefault();
    const amtRaw = document.getElementById("rev-amount").value;
    try {
      const res = await apiFetch("/points/reverse", {
        method: "POST",
        body: JSON.stringify({
          order_id: document.getElementById("rev-order-id").value.trim(),
          return_amount: amtRaw ? Number(amtRaw) : null,
          reason: document.getElementById("rev-reason").value.trim(),
        }),
      });
      showToast(`Reversed ${fmtNum(res.points_reversed)} pts on ${res.order_id}`, "success");
      loadTransactions();
    } catch (err) {
      showToast(`Reversal error: ${err.message}`, "error");
    }
  });

  document.getElementById("form-expire-batch").addEventListener("submit", async (e) => {
    e.preventDefault();
    const acc = document.getElementById("exp-account-id").value.trim();
    try {
      const res = await apiFetch("/points/expire", {
        method: "POST",
        body: JSON.stringify({
          as_of_date: document.getElementById("exp-cutoff").value.trim(),
          account_id: acc || null,
        }),
      });
      showToast(`Expired ${res.batches_expired} lots (${fmtNum(res.total_points_expired)} pts)`, "success");
      loadTransactions();
    } catch (err) {
      showToast(`Expiration error: ${err.message}`, "error");
    }
  });

  // Rewards redemption form
  document.getElementById("form-redeem").addEventListener("submit", async (e) => {
    e.preventDefault();
    const box = document.getElementById("rdm-result-box");
    const idem = document.getElementById("rdm-idem-key").value.trim();
    try {
      const res = await apiFetch("/redemptions", {
        method: "POST",
        body: JSON.stringify({
          account_id: document.getElementById("rdm-account-id").value.trim(),
          reward_id: document.getElementById("rdm-reward-id").value,
          quantity: Number(document.getElementById("rdm-quantity").value),
          idempotency_key: idem || null,
        }),
      });
      box.className = "result-box ok";
      box.textContent = `Success! ${res.redemption_id} completed — ${fmtNum(res.points_redeemed)} pts deducted. Remaining balance: ${fmtNum(res.remaining_balance)} pts.`;
      box.classList.remove("hidden");
      showToast("Reward redeemed successfully!", "success");
      loadRewardsPage();
    } catch (err) {
      box.className = "result-box err";
      box.textContent = `Rejected (${err.status}): ${err.message}`;
      box.classList.remove("hidden");
      showToast(`Redemption rejected: ${err.message}`, "error");
      loadRewardsPage();
    }
  });

  document.getElementById("rdm-status-filter").addEventListener("change", loadRewardsPage);

  // Audit controls
  document.getElementById("audit-type-filter").addEventListener("change", () => loadAuditPage());
  document.getElementById("btn-rerun-audit").addEventListener("click", () => loadAuditPage({ isManualScan: true }));
  document.getElementById("btn-export-audit").addEventListener("click", () => {
    if (!state.anomaliesData) return;
    const blob = new Blob([JSON.stringify(state.anomaliesData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "loyalty_audit_anomalies.json";
    a.click();
    URL.revokeObjectURL(url);
  });

  // Initial load
  loadDashboard();
});
