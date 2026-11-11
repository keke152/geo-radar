/* Read-only SVG chart: three named series, shared counts and explicit units. */
window.renderVisibilityTrend=report=>{
 const rows=report.trend,width=700,height=220,left=40,right=16,top=15,bottom=30;
 const peak=Math.max(1,...rows.map(d=>d.samples));
 const ceiling=peak<=4?4:Math.ceil(peak/4)*4;
 const x=i=>left+(width-left-right)*(rows.length>1?i/(rows.length-1):.5),y=n=>top+(height-top-bottom)*(1-n/ceiling);
 const series=[['samples','已核对回答','#4e83df',''],['brand_mentions','提及品牌','#9670d8','7 4'],['company_mentions','提及企业','#24a6a0','2 3']];
 const legend='<div class="trend-legend" aria-label="图例">'+series.map(([key,label,color,dash])=>`<span><i style="--series-color:${color}"></i>${label}<small>${key==='samples'?'蓝色':key==='brand_mentions'?'紫色':'青色'}</small></span>`).join('')+'<em>单位：条回答</em></div>';
 const grid=Array.from({length:5},(_,i)=>{const n=ceiling*i/4;return `<line x1="${left}" x2="${width-right}" y1="${y(n)}" y2="${y(n)}" class="chart-grid"/><text x="${left-9}" y="${y(n)+4}" text-anchor="end" class="chart-axis">${n}</text>`;}).join('');
 const lines=series.map(([key,label,color,dash])=>`<path d="${rows.map((d,i)=>(i?'L':'M')+x(i).toFixed(1)+','+y(d[key]).toFixed(1)).join(' ')}" fill="none" stroke="${color}" stroke-width="2.2" ${dash?`stroke-dasharray="${dash}"`:''}/>`).join('');
 const points=rows.map((d,i)=>`<g tabindex="0" role="img" aria-label="${d.date}：已核对${d.samples}条，品牌${d.brand_mentions}条，企业${d.company_mentions}条"><circle cx="${x(i)}" cy="${y(d.samples)}" r="7" fill="transparent"><title>${d.date}\n已核对回答：${d.samples}条\n提及品牌：${d.brand_mentions}条\n提及企业：${d.company_mentions}条</title></circle></g>`).join('');
 return legend+(!report.totals.samples?'<p class="empty-trend">当前范围暂无符合口径的回答。</p>':'')+`<svg class="visibility-trend-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="每日回答趋势：蓝色为已核对回答，紫色为品牌提及，青色为企业提及"><desc>品牌与企业提及是回答总数中的子集，同一回答可能同时提及品牌和企业。</desc>${grid}${lines}${points}<text class="chart-axis" x="${left}" y="${height-6}">${report.filters.start_date}</text><text class="chart-axis" text-anchor="end" x="${width-right}" y="${height-6}">${report.filters.end_date}</text></svg><p class="trend-caption">品牌和企业分别按“出现名称的回答条数”计算；同一回答可能同时计入两者。</p>`;
};
