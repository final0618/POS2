function renderTableHeatmap(list, summary, tables) {
  if (!Array.isArray(tables)) {
    throw new Error("桌次熱區資料未提供，請確認後端服務已更新。");
  }
  const maximum = Math.max(0, ...tables.map(table => table.order_count));
  const leaders = tables.filter(table => maximum > 0 && table.order_count === maximum);
  summary.textContent = leaders.length
    ? `最多下單：${leaders.map(table => `${table.table_number} 桌`).join("、")}，各 ${maximum} 單`
    : "本月尚無有效訂單";
  list.replaceChildren(...tables.map(table => {
    const item = document.createElement("li");
    item.className = "table-heatmap-item";
    const level = table.order_count === 0 ? 0 : Math.ceil(table.order_count / maximum * 4);
    item.dataset.heat = String(level);
    const label = document.createElement("strong");
    label.textContent = `${table.table_number} 桌`;
    const count = document.createElement("span");
    count.textContent = `${table.order_count} 單`;
    item.append(label, count);
    return item;
  }));
}
