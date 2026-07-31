import json
import os
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from flask import Flask, jsonify, render_template_string, request
import easyocr
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH = BASE_DIR / "stock_journal.db"
EASYOCR_MODEL_DIR = BASE_DIR / ".easyocr-model"
EASYOCR_MODEL_DIR.mkdir(exist_ok=True)

_OCR_READER = None
_OCR_LOCK = threading.Lock()

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>股票帳跌與收益紀錄（離線）</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --panel: #ffffff;
      --line: #dce3ef;
      --text: #1f2937;
      --subtext: #4b5563;
      --blue: #1d4ed8;
      --red: #b91c1c;
      --green: #047857;
      --amber: #b45309;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Noto Sans TC", "PingFang TC", sans-serif;
      background: radial-gradient(circle at top left, #edf3ff 0, var(--bg) 45%);
      color: var(--text);
    }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 20px; }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 10px 22px rgba(18, 38, 63, 0.06);
      margin-bottom: 16px;
    }
    h1 { margin: 0 0 12px; font-size: 24px; }
    h2 { margin: 0 0 12px; font-size: 18px; }
    .grid { display: grid; gap: 12px; }
    .grid-3 { grid-template-columns: repeat(3, minmax(0,1fr)); }
    .grid-4 { grid-template-columns: repeat(4, minmax(0,1fr)); }
    .grid-2 { grid-template-columns: repeat(2, minmax(0,1fr)); }
    label { font-size: 13px; color: var(--subtext); display: block; margin-bottom: 4px; }
    input, button, select {
      width: 100%;
      padding: 10px;
      border-radius: 10px;
      border: 1px solid var(--line);
      font-size: 14px;
      background: #fff;
    }
    button {
      background: #eef3ff;
      border-color: #c7d7ff;
      color: var(--blue);
      font-weight: 600;
      cursor: pointer;
    }
    button:hover { background: #e1eaff; }
    .btn-save { background: #dcfce7; border-color: #86efac; color: #166534; }
    .btn-danger { background: #fee2e2; border-color: #fecaca; color: #991b1b; }
    .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
    .tab { width: auto; padding: 10px 14px; }
    .tab.active { background: #dbeafe; border-color: #93c5fd; color: #1e3a8a; }
    .hidden { display: none; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; font-size: 13px; }
    th { background: #f8fafc; }
    td input { padding: 6px; font-size: 13px; }
    .muted { color: var(--subtext); font-size: 13px; }
    .mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
    .kpi { background: #f8fafc; border: 1px solid var(--line); border-radius: 10px; padding: 10px; }
    .kpi .name { font-size: 12px; color: var(--subtext); }
    .kpi .val { font-size: 18px; font-weight: 700; margin-top: 3px; }
    .val.pos { color: var(--green); }
    .val.neg { color: var(--red); }
    .val.up { color: var(--red); }
    .val.down { color: var(--green); }
    .up { color: var(--red); font-weight: 600; }
    .down { color: var(--green); font-weight: 600; }
    .flex { display: flex; gap: 8px; align-items: center; }
    .right { text-align: right; }
    canvas { width: 100%; height: 360px; }
    @media (max-width: 900px) {
      .grid-4, .grid-3, .grid-2 { grid-template-columns: 1fr; }
      .wrap { padding: 10px; }
    }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
  <div class="wrap">
    <h1>股票帳跌與收益紀錄（離線）</h1>
    <div class="tabs">
      <button class="tab active" id="tabUploadBtn" onclick="switchTab('upload')">上傳與寫入</button>
      <button class="tab" id="tabQueryBtn" onclick="switchTab('query')">查詢與圖表</button>
      <button class="tab" id="tabPortfolioBtn" onclick="switchTab('portfolio')">總投資</button>
      <button class="tab" id="tabListingBtn" onclick="switchTab('listing')">區間清單</button>
    </div>

    <section id="tabUpload" class="card">
      <h2>1) 上傳每日券商截圖並擷取資料</h2>
      <div class="grid grid-3">
        <div>
          <label>記錄日期</label>
          <input type="date" id="recordDate" value="{{ today }}" />
        </div>
        <div>
          <label>券商截圖（png/jpg）</label>
          <input type="file" id="screenshot" accept="image/png,image/jpeg" />
        </div>
        <div style="align-self:end;">
          <button onclick="parseImage()">解析截圖</button>
        </div>
      </div>
      <p class="muted" id="parseStatus">尚未解析。</p>

      <h2>2) 總覽資訊與表格預覽（可手動修正）</h2>
      <div class="grid grid-2" id="overviewGrid"></div>

      <div class="flex" style="justify-content:space-between; margin-top: 12px;">
        <h2 style="margin:0;">股票明細（可新增 / 刪除）</h2>
        <div class="flex">
          <button onclick="addRow()">新增一列</button>
          <button class="btn-save" onclick="saveRows()">寫入 SQLite</button>
        </div>
      </div>

      <div style="overflow:auto; margin-top: 8px;">
        <table id="rowsTable">
          <thead>
            <tr>
              <th>商品</th>
              <th>股數</th>
              <th>現價</th>
              <th>成本價</th>
              <th>投資成本</th>
              <th>帳面收入</th>
              <th>損益</th>
              <th>損益率(%)</th>
              <th></th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </section>

    <section id="tabQuery" class="card hidden">
      <h2>3) 依商品查詢曲線圖與明細，支援起迄日期</h2>
      <div class="grid grid-3">
        <div>
          <label>起始日期</label>
          <input type="date" id="startDate" />
        </div>
        <div>
          <label>結束日期</label>
          <input type="date" id="endDate" value="{{ today }}" />
        </div>
        <div>
          <label>商品</label>
          <select id="productSelect"></select>
        </div>
      </div>
      <div class="grid grid-3" style="margin-top: 12px;">
        <div class="kpi"><div class="name">最新損益</div><div class="val" id="kpiProfit">-</div></div>
        <div class="kpi"><div class="name">最新日增減損益</div><div class="val" id="kpiDaily">-</div></div>
        <div class="kpi"><div class="name">最新損益率</div><div class="val" id="kpiRate">-</div></div>
      </div>
      <div class="grid grid-4" style="margin-top: 12px;">
        <div class="kpi"><div class="name">總投資成本</div><div class="val" id="kpiTotalInvestment">-</div></div>
        <div class="kpi"><div class="name">總帳面收入</div><div class="val" id="kpiTotalBookIncome">-</div></div>
        <div class="kpi"><div class="name">總損益</div><div class="val" id="kpiTotalProfit">-</div></div>
        <div class="kpi"><div class="name">統計基準日</div><div class="val" id="kpiTotalAsOf">-</div></div>
      </div>
      <div class="flex" style="margin-top:12px;">
        <button onclick="loadProductData()">查詢</button>
        <button type="button" id="toggleProfitAxisBtn" onclick="toggleProfitAxisMode()">損益圖模式：雙軸</button>
      </div>
      <div style="margin-top: 14px;"><canvas id="chartPriceCost"></canvas></div>
      <div style="margin-top: 14px;"><canvas id="chartCapitalIncome"></canvas></div>
      <div style="margin-top: 14px;"><canvas id="chartProfitRate"></canvas></div>

      <h2 style="margin-top:16px;">明細表</h2>
      <div style="overflow:auto;">
        <table id="detailTable">
          <thead>
            <tr>
              <th>日期</th><th>商品</th><th>股數</th><th>現價</th><th>成本價</th><th>投資成本</th><th>帳面收入</th><th>損益</th><th>損益率(%)</th><th>日增減損益</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>

    </section>

    <section id="tabPortfolio" class="card hidden">
      <h2>4) 總投資每日趨勢與明細</h2>
      <div class="grid grid-2">
        <div>
          <label>起始日期</label>
          <input type="date" id="portfolioStartDate" />
        </div>
        <div>
          <label>結束日期</label>
          <input type="date" id="portfolioEndDate" value="{{ today }}" />
        </div>
      </div>
      <div class="flex" style="margin-top:12px;">
        <button onclick="loadPortfolioPageData()">查詢總投資</button>
      </div>

      <h2 style="margin-top:16px;">總投資成本 / 總帳面收入（全商品）</h2>
      <div style="margin-top: 14px;"><canvas id="chartPortfolioTotals"></canvas></div>

      <h2 style="margin-top:16px;">每日總覽</h2>
      <div style="overflow:auto;">
        <table id="portfolioDailyTable">
          <thead>
            <tr>
              <th>日期</th><th>總投資成本</th><th>總帳面收入</th><th>總損益</th><th>每天差異金額</th><th>總損益率(%)</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </section>

    <section id="tabListing" class="card hidden">
      <h2>5) 依起訖日期查看所有商品資訊清單</h2>
      <div class="grid grid-2">
        <div>
          <label>起始日期</label>
          <input type="date" id="listStartDate" />
        </div>
        <div>
          <label>結束日期</label>
          <input type="date" id="listEndDate" value="{{ today }}" />
        </div>
      </div>
      <div class="flex" style="margin-top:12px;">
        <button onclick="loadAllProductData()">查詢全部商品</button>
      </div>

      <p class="muted" id="listingInfo" style="margin-top:10px;">排序：商品（遞減）＋日期（遞減）</p>
      <div class="card" style="margin-top:12px;">
        <label>曲線商品勾選</label>
        <div id="listingProductSelector" class="grid grid-4 muted"></div>
      </div>
      <div style="margin-top: 14px;"><canvas id="chartListingProfit"></canvas></div>
      <div style="margin-top: 14px;"><canvas id="chartListingProfitRate"></canvas></div>
      <div style="overflow:auto;">
        <table id="allDetailTable">
          <thead>
            <tr>
              <th>日期</th><th>商品</th><th>股數</th><th>現價</th><th>成本價</th><th>投資成本</th><th>帳面收入</th><th>損益</th><th>損益率(%)</th><th>日增減損益</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
  </div>

<script>
let parsedOverview = {};
let parsedRows = [];
let chartPriceCost = null;
let chartCapitalIncome = null;
let chartProfitRate = null;
let chartPortfolioTotals = null;
let chartListingProfit = null;
let chartListingProfitRate = null;
let profitAxisMode = 'dual';
let latestProductRows = [];
let latestListingRows = [];
let selectedListingProducts = new Set();

function switchTab(which) {
  document.getElementById('tabUpload').classList.toggle('hidden', which !== 'upload');
  document.getElementById('tabQuery').classList.toggle('hidden', which !== 'query');
  document.getElementById('tabPortfolio').classList.toggle('hidden', which !== 'portfolio');
  document.getElementById('tabListing').classList.toggle('hidden', which !== 'listing');
  document.getElementById('tabUploadBtn').classList.toggle('active', which === 'upload');
  document.getElementById('tabQueryBtn').classList.toggle('active', which === 'query');
  document.getElementById('tabPortfolioBtn').classList.toggle('active', which === 'portfolio');
  document.getElementById('tabListingBtn').classList.toggle('active', which === 'listing');
  if (which === 'query') {
    refreshProducts();
  }
  if (which === 'portfolio') {
    loadPortfolioPageData();
  }
  if (which === 'listing') {
    loadAllProductData();
  }
}

function numVal(v) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

function renderOverview() {
  const grid = document.getElementById('overviewGrid');
  grid.innerHTML = '';
  const keys = ['account', 'total_profit_loss', 'total_profit_rate', 'total_investment_cost', 'record_count', 'raw_summary_text'];
  const names = {
    account: '帳號/來源',
    total_profit_loss: '總損益',
    total_profit_rate: '總損益率(%)',
    total_investment_cost: '總投資成本',
    record_count: '擷取筆數',
    raw_summary_text: '總覽原始文字'
  };
  keys.forEach((k) => {
    const box = document.createElement('div');
    box.className = 'kpi';
    box.innerHTML = `<div class='name'>${names[k]}</div><input id='ov_${k}' value='${parsedOverview[k] ?? ''}' />`;
    grid.appendChild(box);
  });
}

function rowHtml(r) {
  return `<tr>
    <td><input value="${r.product ?? ''}" /></td>
    <td><input value="${r.shares ?? ''}" /></td>
    <td><input value="${r.current_price ?? ''}" /></td>
    <td><input value="${r.cost_price ?? ''}" /></td>
    <td><input value="${r.investment_cost ?? ''}" /></td>
    <td><input value="${r.book_income ?? ''}" /></td>
    <td><input value="${r.profit_loss ?? ''}" /></td>
    <td><input value="${r.profit_loss_rate ?? ''}" /></td>
    <td><button class='btn-danger' onclick='this.closest("tr").remove()'>刪除</button></td>
  </tr>`;
}

function renderRows() {
  const tbody = document.querySelector('#rowsTable tbody');
  tbody.innerHTML = parsedRows.map(rowHtml).join('');
}

function addRow() {
  parsedRows.push({ product: '', shares: '', current_price: '', cost_price: '', investment_cost: '', book_income: '', profit_loss: '', profit_loss_rate: '' });
  renderRows();
}

function collectRowsFromTable() {
  const rows = [];
  document.querySelectorAll('#rowsTable tbody tr').forEach((tr) => {
    const cells = tr.querySelectorAll('td input');
    const obj = {
      product: cells[0].value.trim(),
      shares: numVal(cells[1].value),
      current_price: numVal(cells[2].value),
      cost_price: numVal(cells[3].value),
      investment_cost: numVal(cells[4].value),
      book_income: numVal(cells[5].value),
      profit_loss: numVal(cells[6].value),
      profit_loss_rate: numVal(cells[7].value),
    };
    if (obj.product) rows.push(obj);
  });
  return rows;
}

function collectOverview() {
  const keys = ['account', 'total_profit_loss', 'total_profit_rate', 'total_investment_cost', 'record_count', 'raw_summary_text'];
  const out = {};
  keys.forEach((k) => {
    out[k] = document.getElementById(`ov_${k}`)?.value ?? '';
  });
  out.total_profit_loss = numVal(out.total_profit_loss);
  out.total_profit_rate = numVal(out.total_profit_rate);
  out.total_investment_cost = numVal(out.total_investment_cost);
  out.record_count = parseInt(out.record_count || '0', 10) || 0;
  return out;
}

async function parseImage() {
  const file = document.getElementById('screenshot').files[0];
  const recordDate = document.getElementById('recordDate').value;
  if (!file) return alert('請選擇截圖檔案');
  if (!recordDate) return alert('請選擇記錄日期');

  const form = new FormData();
  form.append('image', file);
  form.append('record_date', recordDate);

  document.getElementById('parseStatus').textContent = '解析中，請稍候...';
  const res = await fetch('/api/parse', { method: 'POST', body: form });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById('parseStatus').textContent = `解析失敗：${data.error || '未知錯誤'}`;
    return;
  }
  parsedOverview = data.summary || {};
  parsedRows = data.rows || [];
  renderOverview();
  renderRows();
  document.getElementById('parseStatus').textContent = `解析完成，共 ${parsedRows.length} 筆。若 OCR 有誤可直接修改後再存檔。`;
}

