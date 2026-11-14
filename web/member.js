const $ = selector => document.querySelector(selector);
const message = text => { $("#memberMessage").textContent = text; };
let offset = 0;
const pageSize = 20;
const labels = {earn:"消費累點", redeem:"點數折抵", expire:"點數到期", reversal:"交易沖銷", adjustment:"人工調整"};

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: {Accept:"application/json", ...(options.body ? {"Content-Type":"application/json"} : {})} });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "操作失敗，請確認資料後重試。");
  return data;
}

async function refreshSession() {
  try {
    const session = await api("/api/members/session");
    $("#authSection").hidden = session.authenticated;
    $("#pointsSection").hidden = !session.authenticated;
    $("#clearSession").hidden = true;
    if (session.authenticated) {
      $("#memberIdentity").textContent = `會員手機末四碼：${session.phone}`;
      await refreshPoints();
    }
  } catch (error) {
    $("#authSection").hidden = false;
    $("#pointsSection").hidden = true;
    $("#clearSession").hidden = false;
    message(error.message);
  }
}

async function refreshPoints() {
  const data = await api("/api/members/me/points");
  $("#pointsBalance").textContent = data.available_points.toLocaleString("zh-TW");
  const list = $("#expiringList");
  list.replaceChildren();
  for (const item of data.expiring) {
    const row = document.createElement("li");
    row.textContent = `${new Date(item.expires_at).toLocaleString("zh-TW", {timeZone:"Asia/Taipei"})}：${item.points} 點`;
    list.append(row);
  }
  if (!data.expiring.length) list.textContent = "未來 30 天沒有到期點數。";
  offset = 0;
  $("#transactionsList").replaceChildren();
  await loadTransactions();
}

async function loadTransactions() {
  const data = await api(`/api/members/me/points/transactions?limit=${pageSize}&offset=${offset}`);
  const list = $("#transactionsList");
  for (const item of data.transactions) {
    const row = document.createElement("li");
    if (item.kind === "redeem") row.classList.add("transaction-redeem");
    const time = new Date(item.created_at).toLocaleString("zh-TW", {timeZone:"Asia/Taipei"});
    row.textContent = `${time} · ${labels[item.kind] || item.kind} · ${item.points_delta > 0 ? "+" : ""}${item.points_delta} 點${item.order_id ? ` · 訂單 ${item.order_id}` : ""}`;
    list.append(row);
  }
  offset += data.transactions.length;
  $("#loadMore").hidden = !data.has_more;
  if (!offset) list.textContent = "目前沒有點數異動。";
}

for (const [formId, action] of [["loginForm", "login"], ["registerForm", "register"]]) {
  $(`#${formId}`).addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      const payload = Object.fromEntries(new FormData(form));
      const result = await api(`/api/members/${action}`, {method:"POST", body:JSON.stringify(payload)});
      form.reset();
      message(result.message);
      if (action === "login") await refreshSession();
    } catch (error) { message(error.message); }
    finally { button.disabled = false; }
  });
}

async function logout() {
  try {
    await api("/api/members/logout", {method:"POST"});
    message("已登出，可直接以訪客身分點餐。");
    await refreshSession();
  } catch (error) { message(error.message); }
}
$("#logoutButton").addEventListener("click", logout);
$("#clearSession").addEventListener("click", logout);
$("#loadMore").addEventListener("click", async () => {
  try { await loadTransactions(); } catch (error) { message(error.message); }
});
refreshSession();
