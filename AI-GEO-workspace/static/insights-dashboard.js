/* Charts share the statistics report and never request data on their own. */
(() => {
 const root = document.querySelector('#insights-dashboard');
 const tabs = [...root.querySelectorAll('[data-dashboard-metric]')];
 const platformChart = root.querySelector('#insights-platform-chart');
 const trendChart = root.querySelector('#insights-trend');
 const coverage = root.querySelector('#insights-coverage');
 const message = root.querySelector('#insights-dashboard-status');
 const metricNote = root.querySelector('#dashboard-platform-note');
 const metrics = {
  brand_mentions: {label:'提及品牌', color:'brand'},
  company_mentions: {label:'提及企业', color:'company'},
  official_links: {label:'官网链接', color:'links'},
  samples: {label:'样本量', color:'samples'},
 };
 const reasons = {
  unreviewed:'未完成或未核对', empty_answer:'空回答', branded:'指名核对',
  materials:'资料研读', continuation:'连续会话', source_directed:'来源核验',
 };
 const format = new Intl.NumberFormat('zh-CN', {maximumFractionDigits:1});
 const percent = (n, total) => format.format(n * 100 / total) + '%';
 let metric = 'brand_mentions', activeKey = '', renderedKey = '', fingerprint = '', report;

 function drawPlatforms(){
  const isCount = metric === 'samples';
  const highest = Math.max(1, ...report.platforms.map(p => p.samples));
  const {label, color} = metrics[metric];
  metricNote.textContent = isCount
   ? '柱长按当前平台中的最大样本量绘制，单位：条。'
   : '各平台分母为该平台计入的回答数。点平台名可查看该平台。';
  platformChart.innerHTML = report.platforms.map(p => {
   const name = esc(p.name), id = esc(p.id);
   const platform = report.filters.platform === 'all'
    ? `<button class="dashboard-platform" type="button" data-dashboard-platform-select="${id}" title="仅看${name}">${name}</button>`
    : `<span class="dashboard-platform-name">${name}</span>`;
   const value = p[metric];
   const max = isCount ? highest : p.samples;
   const score = isCount ? `${format.format(value)} 条` : `${percent(value, max)}`;
   return `<div class="dashboard-platform-row" data-dashboard-platform="${id}">
    ${platform}
    ${p.samples ? `<div class="dashboard-bar" role="progressbar" aria-label="${name} · ${label}" aria-valuenow="${value}" aria-valuemin="0" aria-valuemax="${max}" aria-valuetext="${isCount ? score : value + ' / ' + max + ' 条 · ' + score}">
     <span class="dashboard-bar-fill dashboard-series-${color}" style="width:${value / max * 100}%"></span></div>
     <div class="dashboard-platform-value"><b>${score}</b>${isCount ? '' : `<small>${value} / ${max} 条</small>`}</div>`
     : '<div class="dashboard-bar no-sample" aria-hidden="true"></div><div class="dashboard-platform-value no-sample-label">暂无样本</div>'}
   </div>`;
  }).join('');
 }

 function drawCoverage(){
  const total = report.task_count, included = report.totals.samples;
  if (!total){
   coverage.innerHTML = '<p class="dashboard-empty-copy">当前筛选没有任务记录。</p>';
   return;
  }
  const omitted = total - included;
  const counts = Object.entries(reasons).filter(([key]) => report.excluded[key] > 0);
  coverage.innerHTML = `<div class="dashboard-coverage-summary">
   <div class="dashboard-coverage-figures"><span><i></i>计入 <b>${included}</b> 条</span><span><i></i>未计入 <b>${omitted}</b> 条</span></div>
   <div class="dashboard-coverage-track" role="img" aria-label="共 ${total} 条任务，计入 ${included} 条，未计入 ${omitted} 条"><span style="width:${included / total * 100}%"></span></div>
   <small>共 ${total} 条任务 · 计入比例 ${percent(included, total)}</small>
  </div>
  <div class="dashboard-reasons">${counts.length
   ? `<p>未计入原因</p><ul>${counts.map(([key, label]) => `<li>${label}<b>${report.excluded[key]} 条</b></li>`).join('')}</ul>`
   : '<p class="dashboard-empty-copy">当前范围内的任务均已计入。</p>'}</div>`;
 }

 root.addEventListener('click', event => {
  const button = event.target.closest('[data-dashboard-metric]');
  if (button && report){
   metric = button.dataset.dashboardMetric;
   tabs.forEach(tab => tab.setAttribute('aria-pressed', String(tab === button)));
   drawPlatforms();
  }
  const platform = event.target.closest('[data-dashboard-platform-select]');
  if (platform){
   const filter = document.querySelector('#insights-platform');
   filter.value = platform.dataset.dashboardPlatformSelect;
   filter.dispatchEvent(new Event('change', {bubbles:true}));
   filter.focus({preventScroll:true});
  }
 });

 window.InsightsDashboard = {
  begin(key){
   activeKey = key;
   if (key === renderedKey) return;
   root.dataset.state = 'loading';
   message.textContent = '正在读取当前筛选的统计数据…';
  },
  render(next, key){
   if (key !== activeKey) return;
   const state = JSON.stringify([next.filters,next.totals.samples,next.trend,next.platforms,next.task_count,next.excluded]);
   if (state !== fingerprint){
    const selected = key === renderedKey ? trendChart.querySelector('[data-dashboard-day]')?.getAttribute('aria-valuetext') : null;
    report = next;
    window.renderVisibilityTrend(trendChart, next, selected);
    drawPlatforms();
    drawCoverage();
    fingerprint = state;
   }
   renderedKey = key;
   root.dataset.state = 'ready';
   message.textContent = '';
  },
  fail(key){
   if (key !== activeKey || key === renderedKey) return;
   root.dataset.state = 'error';
   message.textContent = '当前筛选的数据读取失败。请使用「刷新最新状态」重试。';
  },
 };
})();