async function saveRows() {
  const payload = {
    record_date: document.getElementById('recordDate').value,
    source_file: document.getElementById('screenshot').files[0]?.name || 'manual',
    summary: collectOverview(),
    rows: collectRowsFromTable(),
  };
  if (!payload.record_date) return alert('請選擇記錄日期');
  if (!payload.rows.length) return alert('至少需一筆商品資料');

  const res = await fetch('/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || '寫入失敗');
  alert(`寫入成功：${data.saved_count} 筆，已更新日增減損益`);
  switchTab('query');
  await refreshProducts();
}

async function refreshProducts() {
  const sel = document.getElementById('productSelect');
  const prevValue = sel.value;
  const res = await fetch('/api/products');
  const data = await res.json();
  sel.innerHTML = '';
  (data.products || []).forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p;
    sel.appendChild(opt);
  });
  if (prevValue && (data.products || []).includes(prevValue)) {
    sel.value = prevValue;
  }
  if (!document.getElementById('startDate').value) {
    document.getElementById('startDate').value = data.min_date || '';
  }
  if (!document.getElementById('listStartDate').value) {
    document.getElementById('listStartDate').value = data.min_date || '';
  }
  if (!document.getElementById('portfolioStartDate').value) {
    document.getElementById('portfolioStartDate').value = data.min_date || '';
  }
  if (!document.getElementById('listEndDate').value) {
    document.getElementById('listEndDate').value = document.getElementById('endDate').value || '';
  }
  if (!document.getElementById('portfolioEndDate').value) {
    document.getElementById('portfolioEndDate').value = document.getElementById('endDate').value || '';
  }
  if ((data.products || []).length) {
    await loadProductData();
  }
}

