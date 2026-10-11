'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (n, digits = 2) => Number.isFinite(n) ? new Intl.NumberFormat('ru-RU', {maximumFractionDigits:digits, minimumFractionDigits:digits}).format(n) : '—';
const usd = n => Number.isFinite(n) ? '$' + number(n) : '—';
const pct = n => Number.isFinite(n) ? (n > 0 ? '+' : '') + number(n) + '%' : '—';
const tone = n => n > 0 ? 'positive' : n < 0 ? 'negative' : '';
const date = (t, full = true) => t ? new Intl.DateTimeFormat('ru-RU', {timeZone:'Europe/Moscow', day:'2-digit', month:'2-digit', ...(full ? {hour:'2-digit',minute:'2-digit',second:'2-digit'} : {year:'numeric'})}).format(new Date(t*1000)) : 'Ещё не было';
const day = t => new Intl.DateTimeFormat('ru-RU', {timeZone:'UTC', day:'2-digit',month:'2-digit',year:'numeric'}).format(new Date(t*1000));
const ago = (t, now) => !t ? 'нет данных' : Math.max(0,Math.floor(now-t)) < 60 ? `${Math.max(0,Math.floor(now-t))}с назад` : `${Math.floor((now-t)/60)}мин назад`;
const names = {trend:'VECTOR', reversion:'ORBIT', breakout:'PULSE', benchmark:'BUY & HOLD'};
const decisions = {BUY:'ВХОД',SELL:'ВЫХОД',WAIT:'ОЖИДАНИЕ',HOLD:'УДЕРЖАНИЕ',HALTED:'РИСК ОСТАНОВЛЕН'};
let snapshot = null, report = null, mode = 'live', disconnected = false;

function renderRanking() {
  $('ranking').innerHTML = snapshot.agents.map((a,i) => `<div class="rank-row"><span class="rank-no">0${i+1}</span><div><div class="rank-name"><span class="dot" data-agent="${esc(a.id)}"></span>${esc(a.name)}</div><div class="rank-detail">${usd(a.state.equity)}</div></div><div class="rank-number ${tone(a.state.return_pct)}">${pct(a.state.return_pct)}<div class="rank-detail">DD ${number(a.state.max_drawdown*100)}%</div></div></div>`).join('');
}

function renderAgents() {
  const open = new Set([...document.querySelectorAll('.rules[open]')].map(el=>el.id));
  const system = snapshot.system;
  $('agent-cards').innerHTML = snapshot.agents.map(a => {
    const s = a.state, p = s.position;
    const state = s.halted ? 'Риск остановлен' : disconnected || !system.ready ? 'Цикл заблокирован' : p ? 'В позиции' : 'Ожидает сигнал';
    let position = 'Позиции нет. Средства в виртуальных USD.';
    if (p) {
      const current = system.quote?.bid;
      const net = current ? p.qty*current*(1-.0005)*(1-.001) : null;
      const pnl = net !== null ? net-p.cost : null;
      position = `<strong>${number(p.qty,6)} BTC</strong> · вход ${usd(p.entry)}<br>Стоп ${usd(p.stop)} · цель ${usd(p.take)}<br>Оценка P&amp;L: <span class="${tone(pnl)}">${usd(pnl)}</span> · открыта ${date(p.opened_at)}<br>По последнему bid с выходными издержками.`;
    }
    const blocked = disconnected ? 'Связь с API потеряна; данные ниже сохранены с прошлого ответа.' : !system.ready ? system.current_error || 'Нет подтверждения свежего серверного цикла. Торговля недоступна.' : '';
    return `<article class="panel agent-card" data-agent="${esc(a.id)}"><div class="agent-head"><div class="agent-identity"><span class="agent-icon">${esc(a.name[0])}</span><div><h3>${esc(a.name)}</h3><small>${esc(a.style)}</small></div></div><span class="state-tag ${s.halted?'halted':p && system.ready && !disconnected?'open':''}">${esc(state)}</span></div><p class="agent-description">${esc(a.description)}</p><dl class="agent-stats"><div><dt>Капитал</dt><dd>${usd(s.equity)}</dd></div><div><dt>Доходность</dt><dd class="${tone(s.return_pct)}">${pct(s.return_pct)}</dd></div><div><dt>Макс. просадка</dt><dd>${number(s.max_drawdown*100)}%</dd></div><div><dt>Комиссии</dt><dd>${usd(s.fees)}</dd></div></dl><div class="decision"><span class="decision-label">${esc(decisions[s.last_decision] || s.last_decision)}</span>${blocked?`<p class="negative">${esc(blocked)}</p>`:''}<p>${esc(s.reason)}</p><time>${s.last_run ? 'Последнее решение · '+date(s.last_run) : 'Свежие данные ещё не анализировались'}</time></div><div class="position-box">${position}</div><details class="rules" id="rules-${esc(a.id)}" ${open.has('rules-'+a.id)?'open':''}><summary>Правила стратегии и риск</summary><p><b>Вход.</b> ${esc(a.entry_rule)}</p><p><b>Выход.</b> ${esc(a.exit_rule)}</p><p>Риск на сделку ${number(a.risk*100,1)}% капитала; доля позиции не выше ${number(a.allocation*100,0)}%. Гэп может превысить стоп.</p><p>Завершённых сделок: ${s.trades}. Win rate: ${s.win_rate===null?'недостаточно данных':number(s.win_rate,1)+'%'}. Реализованный P&amp;L: ${usd(s.realized_pnl)}.</p></details><div class="risk-line"><span>SL ${number(a.stop*100,0)}%</span><span>TP ${number(a.take*100,0)}%</span><span>ЛИМИТ DD ${number(a.max_drawdown*100,0)}%</span></div></article>`;
  }).join('');
}

