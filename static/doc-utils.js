// 문서 화면(index)과 인쇄 화면(print)이 함께 쓰는 금액 함수

function won(n){ return (Number(n)||0).toLocaleString('ko-KR'); }

// 숫자 → 한글 금액 (예: 2420000 → 이백사십이만)
function korNum(n){
  n = Math.floor(Number(n)||0);
  if(!n) return '영';
  const D = ['','일','이','삼','사','오','육','칠','팔','구'], S = ['','십','백','천'], B = ['','만','억','조'];
  let out = '', g = 0;
  while(n > 0){
    const part = n % 10000;
    if(part){
      let s = '';
      String(part).padStart(4,'0').split('').forEach((c,i) => {
        const v = +c, u = 3 - i;
        if(!v) return;
        s += (v === 1 && u > 0 ? '' : D[v]) + S[u];
      });
      if(part === 1 && g > 0) s = '일';
      out = s + B[g] + out;
    }
    n = Math.floor(n / 10000); g++;
  }
  return out;
}

// 부가세: 'excluded' 별도(10% 더함) · 'included' 포함 · 'none' 없음(현금 등)
function itemTax(amount, vatMode){ return vatMode === 'none' ? 0 : Math.round(amount * 0.1); }
function vatLabel(vatMode){ return {included:'부가세포함', none:'부가세 없음'}[vatMode] || '부가세별도'; }

// 품목 합계: 공급가액, 세액, 합계
function sumItems(items, vatMode){
  let supply = 0, tax = 0;
  (items||[]).forEach(it => { const a = Math.round((+it.qty||0)*(+it.price||0)); supply += a; tax += itemTax(a, vatMode); });
  return {supply, tax, total: supply + tax};
}

// 입금계좌: 설정에 한 줄에 하나씩 · 문서마다 고른 계좌 (명세서는 안 고르면 첫 번째 계좌)
function bankList(co){ return String(co.bank || '').split('\n').map(s => s.trim()).filter(Boolean); }
function docBank(doc, co){
  const d = doc.data || {};
  if('bank' in d) return d.bank || '';
  return doc.doc_type === 'statement' ? (bankList(co)[0] || '') : '';
}