function fmt(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '-';
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function colorClass(v) {
  if (v > 0) return 'pos';
  if (v < 0) return 'neg';
  return '';
}

function profitClass(v) {
  if (v > 0) return 'up';
  if (v < 0) return 'down';
  return '';
}

function destroyProductCharts() {
  if (chartPriceCost) chartPriceCost.destroy();
  if (chartCapitalIncome) chartCapitalIncome.destroy();
  if (chartProfitRate) chartProfitRate.destroy();
  chartPriceCost = null;
  chartCapitalIncome = null;
  chartProfitRate = null;
}

function destroyPortfolioChart() {
  if (chartPortfolioTotals) chartPortfolioTotals.destroy();
  chartPortfolioTotals = null;
}

function destroyListingCharts() {
  if (chartListingProfit) chartListingProfit.destroy();
  if (chartListingProfitRate) chartListingProfitRate.destroy();
  chartListingProfit = null;
  chartListingProfitRate = null;
}

function getSeriesColor(index) {
  const palette = ['#1d4ed8', '#b91c1c', '#047857', '#b45309', '#0ea5e9', '#7c3aed', '#be185d', '#ca8a04', '#0f766e', '#6d28d9'];
  return palette[index % palette.length];
}

function buildListingDatasets(rows, metricKey) {
  const products = Array.from(selectedListingProducts);
  const labels = Array.from(new Set(rows.map((r) => r.record_date))).sort();
  const productDateValue = new Map();
  rows.forEach((r) => {
    productDateValue.set(`${r.product}__${r.record_date}`, r[metricKey]);
  });

  const datasets = products.map((product, idx) => {
    const color = getSeriesColor(idx);
    return {
      label: product,
      data: labels.map((d) => {
        const v = productDateValue.get(`${product}__${d}`);
        return v === undefined ? null : v;
      }),
      borderColor: color,
      backgroundColor: color,
      fill: false,
      tension: 0.2,
      pointRadius: 2,
      spanGaps: true,
    };
  });
  return { labels, datasets };
}

function renderListingCharts() {
  if (!latestListingRows.length || !selectedListingProducts.size) {
    destroyListingCharts();
    return;
  }

  const profitSeries = buildListingDatasets(latestListingRows, 'profit_loss');
  const rateSeries = buildListingDatasets(latestListingRows, 'profit_loss_rate');
  destroyListingCharts();

  chartListingProfit = new Chart(document.getElementById('chartListingProfit').getContext('2d'), {
    type: 'line',
    data: profitSeries,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: '各商品損益曲線' } },
      interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: false } }
    }
  });

  chartListingProfitRate = new Chart(document.getElementById('chartListingProfitRate').getContext('2d'), {
    type: 'line',
    data: rateSeries,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: '各商品損益率曲線(%)' } },
      interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: false } }
    }
  });
}

