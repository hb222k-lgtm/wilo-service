// 문서 배치 — 레터형 · 카드형 · 사이드바형 (표형은 print.html)
// 색은 시안(.theme-*)의 CSS 변수(--accent, --lab-bg, --soft …)를 따른다.
// print.html의 esc · won · korNum · sumItems · stampImg · logoImg 등을 그대로 사용.

const LAYOUTS = {};

const TRADE = {
  quote: {
    title: '견 적 서', plain: '견적서', en: 'QUOTATION', numbered: false,
    greet: '귀사의 일익 번창하심을 기원합니다. 아래와 같이 견적드리오니 검토 바랍니다.',
    meta: (doc, c, d) => [['공사명', doc.title], ['유효기간', d.valid_until],
      ['연락처', [c.tel && 'TEL ' + c.tel, c.fax && 'FAX ' + c.fax].filter(Boolean).join(' · ')]],
  },
  statement: {
    title: '거 래 명 세 서', plain: '거래명세서', en: 'STATEMENT', numbered: true,
    greet: '다음과 같이 계산합니다.',
    meta: (doc, c) => [['공사명', doc.title], ['사업자번호', c.biz_no], ['대표자', c.ceo], ['주소', c.address], ['연락처', c.tel]],
  },
};

function lyItems(doc){ return (doc.data.items || []).filter(it => it.name || it.price); }
function lyAmount(it){ return Math.round((+it.qty || 0) * (+it.price || 0)); }
function lyDate(d){ return dot(d).replace(/\//g, '.'); }
function lyVat(d){ return d.vat_mode === 'none' ? '부가세 없음' : 'VAT 포함'; }
function lyMeta(rows){
  return rows.filter(([, v]) => v).map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join('');
}
function lyPhotoCount(d){
  return (d.photo_layout || 'rows') === 'grid' ? (d.photos || []).length
    : (d.groups || []).reduce((n, g) => n + (g.photos || []).length, 0);
}
function lyStamp(co){ return `<span class="stamp-wrap">(인)${stampImg(co)}</span>`; }

// 품목표 — compact는 좁은 본문(사이드바형)용
function lyItemsTable(items, d, numbered, cls, minRows, compact){
  const w = compact ? [8, 11, 10, 20, 23, 18] : [9, 14, 13, 24, 27, 22];
  const head = `${numbered ? `<th class="c" style="width:${w[0]}mm">No</th>` : ''}<th>품목명</th>
    <th class="c" style="width:${w[1]}mm">규격</th><th class="c" style="width:${w[2]}mm">수량</th>
    <th class="r" style="width:${w[3]}mm">단가</th><th class="r" style="width:${w[4]}mm">공급가액</th><th class="r" style="width:${w[5]}mm">부가세</th>`;
  let rows = '';
  for(let i = 0; i < Math.max(minRows, items.length); i++){
    const it = items[i];
    if(!it){ rows += `<tr class="empty">${'<td></td>'.repeat(numbered ? 7 : 6)}</tr>`; continue; }
    const a = lyAmount(it);
    rows += `<tr>${numbered ? `<td class="c">${i + 1}</td>` : ''}<td>${esc(it.name)}</td><td class="c">${esc(it.spec)}</td>
      <td class="c">${esc(it.qty)}</td><td class="r">${won(it.price)}</td><td class="r">${won(a)}</td>
      <td class="r">${d.vat_mode === 'none' ? '-' : won(itemTax(a, d.vat_mode))}</td></tr>`;
  }
  return `<table class="${cls}"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
}

function lySums(t){
  return `<table class="ly-sum"><tr><th>공급가액</th><td>${won(t.supply)}</td></tr><tr><th>부가세</th><td>${won(t.tax)}</td></tr>
    <tr class="grand"><th>합계</th><td>₩ ${won(t.total)}</td></tr></table>`;
}

function completionInfo(doc){
  const d = doc.data, amt = +doc.supply_amount || 0;
  return [['공사명', doc.title], ['발주처', doc.client_name],
    ['계약금액', amt ? `일금 ${korNum(amt)}원정 (₩${won(amt)}, ${vatLabel(d.vat_mode)})` : ''],
    ['계약일자', ymdShort(d.contract_date)], ['착공일자', ymdShort(d.start_date)], ['준공일자', ymdShort(d.end_date)]];
}

// ── 레터형: 위쪽에 회사 머리글, 큰 합계 금액, 줄무늬 품목표 ─────────────────
function letterHead(co, title, doc){
  return `<div class="lt-head">
    <div class="lt-co"><div class="lt-co-name">${esc(co.name)}</div>
      <div class="lt-co-info">${esc(co.address)}<br>TEL ${esc(co.tel)}${co.fax ? ' · FAX ' + esc(co.fax) : ''}${co.email ? ' · ' + esc(co.email) : ''}
        <br>사업자번호 ${esc(co.biz_no)} · 대표 ${esc(co.ceo)}</div></div>
    <div class="lt-doc">${logoImg(co)}<div class="lt-title">${title}</div>
      <div class="lt-meta">${doc.doc_no ? esc(doc.doc_no) + ' · ' : ''}${lyDate(doc.doc_date)}</div></div>
  </div>`;
}

function letterTrade(doc, co, kind){
  const d = doc.data, c = d.client || {}, K = TRADE[kind];
  const items = lyItems(doc), t = sumItems(items, d.vat_mode), bank = docBank(doc, co);
  return `<div class="sheet ly-letter">
    ${letterHead(co, K.title, doc)}
    <div class="lt-to">
      <div class="lt-to-l"><div class="lt-to-name">${esc(doc.client_name)} <small>귀하</small></div>
        <table class="ly-dl">${lyMeta(K.meta(doc, c, d))}</table>
        <p class="lt-greet">${K.greet}</p></div>
      <div class="lt-total"><div class="lab">합계 금액 (${lyVat(d)})</div><div class="num">₩ ${won(t.total)}</div>
        <div class="kor">금 ${korNum(t.total)}원 정</div></div>
    </div>
    ${lyItemsTable(items, d, K.numbered, 'ly-items lt-items', 10)}
    ${lySums(t)}
    <div class="lt-foot">
      <div class="lt-note">
        ${d.note ? `<b>비고</b><p class="multiline">${esc(d.note)}</p>` : ''}
        ${bank ? `<b>입금계좌</b><p>${esc(bank)}</p>` : ''}
        ${kind === 'statement' ? '<b>인수자 확인</b><p class="lt-recv">(인)</p>' : ''}
      </div>
      <div class="ly-sign"><div>${ymd(doc.doc_date)}</div><b>${esc(co.name)}</b><div>대표 ${esc(co.ceo)} ${lyStamp(co)}</div></div>
    </div>
  </div>`;
}

function letterCompletion(doc, co){
  const d = doc.data;
  return `<div class="sheet ly-letter">
    ${letterHead(co, '작업완료확인서', doc)}
    <div class="wc2-lead">아래 공사를 완료하였음을 확인합니다.</div>
    <table class="wc2-info">${completionInfo(doc).map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join('')}</table>
    <div class="wc2-attach">별첨 : 작업사진 ${lyPhotoCount(d)}매</div>
    <div class="wc2-date">${ymd(doc.doc_date)}</div>
    <div class="wc2-signs">
      <div class="wc2-sign"><div class="k">발주처 확인</div><div class="v">${esc(doc.client_name)}</div><div class="line">확인자 <span class="blank"></span> (인)</div></div>
      <div class="wc2-sign"><div class="k">시공사</div><div class="v">${esc(co.name)}</div><div class="line">대표 ${esc(co.ceo)} ${lyStamp(co)}</div></div>
    </div>
  </div>` + renderCompletionPhotos(d);
}

// ── 카드형: 둥근 상자로 정보를 나누고, 선 없는 품목표 ─────────────────────
function cardTop(co, K, doc){
  return `<div class="cd-top"><div><div class="cd-title">${K.plain}</div>
      <div class="cd-sub">${K.en}${doc.doc_no ? ' · ' + esc(doc.doc_no) : ''} · ${lyDate(doc.doc_date)}</div></div>
    <div class="cd-brand">${logoImg(co)}<div class="cd-brand-name">${esc(co.name)}</div></div></div>`;
}

function cardTrade(doc, co, kind){
  const d = doc.data, c = d.client || {}, K = TRADE[kind];
  const items = lyItems(doc), t = sumItems(items, d.vat_mode), bank = docBank(doc, co);
  const sub1 = kind === 'quote'
    ? [c.tel && 'TEL ' + c.tel, c.fax && 'FAX ' + c.fax].filter(Boolean).join(' · ')
    : [c.biz_no && '사업자 ' + c.biz_no, c.ceo && '대표 ' + c.ceo].filter(Boolean).join(' · ') + (c.address ? '<br>' + esc(c.address) : '');
  const sub2 = kind === 'quote' ? (d.valid_until ? '유효기간 ' + esc(d.valid_until) : '') : (c.tel ? '연락처 ' + esc(c.tel) : '');
  return `<div class="sheet ly-card">
    ${cardTop(co, K, doc)}
    <div class="cd-cards three">
      <div class="cd-card"><div class="cd-k">${kind === 'quote' ? '받는 분' : '공급받는자'}</div><div class="cd-v">${esc(doc.client_name)}</div><div class="cd-s">${sub1}</div></div>
      <div class="cd-card"><div class="cd-k">공사명</div><div class="cd-v">${esc(doc.title)}</div><div class="cd-s">${sub2}</div></div>
      <div class="cd-card acc"><div class="cd-k">합계 금액 · ${lyVat(d)}</div><div class="cd-v big">₩${won(t.total)}</div><div class="cd-s">금 ${korNum(t.total)}원 정</div></div>
    </div>
    <div class="cd-greet">${K.greet}</div>
    ${lyItemsTable(items, d, K.numbered, 'ly-items cd-items', 10)}
    <div class="cd-chips"><span>공급가액 <b>${won(t.supply)}</b></span><span>부가세 <b>${won(t.tax)}</b></span>
      <span class="acc">합계 <b>₩${won(t.total)}</b></span></div>
    <div class="cd-cards two">
      <div class="cd-card"><div class="cd-k">비고 · 결제</div><div class="cd-p multiline">${esc(d.note)}</div>
        ${bank ? `<div class="cd-s">입금계좌 ${esc(bank)}</div>` : ''}
        ${kind === 'statement' ? '<div class="cd-s" style="margin-top:3mm">인수자 확인 <span class="blank"></span> (인)</div>' : ''}</div>
      <div class="cd-card"><div class="cd-k">공급자</div><div class="cd-v">${esc(co.name)}</div>
        <div class="cd-s">사업자번호 ${esc(co.biz_no)} · 대표 ${esc(co.ceo)} ${lyStamp(co)}</div>
        <div class="cd-s">${esc(co.address)}<br>TEL ${esc(co.tel)}${co.email ? ' · ' + esc(co.email) : ''}</div></div>
    </div>
  </div>`;
}

function cardCompletion(doc, co){
  const d = doc.data;
  return `<div class="sheet ly-card">
    ${cardTop(co, {plain: '작업완료확인서', en: 'COMPLETION'}, doc)}
    <div class="cd-lead">아래 공사를 완료하였음을 확인합니다.</div>
    <div class="cd-grid">${completionInfo(doc).map(([k, v]) =>
      `<div class="cd-card${k === '공사명' ? ' acc' : ''}"><div class="cd-k">${k}</div><div class="cd-v">${esc(v) || '-'}</div></div>`).join('')}</div>
    <div class="cd-attach">별첨 : 작업사진 ${lyPhotoCount(d)}매</div>
    <div class="wc2-date">${ymd(doc.doc_date)}</div>
    <div class="cd-cards two">
      <div class="cd-card"><div class="cd-k">발주처 확인</div><div class="cd-v">${esc(doc.client_name)}</div>
        <div class="cd-s" style="margin-top:5mm">확인자 <span class="blank"></span> (인)</div></div>
      <div class="cd-card"><div class="cd-k">시공사</div><div class="cd-v">${esc(co.name)}</div>
        <div class="cd-s" style="margin-top:5mm">대표 ${esc(co.ceo)} ${lyStamp(co)}</div></div>
    </div>
  </div>` + renderCompletionPhotos(d);
}

// ── 사이드바형: 왼쪽 색 띠에 회사 정보 · 직인, 오른쪽에 내용 ─────────────────
function sideBar(co, doc){
  const bank = doc.data.items ? docBank(doc, co) : '';
  return `<aside class="sd-bar">
    ${co.show_logo ? `<div class="sd-logo">${logoImg(co)}</div>` : ''}
    <div class="sd-name">${esc(co.name)}</div>
    <dl class="sd-info">
      <dt>대표</dt><dd>${esc(co.ceo)}</dd><dt>사업자번호</dt><dd>${esc(co.biz_no)}</dd>
      <dt>주소</dt><dd>${esc(co.address)}</dd><dt>전화</dt><dd>${esc(co.tel)}</dd>
      ${co.fax ? `<dt>팩스</dt><dd>${esc(co.fax)}</dd>` : ''}${co.email ? `<dt>이메일</dt><dd>${esc(co.email)}</dd>` : ''}
      ${bank ? `<dt>입금계좌</dt><dd>${esc(bank)}</dd>` : ''}
    </dl>
    <div class="sd-sign">${ymd(doc.doc_date)}<br><b>${esc(co.name)}</b><br>대표 ${esc(co.ceo)} ${lyStamp(co)}</div>
  </aside>`;
}

function sideTrade(doc, co, kind){
  const d = doc.data, c = d.client || {}, K = TRADE[kind];
  const items = lyItems(doc), t = sumItems(items, d.vat_mode);
  return `<div class="sheet ly-side">
    ${sideBar(co, doc)}
    <main class="sd-main">
      <div class="sd-title">${K.title}</div>
      <div class="sd-meta">${K.en}${doc.doc_no ? ' · ' + esc(doc.doc_no) : ''} · ${lyDate(doc.doc_date)}</div>
      <div class="sd-to"><div class="sd-to-name">${esc(doc.client_name)} <small>귀하</small></div>
        <table class="ly-dl">${lyMeta(K.meta(doc, c, d))}</table></div>
      <div class="sd-amount"><span>합계 금액 (${lyVat(d)})</span><b>₩ ${won(t.total)}</b><small>금 ${korNum(t.total)}원 정</small></div>
      <div class="sd-greet">${K.greet}</div>
      ${lyItemsTable(items, d, K.numbered, 'ly-items sd-items', 10, true)}
      ${lySums(t)}
      ${d.note ? `<div class="sd-note"><b>비고</b><span class="multiline">${esc(d.note)}</span></div>` : ''}
      ${kind === 'statement' ? '<div class="sd-note"><b>인수자 확인</b><span><span class="blank"></span> (인)</span></div>' : ''}
    </main>
  </div>`;
}

function sideCompletion(doc, co){
  const d = doc.data;
  return `<div class="sheet ly-side">
    ${sideBar(co, doc)}
    <main class="sd-main">
      <div class="sd-title">작업완료확인서</div>
      <div class="sd-meta">COMPLETION${doc.doc_no ? ' · ' + esc(doc.doc_no) : ''} · ${lyDate(doc.doc_date)}</div>
      <div class="wc2-lead" style="margin-top:8mm">아래 공사를 완료하였음을 확인합니다.</div>
      <table class="wc2-info">${completionInfo(doc).map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join('')}</table>
      <div class="wc2-attach">별첨 : 작업사진 ${lyPhotoCount(d)}매</div>
      <div class="wc2-signs one">
        <div class="wc2-sign"><div class="k">발주처 확인</div><div class="v">${esc(doc.client_name)}</div><div class="line">확인자 <span class="blank"></span> (인)</div></div>
      </div>
    </main>
  </div>` + renderCompletionPhotos(d);
}

// ── 계약서: 표 형식을 유지하면서 깔끔하게 (레터 · 카드 · 사이드바 공통) ────────
function prettyContract(doc, co){
  const d = doc.data, c = d.client || {}, amt = +doc.supply_amount || 0;
  const sp = s => esc((s || '').split('').join(' '));
  return `<div class="sheet ct2">
    <div class="ct2-head"><div class="ct2-title">공사도급표준계약서</div>
      <div class="ct2-date"><span>계약일자</span>${ymd(doc.doc_date)}</div></div>
    <div class="ct2-box"><table class="ct2-t">
      <colgroup><col style="width:13mm"><col style="width:30mm"><col><col style="width:30mm"><col style="width:38mm"></colgroup>
      <tr><td class="ct2-sec" rowspan="4">계<br>약<br>자</td><th>발주처</th><td colspan="3" class="b">${esc(doc.client_name)}</td></tr>
      <tr><th rowspan="3">계약대상자</th><td colspan="3"><span class="k">상호</span>${esc(co.name)}<span class="k gap">사업자등록번호</span>${esc(co.biz_no)}</td></tr>
      <tr><td colspan="3"><span class="k">주소</span>${esc(co.address)}</td></tr>
      <tr><td colspan="3"><span class="k">대표자</span>${sp(co.ceo)}<span class="k gap">전화</span>${esc(co.tel)}</td></tr>
    </table></div>
    <div class="ct2-box"><table class="ct2-t">
      <colgroup><col style="width:13mm"><col style="width:30mm"><col><col style="width:30mm"><col style="width:38mm"></colgroup>
      <tr><td class="ct2-sec" rowspan="8">계<br>약<br>내<br>용</td><th>공 사 명</th><td colspan="3" class="b">${esc(doc.title)}</td></tr>
      <tr><th>계 약 금</th><td colspan="3"><b>일금 ${korNum(amt)} 원정</b> ( ₩${won(amt)}원 / ${vatLabel(d.vat_mode)} )</td></tr>
      <tr><th>계약이행보증금</th><td>${esc(d.perf_bond)}</td><th>하자이행보증금</th><td>${esc(d.defect_bond)}</td></tr>
      <tr><th>하자담보기간</th><td colspan="3">${esc(d.warranty)}</td></tr>
      <tr><th>지체상금율</th><td colspan="3">${esc(d.delay_rate)}</td></tr>
      <tr><th>착공년월일</th><td>${ymd(d.start_date, true)}</td><th>준공년월일</th><td>${ymd(d.end_date, true)}</td></tr>
      <tr><th>기타사항</th><td colspan="3" class="multiline">${esc(d.etc_note)}</td></tr>
      <tr><th>붙임서류</th><td colspan="3">${esc(d.attachments)}</td></tr>
    </table></div>
    <div class="ct2-text">도급인("갑")과 수급인("을")은 상기와 같이 공사계약을 체결하고 신의에 성실히 계약상의 의무를 이행할 것을 확약하며,
      이 계약의 증서로서 계약서를 작성하여 당사자 간 기명, 날인 후 각각 1통씩 보관한다.</div>
    <div class="ct2-day">${ymd(doc.doc_date)}</div>
    <div class="ct2-signs">
      <div class="ct2-sign"><div class="who">"갑" 도급인</div><div class="name">${esc(doc.client_name)}</div>
        <table class="ct2-dl"><tr><th>주소</th><td>${esc(c.address)}</td></tr><tr><th>대표자</th><td>${sp(c.ceo)} ( 인 )</td></tr><tr><th>전화</th><td>${esc(c.tel)}</td></tr></table></div>
      <div class="ct2-sign"><div class="who">"을" 수급인</div><div class="name">${esc(co.name)}</div>
        <table class="ct2-dl"><tr><th>주소</th><td>${esc(co.address)}</td></tr><tr><th>대표자</th><td>${sp(co.ceo)} ${lyStamp(co)}</td></tr><tr><th>전화</th><td>${esc(co.tel)}</td></tr></table></div>
    </div>
  </div>`;
}

LAYOUTS.letter = {quote: (d, c) => letterTrade(d, c, 'quote'), statement: (d, c) => letterTrade(d, c, 'statement'),
                  contract: prettyContract, completion: letterCompletion};
LAYOUTS.card = {quote: (d, c) => cardTrade(d, c, 'quote'), statement: (d, c) => cardTrade(d, c, 'statement'),
                contract: prettyContract, completion: cardCompletion};
LAYOUTS.sidebar = {quote: (d, c) => sideTrade(d, c, 'quote'), statement: (d, c) => sideTrade(d, c, 'statement'),
                   contract: prettyContract, completion: sideCompletion};