function renderTrades() {
  if (!snapshot) return;
  const selected = $('trade-filter').value;
  const trades = snapshot.trades.filter(t=>selected==='all'||t.agent_id===selected);
  if (!trades.length) {
    $('trade-list').innerHTML = '<div class="empty-state">Пока нет исполненных сделок.<br>Агенты ждут условий своих стратегий. Сделки ради активности не создаются.</div>';
    return;
  }
  $('trade-list').innerHTML = `<table><thead><tr><th>Время / агент</th><th>Сторона</th><th>Цена / объём</th><th>Причина</th><th>P&amp;L / комиссия</th></tr></thead><tbody>${trades.map(t=>`<tr><td>${date(t.time)}<div class="rank-detail">${esc(names[t.agent_id] || t.agent_id)}</div></td><td><span class="trade-side ${t.side==='SELL'?'sell':''}">${esc(t.side)}</span></td><td>${usd(t.price)}<div class="rank-detail">${number(t.qty,6)} BTC</div></td><td class="trade-reason">${esc(t.reason)}</td><td><span class="${tone(t.pnl)}">${t.pnl===null?'—':usd(t.pnl)}</span><div class="rank-detail">ком. ${usd(t.fee)}</div></td></tr>`).join('')}</tbody></table>`;
}

function renderSystem() {
  const s = snapshot.system, now = snapshot.server_time;
  const status = disconnected ? 'offline' : s.status;
  const label = disconnected ? 'Связь с API потеряна' : s.ready ? 'Серверный цикл работает' : s.worker_alive ? 'Worker запущен, торговля заблокирована' : 'Worker не подтверждён';
  $('connection').dataset.status = status;
  $('connection').innerHTML = `<span class="dot"></span>${esc(label)} · ${s.quote ? 'котировка '+ago(s.quote.time,now) : 'свежих котировок ещё нет'} · PAPER ONLY`;
  $('system-light').dataset.status = status;
  const rows = [
    ['Состояние',label],['Источник',s.quote?.source || 'Coinbase BTC-USD · публичный API'],
    ['Время котировки',s.quote?date(s.quote.time):'Нет данных'],['Свежесть',s.quote_fresh?'До 60с':'Торговля запрещена'],
    ['Успешный цикл',date(s.last_cycle)],['Heartbeat worker',date(s.heartbeat)],
    ['Запуск worker',date(s.worker_started)],['Закрытая свеча',s.candle_time?date(s.candle_time,false)+' · '+s.candle_count+' свечей':'Нет данных'],
    ['Следующая попытка',s.retry_at?date(s.retry_at):'Обычный интервал 30с'],['Ответ API',date(snapshot.server_time)],
  ];
  $('system-details').innerHTML = rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
  $('system-errors').innerHTML = (s.current_error ? `<div class="error-item"><strong>Торговлю блокирует ошибка</strong><br>${esc(s.current_error)}</div>`:'') + (snapshot.errors.length ? `<details class="errors-history"><summary>Недавние ошибки (${snapshot.errors.length})</summary>${snapshot.errors.map(e=>`<div class="error-item"><time>${date(e.time)}</time>${esc(e.message)}</div>`).join('')}</details>`:'<p class="chart-note">В журнале нет зарегистрированных ошибок.</p>');
}

