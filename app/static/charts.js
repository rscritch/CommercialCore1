(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    const el = document.createElementNS(NS, name);
    Object.entries(attrs || {}).forEach(([key, value]) => el.setAttribute(key, String(value)));
    return el;
  }

  function money(value) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(value || 0);
  }

  function empty(container, message) {
    container.innerHTML = `<div class="chart-empty">${message}</div>`;
  }

  function lineChart(container, rows) {
    if (!rows || rows.length === 0) return empty(container, "Add reporting periods to display the trend.");
    const width = 760, height = 300, left = 64, right = 24, top = 24, bottom = 48;
    const plotW = width - left - right, plotH = height - top - bottom;
    const maxValue = Math.max(...rows.flatMap(r => [r.actual || 0, r.estimatePace || 0]), 1);
    const svg = svgEl("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Cumulative exposure trend"});
    [0, .25, .5, .75, 1].forEach(frac => {
      const y = top + plotH * (1 - frac);
      svg.appendChild(svgEl("line", {x1:left, y1:y, x2:width-right, y2:y, class:"chart-grid"}));
      const label = svgEl("text", {x:left-10, y:y+4, "text-anchor":"end", class:"chart-axis-label"});
      label.textContent = money(maxValue * frac);
      svg.appendChild(label);
    });
    const x = i => left + (rows.length === 1 ? plotW/2 : i * plotW/(rows.length-1));
    const y = v => top + plotH * (1 - v/maxValue);
    function pathFor(key, className) {
      const d = rows.map((row,i) => `${i===0?'M':'L'} ${x(i)} ${y(row[key] || 0)}`).join(" ");
      svg.appendChild(svgEl("path", {d, class:className}));
      rows.forEach((row,i) => svg.appendChild(svgEl("circle", {cx:x(i), cy:y(row[key] || 0), r:3.5, class:`${className}-point`})));
    }
    pathFor("estimatePace", "chart-line estimate-line");
    pathFor("actual", "chart-line actual-line");
    const step = Math.max(1, Math.ceil(rows.length / 6));
    rows.forEach((row,i) => {
      if (i % step !== 0 && i !== rows.length-1) return;
      const label = svgEl("text", {x:x(i), y:height-18, "text-anchor":"middle", class:"chart-axis-label"});
      label.textContent = row.label;
      svg.appendChild(label);
    });
    container.innerHTML = "";
    container.appendChild(svg);
  }

  function barChart(container, rows, labelKey, valueKey) {
    if (!rows || rows.length === 0) return empty(container, "No comparable history is available yet.");
    const width = 760, height = 300, left = 64, right = 24, top = 24, bottom = 56;
    const plotW = width-left-right, plotH=height-top-bottom;
    const maxValue = Math.max(...rows.map(r => r[valueKey] || 0), 1);
    const svg = svgEl("svg", {viewBox:`0 0 ${width} ${height}`, role:"img"});
    [0,.25,.5,.75,1].forEach(frac => {
      const y=top+plotH*(1-frac);
      svg.appendChild(svgEl("line",{x1:left,y1:y,x2:width-right,y2:y,class:"chart-grid"}));
      const t=svgEl("text",{x:left-10,y:y+4,"text-anchor":"end",class:"chart-axis-label"}); t.textContent=money(maxValue*frac); svg.appendChild(t);
    });
    const slot=plotW/rows.length, barW=Math.min(90, slot*.58);
    rows.forEach((row,i)=>{
      const value=row[valueKey]||0, h=plotH*(value/maxValue), x=left+i*slot+(slot-barW)/2, y=top+plotH-h;
      svg.appendChild(svgEl("rect",{x,y,width:barW,height:h,rx:6,class:row.projected?"chart-bar projected-bar":"chart-bar"}));
      const val=svgEl("text",{x:x+barW/2,y:Math.max(y-8,14),"text-anchor":"middle",class:"chart-value-label"}); val.textContent=money(value); svg.appendChild(val);
      const lab=svgEl("text",{x:x+barW/2,y:height-22,"text-anchor":"middle",class:"chart-axis-label"}); lab.textContent=row[labelKey]; svg.appendChild(lab);
    });
    container.innerHTML=""; container.appendChild(svg);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const payload = document.getElementById("reporting-data");
    if (!payload) return;
    let data;
    try { data = JSON.parse(payload.textContent); } catch (_) { return; }
    const trend = document.getElementById("trend-chart");
    const annual = document.getElementById("annual-chart");
    const methods = document.getElementById("projection-chart");
    if (trend) lineChart(trend, data.cumulative);
    if (annual) barChart(annual, data.annual_totals, "year", "value");
    if (methods) barChart(methods, data.projection_methods, "method", "value");

    const businessPayload = document.getElementById("business-data");
    if (businessPayload) {
      let businessData;
      try { businessData = JSON.parse(businessPayload.textContent); } catch (_) { businessData = null; }
      if (businessData) {
        groupedBarChart(document.getElementById("business-projection-chart"), businessData.estimate_projection, "label", [
          {key:"estimate", label:"Recorded estimate"}, {key:"projection", label:"Current projection"}
        ], true);
        groupedBarChart(document.getElementById("business-score-chart"), businessData.scores, "label", [
          {key:"index", label:"Core index"}, {key:"accuracy", label:"Accuracy"}, {key:"confidence", label:"Confidence"}
        ], false);
      }
    }
  });

  function groupedBarChart(container, rows, labelKey, series, moneyValues) {
    if (!container) return;
    if (!rows || !rows.length) return empty(container, "Add calculated exposures to display this chart.");
    const width=760,height=320,left=64,right=24,top=24,bottom=88,plotW=width-left-right,plotH=height-top-bottom;
    const maxValue=Math.max(...rows.flatMap(r=>series.map(s=>r[s.key]||0)),1);
    const svg=svgEl("svg",{viewBox:`0 0 ${width} ${height}`,role:"img"});
    [0,.25,.5,.75,1].forEach(frac=>{const y=top+plotH*(1-frac);svg.appendChild(svgEl("line",{x1:left,y1:y,x2:width-right,y2:y,class:"chart-grid"}));const t=svgEl("text",{x:left-10,y:y+4,"text-anchor":"end",class:"chart-axis-label"});t.textContent=moneyValues?money(maxValue*frac):Math.round(maxValue*frac);svg.appendChild(t);});
    const groupW=plotW/rows.length,barW=Math.min(34,(groupW*.72)/series.length);
    rows.forEach((row,i)=>{series.forEach((ser,j)=>{const value=row[ser.key]||0,h=plotH*(value/maxValue),x=left+i*groupW+(groupW-series.length*barW)/2+j*barW,y=top+plotH-h;svg.appendChild(svgEl("rect",{x,y,width:Math.max(barW-3,4),height:h,rx:4,class:j===0?"chart-bar":"chart-bar-secondary"}));});const lab=svgEl("text",{x:left+i*groupW+groupW/2,y:height-58,"text-anchor":"middle",class:"chart-axis-label",transform:`rotate(-18 ${left+i*groupW+groupW/2} ${height-58})`});lab.textContent=row[labelKey];svg.appendChild(lab);});
    series.forEach((ser,j)=>{const x=left+j*180,y=height-12;svg.appendChild(svgEl("rect",{x,y:y-10,width:14,height:6,rx:2,class:j===0?"chart-bar":"chart-bar-secondary"}));const t=svgEl("text",{x:x+20,y,class:"chart-axis-label"});t.textContent=ser.label;svg.appendChild(t);});
    container.innerHTML="";container.appendChild(svg);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const payload = document.getElementById("portfolio-analytics-data");
    if (!payload) return;
    let data;
    try { data = JSON.parse(payload.textContent); } catch (_) { return; }
    barChart(document.getElementById("portfolio-carrier-chart"), data.carrier || [], "label", "value");
    barChart(document.getElementById("portfolio-industry-chart"), data.industry || [], "label", "value");
    barChart(document.getElementById("portfolio-line-chart"), data.line || [], "label", "value");
  });

  document.addEventListener("DOMContentLoaded", () => {
    const payload = document.getElementById("executive-analytics-data");
    if (!payload) return;
    let data;
    try { data = JSON.parse(payload.textContent); } catch (_) { return; }
    barChart(document.getElementById("executive-premium-chart"), data.premium_trend || [], "label", "value");
    groupedBarChart(document.getElementById("executive-renewal-chart"), data.renewal_pipeline || [], "label", [
      {key:"premium", label:"Tracked annual premium"},
      {key:"count", label:"Policy count"}
    ], true);
  });
})();