function renderListingProductSelector(rows) {
  const el = document.getElementById('listingProductSelector');
  const products = Array.from(new Set(rows.map((r) => r.product))).sort();
  if (!products.length) {
    el.innerHTML = '<span class="muted">目前無資料可勾選商品</span>';
    selectedListingProducts = new Set();
    destroyListingCharts();
    return;
  }

  if (!selectedListingProducts.size) {
    selectedListingProducts = new Set(products);
  } else {
    selectedListingProducts = new Set(products.filter((p) => selectedListingProducts.has(p)));
    if (!selectedListingProducts.size) {
      selectedListingProducts = new Set(products);
    }
  }

  el.innerHTML = products.map((p) => `
    <label style="display:flex; gap:6px; align-items:center; margin:0;">
      <input type="checkbox" class="listing-product-checkbox" value="${p}" ${selectedListingProducts.has(p) ? 'checked' : ''} style="width:auto;" />
      <span>${p}</span>
    </label>
  `).join('');

  document.querySelectorAll('.listing-product-checkbox').forEach((cb) => {
    cb.addEventListener('change', () => {
      const checked = Array.from(document.querySelectorAll('.listing-product-checkbox:checked')).map((x) => x.value);
      selectedListingProducts = new Set(checked);
      renderListingCharts();
    });
  });
}

function buildProfitRateChart(rows, labels) {
  if (chartProfitRate) chartProfitRate.destroy();
  const isDual = profitAxisMode === 'dual';
  const btn = document.getElementById('toggleProfitAxisBtn');
  if (btn) {
    btn.textContent = `損益圖模式：${isDual ? '雙軸' : '同軸'}`;
  }
  chartProfitRate = new Chart(document.getElementById('chartProfitRate').getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: '損益', data: rows.map((r) => r.profit_loss), borderColor: '#b91c1c', backgroundColor: '#b91c1c', fill: false, tension: 0.2, pointRadius: 2, yAxisID: 'y' },
        { label: '損益率(%)', data: rows.map((r) => r.profit_loss_rate), borderColor: '#7c3aed', backgroundColor: '#7c3aed', fill: false, tension: 0.2, pointRadius: 2, yAxisID: isDual ? 'y1' : 'y' },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: `損益 / 損益率（${isDual ? '雙軸' : '同軸'}）` } },
      interaction: { mode: 'index', intersect: false },
      scales: isDual
        ? {
            y: { beginAtZero: false, position: 'left' },
            y1: { beginAtZero: false, position: 'right', grid: { drawOnChartArea: false } },
          }
        : {
            y: { beginAtZero: false, position: 'left' },
          }
    }
  });
}

function toggleProfitAxisMode() {
  profitAxisMode = profitAxisMode === 'dual' ? 'single' : 'dual';
  if (!latestProductRows.length) return;
  const labels = latestProductRows.map((r) => r.record_date);
  buildProfitRateChart(latestProductRows, labels);
}

async function loadPortfolioTotals(start, end) {
  const res = await fetch(`/api/portfolio-totals?start=${start}&end=${end}`);
  const data = await res.json();
  const invEl = document.getElementById('kpiTotalInvestment');
  const bookEl = document.getElementById('kpiTotalBookIncome');
  const profitEl = document.getElementById('kpiTotalProfit');
  const asOfEl = document.getElementById('kpiTotalAsOf');
  invEl.textContent = fmt(data.total_investment_cost);
  bookEl.textContent = fmt(data.total_book_income);
  profitEl.textContent = fmt(data.total_profit_loss);
  profitEl.className = `val ${colorClass(data.total_profit_loss)}`;
  asOfEl.textContent = data.as_of_date || '-';
}

async function loadPortfolioPageData() {
  const start = document.getElementById('portfolioStartDate').value;
  const end = document.getElementById('portfolioEndDate').value;
  const res = await fetch(`/api/portfolio-totals-series?start=${start}&end=${end}`);
  const data = await res.json();
  const rows = data.rows || [];

  if (!rows.length) {
    destroyPortfolioChart();
    document.querySelector('#portfolioDailyTable tbody').innerHTML = '';
    return;
  }

  const labels = rows.map((r) => r.record_date);
  const totalInvestment = rows.map((r) => r.total_investment_cost);
  const totalBookIncome = rows.map((r) => r.total_book_income);
  destroyPortfolioChart();
  chartPortfolioTotals = new Chart(document.getElementById('chartPortfolioTotals').getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: '總投資成本', data: totalInvestment, borderColor: '#065f46', backgroundColor: '#065f46', fill: false, tension: 0.2, pointRadius: 2 },
        { label: '總帳面收入', data: totalBookIncome, borderColor: '#9a3412', backgroundColor: '#9a3412', fill: false, tension: 0.2, pointRadius: 2 },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: '全商品每日加總趨勢' } },
      interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: false } }
    }
  });

  const tb = document.querySelector('#portfolioDailyTable tbody');
  const rowsWithDiff = [...rows];
  let prevTotalProfit = null;
  rowsWithDiff.forEach((r) => {
    const currentProfit = numVal(r.total_profit_loss);
    if (currentProfit === null || prevTotalProfit === null) {
      r.daily_diff_amount = null;
    } else {
      r.daily_diff_amount = currentProfit - prevTotalProfit;
    }
    prevTotalProfit = currentProfit;
  });
  const tableRows = rowsWithDiff.sort((a, b) => (a.record_date < b.record_date ? 1 : a.record_date > b.record_date ? -1 : 0));
  tb.innerHTML = tableRows.map((r) => `<tr>
    <td>${r.record_date}</td><td>${fmt(r.total_investment_cost)}</td><td>${fmt(r.total_book_income)}</td><td class="${profitClass(r.total_profit_loss)}">${fmt(r.total_profit_loss)}</td><td class="${profitClass(r.daily_diff_amount)}">${fmt(r.daily_diff_amount)}</td><td class="${profitClass(r.total_profit_rate)}">${fmt(r.total_profit_rate)}</td>
  </tr>`).join('');
}

