function renderWeeklySalesChart(list, days) {
  if (!Array.isArray(days) || days.length !== 7 ||
      days.some(day => !/^\d{4}-\d{2}-\d{2}$/.test(day.date) ||
        (day.amount !== null && (!Number.isFinite(day.amount) || day.amount < 0)))) {
    throw new Error("每日營業額資料不正確，請確認後端服務已更新。");
  }
  const maximum = Math.max(0, ...days.map(day => day.amount === null ? 0 : day.amount));
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  list.replaceChildren(...days.map((day, index) => {
    const item = document.createElement("li");
    item.className = "daily-sales-item";
    const date = document.createElement("time");
    date.dateTime = day.date;
    date.textContent = `${day.date.slice(5).replace("-", "/")} 週${weekdays[index]}`;
    const track = document.createElement("span");
    track.className = "daily-sales-track";
    track.setAttribute("aria-hidden", "true");
    const bar = document.createElement("span");
    bar.className = "daily-sales-bar";
    bar.style.width = `${maximum && day.amount !== null ? day.amount / maximum * 100 : 0}%`;
    track.append(bar);
    const amount = document.createElement("span");
    amount.className = "daily-sales-amount";
    amount.textContent = day.amount === null ? "尚未到" : `NT$ ${day.amount.toLocaleString("zh-TW")}`;
    item.append(date, track, amount);
    return item;
  }));
}