function renderChart() {
  const historical = mode==='history';
  $('chart-period').disabled = historical;
  $('live-tab').classList.toggle('selected', !historical);
  $('history-tab').classList.toggle('selected', historical);
  $('live-tab').setAttribute('aria-pressed',String(!historical));
  $('history-tab').setAttribute('aria-pressed',String(historical));
  let series = [];
  if (historical && report) {
    series = [...report.agents.map(a=>({id:a.id, name:a.name, curve:a.curve})),{id:'benchmark',name:'BUY & HOLD',curve:report.benchmark.curve}];
    $('chart-context').textContent = `${day(report.start)} — ${day(report.end)} · дневные наблюдения`;
    $('chart-note').textContent = 'Историческая модель с издержками. Стопы наблюдаются раз в день; внутридневное исполнение этим тестом не подтверждено.';
  } else if (!historical && snapshot) {
    const days = $('chart-period').value;
    const start = days==='all'?0:snapshot.server_time-Number(days)*86400;
    series = snapshot.agents.map(a=>({id:a.id,name:a.name,curve:a.curve.filter(p=>p.time>=start)}));
    $('chart-context').textContent = 'Доходность от $10 000 на агента';
    $('chart-note').textContent = 'Последние 1000 почасовых точек из SQLite. Оценка ликвидации по последнему bid с выходными издержками.';
  }
  $('chart-legend').innerHTML = series.map(s=>`<span class="legend-item" data-agent="${esc(s.id)}">${esc(s.name)}</span>`).join('');
  const curves = series.filter(s=>s.curve.length>1);
  if (!curves.length) {
    $('capital-chart').innerHTML = `<div class="empty-state">${historical?'Исторический отчёт пока недоступен.':'Недостаточно сохранённых наблюдений для графика.<br>Первый участок появится после двух почасовых точек worker.'}</div>`;
    return;
  }
  const all = curves.flatMap(s=>s.curve);
  const minT = Math.min(...all.map(p=>p.time)), maxT = Math.max(...all.map(p=>p.time));
  const initial = historical ? report.initial_cash : snapshot.initial_cash;
  const values = all.map(p=>(p.equity/initial-1)*100);
  let minV = Math.min(0,...values), maxV = Math.max(0,...values);
  const pad = Math.max((maxV-minV)*.1,.2); minV-=pad;maxV+=pad;
  const x = t=>55+(t-minT)/(maxT-minT||1)*620;
  const y = v=>185-(v-minV)/(maxV-minV)*165;
  const grids = Array.from({length:5},(_,i)=>{
    const v=minV+(maxV-minV)*i/4;
    return `<line class="grid-line" x1="55" x2="675" y1="${y(v)}" y2="${y(v)}"/><text class="chart-label" x="45" y="${y(v)+3}" text-anchor="end">${number(v,1)}%</text>`;
  }).join('');
  const lines = curves.map(s=>`<polyline class="chart-line" data-agent="${esc(s.id)}" points="${s.curve.map(p=>`${x(p.time).toFixed(2)},${y((p.equity/initial-1)*100).toFixed(2)}`).join(' ')}"><title>${esc(s.name)}: ${pct((s.curve.at(-1).equity/initial-1)*100)}</title></polyline>`).join('');
  const labels = [0,.5,1].map(f=>`<text class="chart-label" x="${55+f*620}" y="210" text-anchor="${f===0?'start':f===1?'end':'middle'}">${day(minT+f*(maxT-minT))}</text>`).join('');
  $('capital-chart').innerHTML = `<svg viewBox="0 0 700 225" role="img" aria-label="Доходность стратегий за период ${day(minT)} — ${day(maxT)}">${grids}<line class="zero-line" x1="55" x2="675" y1="${y(0)}" y2="${y(0)}"/>${lines}${labels}</svg>`;
}