async function loadProductData() {
  const product = document.getElementById('productSelect').value;
  const start = document.getElementById('startDate').value;
  const end = document.getElementById('endDate').value;
  await loadPortfolioTotals(start, end);

  if (!product) {
    latestProductRows = [];
    document.querySelector('#detailTable tbody').innerHTML = '';
    destroyProductCharts();
    return;
  }

  const res = await fetch(`/api/product-data?product=${encodeURIComponent(product)}&start=${start}&end=${end}`);
  const data = await res.json();
  const rows = data.rows || [];
  latestProductRows = rows;

  const tb = document.querySelector('#detailTable tbody');
  tb.innerHTML = rows.map((r) => `<tr>
    <td>${r.record_date}</td><td>${r.product}</td><td>${fmt(r.shares, 0)}</td><td>${fmt(r.current_price)}</td><td>${fmt(r.cost_price)}</td><td>${fmt(r.investment_cost)}</td><td>${fmt(r.book_income)}</td><td class="${profitClass(r.profit_loss)}">${fmt(r.profit_loss)}</td><td class="${profitClass(r.profit_loss_rate)}">${fmt(r.profit_loss_rate)}</td><td class="${profitClass(r.daily_profit_change)}">${fmt(r.daily_profit_change)}</td>
  </tr>`).join('');

  const latest = rows[rows.length - 1] || {};
  const kpiProfit = document.getElementById('kpiProfit');
  const kpiDaily = document.getElementById('kpiDaily');
  const kpiRate = document.getElementById('kpiRate');
  kpiProfit.textContent = fmt(latest.profit_loss);
  kpiProfit.className = `val ${colorClass(latest.profit_loss)}`;
  kpiDaily.textContent = fmt(latest.daily_profit_change);
  kpiDaily.className = `val ${colorClass(latest.daily_profit_change)}`;
  kpiRate.textContent = `${fmt(latest.profit_loss_rate)}%`;
  kpiRate.className = `val ${colorClass(latest.profit_loss_rate)}`;

  const labels = rows.map((r) => r.record_date);
  destroyProductCharts();

  chartPriceCost = new Chart(document.getElementById('chartPriceCost').getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: '現價', data: rows.map((r) => r.current_price), borderColor: '#1d4ed8', backgroundColor: '#1d4ed8', fill: false, tension: 0.2, pointRadius: 2 },
        { label: '成本價', data: rows.map((r) => r.cost_price), borderColor: '#0ea5e9', backgroundColor: '#0ea5e9', fill: false, tension: 0.2, pointRadius: 2 },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: '現價 / 成本價' } },
      interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: false } }
    }
  });

  chartCapitalIncome = new Chart(document.getElementById('chartCapitalIncome').getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: '投資成本', data: rows.map((r) => r.investment_cost), borderColor: '#047857', backgroundColor: '#047857', fill: false, tension: 0.2, pointRadius: 2 },
        { label: '帳面收入', data: rows.map((r) => r.book_income), borderColor: '#b45309', backgroundColor: '#b45309', fill: false, tension: 0.2, pointRadius: 2 },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: '投資成本 / 帳面收入' } },
      interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: false } }
    }
  });

  buildProfitRateChart(rows, labels);
}

async function loadAllProductData() {
  const start = document.getElementById('listStartDate').value;
  const end = document.getElementById('listEndDate').value;
  const res = await fetch(`/api/all-product-data?start=${start}&end=${end}`);
  const data = await res.json();
  const rows = data.rows || [];
  latestListingRows = rows;

  const tb = document.querySelector('#allDetailTable tbody');
  tb.innerHTML = rows.map((r) => `<tr>
    <td>${r.record_date}</td><td>${r.product}</td><td>${fmt(r.shares, 0)}</td><td>${fmt(r.current_price)}</td><td>${fmt(r.cost_price)}</td><td>${fmt(r.investment_cost)}</td><td>${fmt(r.book_income)}</td><td class="${profitClass(r.profit_loss)}">${fmt(r.profit_loss)}</td><td class="${profitClass(r.profit_loss_rate)}">${fmt(r.profit_loss_rate)}</td><td class="${profitClass(r.daily_profit_change)}">${fmt(r.daily_profit_change)}</td>
  </tr>`).join('');

  const info = document.getElementById('listingInfo');
  info.textContent = `排序：商品（遞減）＋日期（遞減）｜共 ${rows.length} 筆`;
  renderListingProductSelector(rows);
  renderListingCharts();
}

document.getElementById('productSelect').addEventListener('change', loadProductData);
document.getElementById('startDate').addEventListener('change', loadProductData);
document.getElementById('endDate').addEventListener('change', loadProductData);
document.getElementById('portfolioStartDate').addEventListener('change', loadPortfolioPageData);
document.getElementById('portfolioEndDate').addEventListener('change', loadPortfolioPageData);
document.getElementById('listStartDate').addEventListener('change', loadAllProductData);
document.getElementById('listEndDate').addEventListener('change', loadAllProductData);

