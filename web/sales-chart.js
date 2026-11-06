function renderSalesChart(container, sales) {
  const periods = ["today", "week", "month"];
  if (!sales || periods.some(period => !Number.isFinite(sales[period]) || sales[period] < 0)) {
    throw new Error("營業額資料不正確。");
  }
  const maximum = Math.max(...periods.map(period => sales[period]));
  for (const period of periods) {
    const metric = container.querySelector(`[data-period="${period}"]`);
    const amount = sales[period];
    metric.querySelector("strong").textContent = `NT$ ${amount.toLocaleString("zh-TW")}`;
    metric.querySelector(".sales-bar").style.width = `${maximum ? amount / maximum * 100 : 0}%`;
  }
}