function renderReport() {
  if (!report) return;
  $('history-description').textContent = `${day(report.start)} — ${day(report.end)} · ${report.observations} дневных наблюдений после прогрева. Все позиции закрыты в конце теста, издержки учтены.`;
  const rows = [...report.agents.map(a=>({...a,name:a.name,status:a.halted?'Лимит риска достигнут':'Тест завершён'})),{...report.benchmark,name:'BUY & HOLD BTC',closed_trades:1,status:'Удержание всего капитала'}];
  $('history-results').innerHTML = `<table><thead><tr><th>Стратегия</th><th>Итоговый капитал</th><th>Доходность</th><th>Макс. просадка</th><th>Сделок закрыто</th><th>Результат проверки</th></tr></thead><tbody>${rows.map(a=>`<tr><td>${esc(a.name)}</td><td>${usd(a.equity)}</td><td class="${tone(a.return_pct)}">${pct(a.return_pct)}</td><td>${number(a.max_drawdown*100)}%</td><td>${a.closed_trades}</td><td>${esc(a.status)}</td></tr>`).join('')}</tbody></table>`;
  $('history-method').innerHTML = `<p>${esc(report.model)}</p><p>Комиссия ${number(report.fee_rate*100,2)}%, проскальзывание ${number(report.slippage_rate*100,2)}% на каждой стороне. Начальный виртуальный капитал ${usd(report.initial_cash)}.</p><ul>${report.limitations.map(t=>`<li>${esc(t)}</li>`).join('')}</ul><p>Данные: <a href="${esc(report.source.url)}" target="_blank" rel="noopener noreferrer">Coin Metrics · PriceUSD</a>, CC BY 4.0. Исходные наблюдения: ${esc(report.source.first)} — ${esc(report.source.last)}. Живая торговля использует Coinbase; данные теста в её журнал не попадают.</p>`;
}

function render() {
  if (!snapshot) return;
  const total = snapshot.agents.reduce((sum,a)=>sum+a.state.equity,0);
  $('total-equity').textContent = usd(total);
  const totalReturn = (total/(snapshot.initial_cash*snapshot.agents.length)-1)*100;
  $('total-return').textContent = `${pct(totalReturn)} · по последней оценке капитала`;
  $('total-return').className = tone(totalReturn);
  $('market-price').textContent = usd(snapshot.system.quote?.price);
  $('price-time').textContent = snapshot.system.quote ? date(snapshot.system.quote.time)+' МСК' : 'Нет свежей рыночной котировки';
  $('position-count').textContent = snapshot.agents.filter(a=>a.state.position).length+' / '+snapshot.agents.length;
  $('trade-count').textContent = snapshot.agents.reduce((n,a)=>n+a.state.trades,0);
  $('fee-total').textContent = 'Комиссии · '+usd(snapshot.agents.reduce((n,a)=>n+a.state.fees,0));
  renderRanking();renderAgents();renderTrades();renderSystem();renderChart();
}

async function fetchJson(path) {
  const response = await fetch(path, {cache:'no-store',signal:AbortSignal.timeout(8000)});
  if (!response.ok) throw new Error('HTTP '+response.status);
  return response.json();
}

async function poll() {
  try {snapshot=await fetchJson('/api/snapshot');disconnected=false;render();}
  catch(error) {
    disconnected=true;
    if(snapshot) {renderAgents();renderSystem();}
    else {
      $('connection').dataset.status='offline';
      $('connection').innerHTML='<span class="dot"></span>API недоступен. Повторим подключение через 10 секунд.';
      $('agent-cards').innerHTML='<div class="panel empty-state">Нет ответа от API. Состояния агентов пока неизвестны.</div>';
      $('system-details').innerHTML='<dt>Состояние</dt><dd>API недоступен</dd>';
    }
  } finally {setTimeout(poll,10000);}
}
$('live-tab').addEventListener('click',()=>{mode='live';renderChart();});
$('history-tab').addEventListener('click',()=>{mode='history';renderChart();});
$('chart-period').addEventListener('change',renderChart);
$('trade-filter').addEventListener('change',renderTrades);
fetchJson('/api/backtest').then(data=>{report=data;renderReport();renderChart();}).catch(()=>{
  $('history-description').textContent='Исторический отчёт недоступен. Результаты не подставляются.';
});
poll();