refreshProducts();
</script>
</body>
</html>
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL,
                source_file TEXT NOT NULL,
                account TEXT,
                total_profit_loss REAL,
                total_profit_rate REAL,
                total_investment_cost REAL,
                record_count INTEGER DEFAULT 0,
                raw_summary_text TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(record_date, source_file)
            );

            CREATE TABLE IF NOT EXISTS daily_stock_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL,
                source_file TEXT NOT NULL,
                product TEXT NOT NULL,
                shares REAL,
                current_price REAL,
                cost_price REAL,
                investment_cost REAL,
                book_income REAL,
                profit_loss REAL,
                profit_loss_rate REAL,
                daily_profit_change REAL,
                raw_row_text TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(record_date, product)
            );
            """
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_stock_records)").fetchall()]
        if "shares" not in cols:
            conn.execute("ALTER TABLE daily_stock_records ADD COLUMN shares REAL")


def safe_float(text: str) -> Optional[float]:
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    t = t.replace(",", "")
    t = t.replace("％", "%")
    t = t.replace("−", "-")
    t = t.replace("—", "-")
    t = re.sub(r"[^0-9\-.%]", "", t)
    if not t:
        return None
    t = t.rstrip("%")
    try:
        return float(t)
    except ValueError:
        return None


def get_ocr_reader():
    global _OCR_READER
    if _OCR_READER is not None:
        return _OCR_READER
    with _OCR_LOCK:
        if _OCR_READER is None:
            _OCR_READER = easyocr.Reader(
                ["ch_tra", "en"],
                gpu=False,
                model_storage_directory=str(EASYOCR_MODEL_DIR),
                user_network_directory=str(EASYOCR_MODEL_DIR),
            )
    return _OCR_READER


def run_easyocr_lines(image_path: Path) -> List[Dict]:
    reader = get_ocr_reader()
    with Image.open(image_path) as src:
        img = src.convert("RGB")
    arr = np.array(img)
    ocr_items = reader.readtext(arr, detail=1, paragraph=False)
    if not ocr_items:
        return []

    raw_words = []
    for bbox, text, conf in ocr_items:
        if not text or conf < 0.2:
            continue
        xs = [pt[0] for pt in bbox]
        ys = [pt[1] for pt in bbox]
        left = float(min(xs))
        top = float(min(ys))
        raw_words.append({"text": text.strip(), "left": left, "top": top})

    if not raw_words:
        return []

    raw_words.sort(key=lambda x: (x["top"], x["left"]))
    # 將高度接近的文字視為同一行，避免欄位切分過細
    lines: List[Dict] = []
    current_bucket: List[Dict] = []
    current_top = None
    line_threshold = 18.0

    for w in raw_words:
        if current_top is None:
            current_bucket = [w]
            current_top = w["top"]
            continue
        if abs(w["top"] - current_top) <= line_threshold:
            current_bucket.append(w)
            current_top = (current_top + w["top"]) / 2
        else:
            parts = sorted(current_bucket, key=lambda x: x["left"])
            lines.append(
                {
                    "text": " ".join(p["text"] for p in parts).strip(),
                    "left": parts[0]["left"],
                    "top": min(p["top"] for p in parts),
                }
            )
            current_bucket = [w]
            current_top = w["top"]

    if current_bucket:
        parts = sorted(current_bucket, key=lambda x: x["left"])
        lines.append(
            {
                "text": " ".join(p["text"] for p in parts).strip(),
                "left": parts[0]["left"],
                "top": min(p["top"] for p in parts),
            }
        )

    return lines


def crop_top_region(image_path: Path) -> Path:
    with Image.open(image_path) as img:
        w, h = img.size
        # 多數券商截圖的主要表格在上半部，先裁上方 72% 提高 OCR 命中率
        cropped = img.crop((0, 0, w, int(h * 0.72)))
    out = image_path.with_name(f"{image_path.stem}_top{image_path.suffix}")
    cropped.save(out)
    return out


def cleanup_upload_files(*paths: Optional[Path]) -> None:
    for path in paths:
        if not path:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            app.logger.warning("清理上傳暫存檔失敗：%s (%s)", path, e)


def looks_like_product(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.search(r"\b(現價|成本價|投資成本|帳面收入|損益率|損益|總覽|帳號|頁次|合計)\b", t):
        return False
    has_code = re.search(r"\d{3,6}", t)
    has_cjk = re.search(r"[\u4e00-\u9fff]", t)
    return bool(has_code or has_cjk)


def parse_summary(lines: List[Dict], full_text: str, row_count: int) -> Dict:
    summary = {
        "account": "",
        "total_profit_loss": None,
        "total_profit_rate": None,
        "total_investment_cost": None,
        "record_count": row_count,
        "raw_summary_text": "",
    }

    top_text = "\n".join(line["text"] for line in lines[:14])
    summary["raw_summary_text"] = top_text

    acc_match = re.search(r"(帳號|帳戶|賬號)\s*[:：]?\s*([A-Za-z0-9\-]+)", full_text)
    if acc_match:
        summary["account"] = acc_match.group(2)
    else:
        # 常見格式：920F-5844164 舒忠
        acc_match2 = re.search(r"\b([A-Za-z0-9]{2,}-[A-Za-z0-9]{4,})\b", full_text)
        if acc_match2:
            summary["account"] = acc_match2.group(1)

    # 盡量抓靠近「總」或「合計」附近的數字
    candidates = []
    for line in lines[:22]:
        text = line["text"]
        if re.search(r"總|合計|總覽|全部", text):
            nums = re.findall(r"-?\d[\d,]*(?:\.\d+)?%?", text)
            candidates.extend(nums)

    if candidates:
        vals = [safe_float(x) for x in candidates]
        vals = [v for v in vals if v is not None]
        if vals:
            summary["total_profit_loss"] = vals[0]
        if len(vals) > 1:
            summary["total_profit_rate"] = vals[1]
        if len(vals) > 2:
            summary["total_investment_cost"] = vals[2]

    if summary["total_profit_loss"] is None:
        m = re.search(r"損益[:：]?\s*(-?\d[\d,]*(?:\.\d+)?)", full_text)
        if m:
            summary["total_profit_loss"] = safe_float(m.group(1))

    if summary["total_profit_rate"] is None:
        m = re.search(r"損益[:：]?\s*-?\d[\d,]*(?:\.\d+)?\s*\(([-+]?\d[\d,]*(?:\.\d+)?)%\)", full_text)
        if m:
            summary["total_profit_rate"] = safe_float(m.group(1))

    return summary


def parse_table_rows(lines: List[Dict]) -> List[Dict]:
    rows = []
    header_idx = -1
    for idx, line in enumerate(lines):
        t = line["text"]
        score = sum(k in t for k in ["商品", "現價", "成本", "投資", "損益"])
        if score >= 3:
            header_idx = idx
            break

    data_lines = lines[header_idx + 1 :] if header_idx >= 0 else lines

    for line in data_lines:
        text = line["text"].replace("O", "0")
        if re.search(r"(頁次|總計|合計|總覽|註記|備註)", text):
            continue

        nums = re.findall(r"-?\d[\d,]*(?:\.\d+)?%?", text)
        if len(nums) < 4:
            continue

        pct_matches = [n for n in nums if "%" in n]
        if pct_matches:
            profit_loss_rate = safe_float(pct_matches[-1])
            core_nums = [safe_float(n) for n in nums if "%" not in n]
        else:
            profit_loss_rate = safe_float(nums[-1])
            core_nums = [safe_float(n) for n in nums[:-1]]

        core_nums = [x for x in core_nums if x is not None]
        if len(core_nums) < 5:
            continue

        # 從尾端固定回推欄位，避免前方欄位順序波動
        profit_loss = core_nums[-1]
        book_income = core_nums[-2]
        investment_cost = core_nums[-3]
        cost_price = core_nums[-4]
        current_price = core_nums[-5]
        shares = core_nums[-6] if len(core_nums) >= 6 else None

        product = ""
        m = re.search(r"(?:下單\s+)?明細\s+(.+?)\s+(現股|融資|融券|零股)\s", text)
        if m:
            product = m.group(1).strip()
        else:
            left_part = text
            for n in nums:
                left_part = left_part.replace(n, " ", 1)
            product = re.sub(r"\s+", " ", left_part).strip(" :-_\t")
            product = re.sub(r"^(下單|明細|功能)\s*", "", product)
            product = re.sub(r"\b(現股|融資|融券|零股)\b", " ", product)
            product = re.sub(r"\b(台|台幣|幣)\b$", "", product).strip()
            product = re.sub(r"\s+", " ", product).strip()

        if not looks_like_product(product):
            continue

        row = {
            "product": product,
            "shares": shares,
            "current_price": current_price,
            "cost_price": cost_price,
            "investment_cost": investment_cost,
            "book_income": book_income,
            "profit_loss": profit_loss,
            "profit_loss_rate": profit_loss_rate,
            "raw_row_text": text,
        }
        rows.append(row)

    # 依商品去重（保留最完整的一列）
    dedup: Dict[str, Dict] = {}
    for r in rows:
        k = r["product"]
        score = sum(v is not None for v in [r["shares"], r["current_price"], r["cost_price"], r["investment_cost"], r["book_income"], r["profit_loss"], r["profit_loss_rate"]])
        if k not in dedup:
            dedup[k] = r
        else:
            old_score = sum(v is not None for v in [dedup[k]["shares"], dedup[k]["current_price"], dedup[k]["cost_price"], dedup[k]["investment_cost"], dedup[k]["book_income"], dedup[k]["profit_loss"], dedup[k]["profit_loss_rate"]])
            if score > old_score:
                dedup[k] = r

    return list(dedup.values())


def recalc_daily_profit_change(product: Optional[str] = None) -> None:
    where = ""
    args: Tuple = ()
    if product:
        where = "WHERE product = ?"
        args = (product,)

    with get_conn() as conn:
        sql = f"""
            SELECT id, product, record_date, profit_loss
            FROM daily_stock_records
            {where}
            ORDER BY product, record_date
        """
        rows = conn.execute(sql, args).fetchall()
        prev_by_product: Dict[str, Optional[float]] = {}
        for row in rows:
            p = row["product"]
            prev = prev_by_product.get(p)
            curr = row["profit_loss"]
            daily = None
            if prev is not None and curr is not None:
                daily = float(curr) - float(prev)
            conn.execute(
                "UPDATE daily_stock_records SET daily_profit_change = ?, updated_at = ? WHERE id = ?",
                (daily, datetime.now().isoformat(timespec="seconds"), row["id"]),
            )
            prev_by_product[p] = curr


@app.route("/")
def index():
    return render_template_string(HTML, today=date.today().isoformat())


@app.route("/api/parse", methods=["POST"])
def api_parse():
    if "image" not in request.files:
        return jsonify({"error": "缺少 image 檔案"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "檔名不可為空"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg"}:
        return jsonify({"error": "僅支援 png/jpg/jpeg"}), 400

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved = UPLOAD_DIR / f"{stamp}_{Path(file.filename).name}"
    file.save(saved)
    top_img = None

    try:
        top_img = crop_top_region(saved)
        lines = run_easyocr_lines(top_img)
        if not lines:
            return jsonify({"error": "OCR 未擷取到文字，請確認截圖清晰且包含上方表格"}), 400
        full_text = "\n".join(line["text"] for line in lines)
        rows = parse_table_rows(lines)
        summary = parse_summary(lines, full_text, len(rows))

        return jsonify(
            {
                "summary": summary,
                "rows": rows,
                "source_file": saved.name,
                "debug": {"line_count": len(lines)},
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cleanup_upload_files(top_img, saved)


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(silent=True) or {}
    record_date = (data.get("record_date") or "").strip()
    source_file = (data.get("source_file") or "manual").strip() or "manual"
    summary = data.get("summary") or {}
    rows = data.get("rows") or []

    if not record_date:
        return jsonify({"error": "record_date 必填"}), 400

    try:
        datetime.strptime(record_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "record_date 格式需為 YYYY-MM-DD"}), 400

    cleaned_rows = []
    for r in rows:
        product = (r.get("product") or "").strip()
        if not product:
            continue
        cleaned_rows.append(
            {
                "product": product,
                "shares": safe_float(r.get("shares")),
                "current_price": safe_float(r.get("current_price")),
                "cost_price": safe_float(r.get("cost_price")),
                "investment_cost": safe_float(r.get("investment_cost")),
                "book_income": safe_float(r.get("book_income")),
                "profit_loss": safe_float(r.get("profit_loss")),
                "profit_loss_rate": safe_float(r.get("profit_loss_rate")),
                "raw_row_text": r.get("raw_row_text") or "",
            }
        )

    if not cleaned_rows:
        return jsonify({"error": "至少需一筆有效商品資料"}), 400

    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO daily_summary (
                record_date, source_file, account, total_profit_loss,
                total_profit_rate, total_investment_cost, record_count,
                raw_summary_text, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_date, source_file) DO UPDATE SET
                account = excluded.account,
                total_profit_loss = excluded.total_profit_loss,
                total_profit_rate = excluded.total_profit_rate,
                total_investment_cost = excluded.total_investment_cost,
                record_count = excluded.record_count,
                raw_summary_text = excluded.raw_summary_text,
                updated_at = excluded.updated_at
            """,
            (
                record_date,
                source_file,
                (summary.get("account") or "").strip(),
                safe_float(summary.get("total_profit_loss")),
                safe_float(summary.get("total_profit_rate")),
                safe_float(summary.get("total_investment_cost")),
                int(summary.get("record_count") or len(cleaned_rows)),
                (summary.get("raw_summary_text") or "").strip(),
                now,
                now,
            ),
        )

        for row in cleaned_rows:
            conn.execute(
                """
                INSERT INTO daily_stock_records (
                    record_date, source_file, product, current_price,
                    shares, cost_price, investment_cost, book_income, profit_loss,
                    profit_loss_rate, daily_profit_change, raw_row_text,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                ON CONFLICT(record_date, product) DO UPDATE SET
                    source_file = excluded.source_file,
                    current_price = excluded.current_price,
                    shares = excluded.shares,
                    cost_price = excluded.cost_price,
                    investment_cost = excluded.investment_cost,
                    book_income = excluded.book_income,
                    profit_loss = excluded.profit_loss,
                    profit_loss_rate = excluded.profit_loss_rate,
                    raw_row_text = excluded.raw_row_text,
                    updated_at = excluded.updated_at
                """,
                (
                    record_date,
                    source_file,
                    row["product"],
                    row["current_price"],
                    row["shares"],
                    row["cost_price"],
                    row["investment_cost"],
                    row["book_income"],
                    row["profit_loss"],
                    row["profit_loss_rate"],
                    row["raw_row_text"],
                    now,
                    now,
                ),
            )

    recalc_daily_profit_change()

    return jsonify({"ok": True, "saved_count": len(cleaned_rows)})


