/* One cursor and keyboard control for daily totals. */
window.renderVisibilityTrend = (container, report, selectedDate) => {
 const rows = report.trend;
 if (!report.totals.samples || !rows.length){
  container.innerHTML = '<div class="dashboard-trend-empty"><p class="dashboard-empty-copy">当前范围暂无符合口径的回答。可调整时间、范围或平台。</p></div>';
  return;
 }
 const series = [
  {key:'samples', label:'计入样本', color:'#8ed7ff', style:'samples', dash:''},
  {key:'brand_mentions', label:'提及品牌', color:'#baa9ff', style:'brand', dash:'7 4'},
  {key:'company_mentions', label:'提及企业', color:'#77ddc5', style:'company', dash:'2 4'},
  {key:'official_links', label:'官网链接', color:'#f5c48a', style:'links', dash:'9 4 2 4'},
 ];
 const width = 620, height = 200, left = 40, right = 28, top = 16, bottom = 27;
 const ceiling = Math.max(4, Math.ceil(Math.max(...rows.map(row => row.samples)) / 4) * 4);
 const span = width - left - right;
 const x = i => left + span * (rows.length === 1 ? .5 : i / (rows.length - 1));
 const y = n => top + (height - top - bottom) * (1 - n / ceiling);
 const legend = series.map(s => `<span class="dashboard-series-${s.style}"><i style="--series:${s.color}" aria-hidden="true"></i>${s.label}</span>`).join('');
 const grid = Array.from({length:5}, (_, i) => {
  const n = i * ceiling / 4;
  return `<line class="chart-grid" x1="${left}" x2="${width-right}" y1="${y(n)}" y2="${y(n)}"/><text x="${left-7}" y="${y(n)+4}" text-anchor="end" class="chart-axis">${n}</text>`;
 }).join('');
 const dates = [...new Set([0, Math.round((rows.length-1)/2), rows.length-1])].map(i =>
  `<text x="${x(i)}" y="${height-6}" text-anchor="middle" class="chart-axis">${esc(rows[i].date.slice(5))}</text>`).join('');
 const lines = series.map(s => {
  const points = rows.map((row, i) => `${x(i)},${y(row[s.key])}`).join(' ');
  return `<polyline points="${points}" fill="none" stroke="${s.color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="${s.dash}"/>`;
 }).join('');

 container.innerHTML = `<div class="dashboard-chart-legend" aria-label="趋势图例">${legend}</div>
  <svg class="dashboard-trend-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="每日计入样本、品牌、企业和官网链接的回答数">
   <desc>各指标可在同一条回答中同时出现。使用日期滑杆查看每日数值。</desc>
   ${grid}${dates}${lines}
   <line class="dashboard-cursor" x1="0" x2="0" y1="${top}" y2="${height-bottom}"/>
   ${series.map(s => `<circle class="dashboard-point" r="3.6" fill="${s.color}" stroke="#102238" stroke-width="1.3"/>`).join('')}
  </svg>
  <label class="dashboard-day-control">查看日期 <input type="range" data-dashboard-day min="0" max="${rows.length-1}" step="1"${rows.length===1?' disabled':''}></label>
  <div class="dashboard-day-detail" data-dashboard-day-detail></div>`;
 const svg = container.querySelector('svg');
 const cursor = container.querySelector('.dashboard-cursor');
 const points = [...container.querySelectorAll('.dashboard-point')];
 const slider = container.querySelector('[data-dashboard-day]');
 const detail = container.querySelector('[data-dashboard-day-detail]');
 function select(index){
  const row = rows[index], cx = x(index);
  if (slider.getAttribute('aria-valuetext') === row.date) return;
  slider.value = index;
  slider.setAttribute('aria-valuetext', row.date);
  cursor.setAttribute('x1', cx);
  cursor.setAttribute('x2', cx);
  points.forEach((point, i) => {
   point.setAttribute('cx', cx);
   point.setAttribute('cy', y(row[series[i].key]));
  });
  detail.innerHTML = `<time datetime="${esc(row.date)}">${esc(row.date)}</time>`
   + (row.samples
    ? series.map(s => `<span>${s.label} <b>${row[s.key]}</b> 条</span>`).join('')
    : '<span>当天暂无符合口径的回答</span>');
 }
 const selected = rows.findIndex(row => row.date === selectedDate);
 select(selected >= 0 ? selected : rows.findLastIndex(row => row.samples > 0));
 slider.addEventListener('input', () => select(Number(slider.value)));
 function selectFromPointer(event){
  const bounds = svg.getBoundingClientRect();
  const relative = ((event.clientX-bounds.left) / bounds.width * width - left) / span;
  select(Math.max(0, Math.min(rows.length-1, Math.round(relative * (rows.length-1)))));
 }
 svg.addEventListener('pointermove', event => {
  if (event.pointerType === 'mouse') selectFromPointer(event);
 });
 svg.addEventListener('click', selectFromPointer);
};