@app.route("/api/products")
def api_products():
    with get_conn() as conn:
        prods = [r[0] for r in conn.execute("SELECT DISTINCT product FROM daily_stock_records ORDER BY product").fetchall()]
        min_date_row = conn.execute("SELECT MIN(record_date) FROM daily_stock_records").fetchone()
        min_date = min_date_row[0] if min_date_row and min_date_row[0] else None
    return jsonify({"products": prods, "min_date": min_date})


@app.route("/api/portfolio-totals")
def api_portfolio_totals():
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()

    clauses = ["1=1"]
    args: List = []
    if start:
        clauses.append("record_date >= ?")
        args.append(start)
    if end:
        clauses.append("record_date <= ?")
        args.append(end)
    where = " AND ".join(clauses)

    with get_conn() as conn:
        as_of_row = conn.execute(
            f"""
            SELECT MAX(record_date)
            FROM daily_stock_records
            WHERE {where}
            """,
            args,
        ).fetchone()
        as_of_date = as_of_row[0] if as_of_row and as_of_row[0] else None
        if not as_of_date:
            return jsonify(
                {
                    "as_of_date": None,
                    "total_investment_cost": None,
                    "total_book_income": None,
                    "total_profit_loss": None,
                }
            )

        totals = conn.execute(
            """
            SELECT SUM(investment_cost) AS total_investment_cost,
                   SUM(book_income) AS total_book_income,
                   SUM(profit_loss) AS total_profit_loss
            FROM daily_stock_records
            WHERE record_date = ?
            """,
            (as_of_date,),
        ).fetchone()

    return jsonify(
        {
            "as_of_date": as_of_date,
            "total_investment_cost": totals["total_investment_cost"],
            "total_book_income": totals["total_book_income"],
            "total_profit_loss": totals["total_profit_loss"],
        }
    )


@app.route("/api/portfolio-totals-series")
def api_portfolio_totals_series():
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()

    clauses = ["1=1"]
    args: List = []
    if start:
        clauses.append("record_date >= ?")
        args.append(start)
    if end:
        clauses.append("record_date <= ?")
        args.append(end)
    where = " AND ".join(clauses)

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT record_date,
                   SUM(investment_cost) AS total_investment_cost,
                   SUM(book_income) AS total_book_income,
                   SUM(profit_loss) AS total_profit_loss,
                   CASE
                     WHEN SUM(investment_cost) IS NULL OR SUM(investment_cost) = 0 THEN NULL
                     ELSE (SUM(profit_loss) * 100.0 / SUM(investment_cost))
                   END AS total_profit_rate
            FROM daily_stock_records
            WHERE {where}
            GROUP BY record_date
            ORDER BY record_date
            """,
            args,
        ).fetchall()

    return jsonify({"rows": [dict(r) for r in rows]})


@app.route("/api/product-data")
def api_product_data():
    product = (request.args.get("product") or "").strip()
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()

    if not product:
        return jsonify({"error": "product 必填"}), 400

    clauses = ["product = ?"]
    args: List = [product]
    if start:
        clauses.append("record_date >= ?")
        args.append(start)
    if end:
        clauses.append("record_date <= ?")
        args.append(end)

    where = " AND ".join(clauses)

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT record_date, product, current_price, cost_price,
                   shares,
                   investment_cost, book_income, profit_loss,
                   profit_loss_rate, daily_profit_change
            FROM daily_stock_records
            WHERE {where}
            ORDER BY record_date
            """,
            args,
        ).fetchall()

    return jsonify({"rows": [dict(r) for r in rows]})


@app.route("/api/all-product-data")
def api_all_product_data():
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()

    clauses = ["1=1"]
    args: List = []
    if start:
        clauses.append("record_date >= ?")
        args.append(start)
    if end:
        clauses.append("record_date <= ?")
        args.append(end)

    where = " AND ".join(clauses)

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT record_date, product, current_price, cost_price,
                   shares,
                   investment_cost, book_income, profit_loss,
                   profit_loss_rate, daily_profit_change
            FROM daily_stock_records
            WHERE {where}
            ORDER BY product DESC, record_date DESC
            """,
            args,
        ).fetchall()

    return jsonify({"rows": [dict(r) for r in rows]})


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=8765, debug=True)
else:
    init_db()
