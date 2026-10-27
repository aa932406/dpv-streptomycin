
import fs from "node:fs";

export function parseCor(path){
  const txt = fs.readFileSync(path).toString("latin1");
  const lines = txt.split(/\r?\n/);
  const hdr = lines.findIndex(l=>/^E\(V\)|^Potential/.test(l));
  const m = txt.match(/Data:\s*(\S+)\s*Time:\s*(\S+)/) || [];
  const parmLine = lines.find(l=>l.startsWith("ExpParmas:")) || "";
  const parms = {};
  parmLine.replace(/^ExpParmas:/,"").split("&-&").forEach(kv=>{const i=kv.indexOf("="); if(i>0) parms[kv.slice(0,i)]=kv.slice(i+1);});
  const ocp = parseFloat((txt.match(/Open Circuit Potential \(V\):\s*(\S+)/)||[])[1] || "NaN");
  const rows=[];
  for(let i=hdr+1;i<lines.length;i++){
    const l=lines[i].trim(); if(!l) continue;
    const p=l.split(/[\s,]+/).map(Number);
    if(p.length>=2 && !isNaN(p[0]) && !isNaN(p[1])) rows.push([p[0],p[1],isNaN(p[2])?NaN:p[2]]);
  }
  return {file: path.split(/[\\/]/).pop(), type:(lines.find(l=>l.startsWith("ID_"))||"").trim(),
    date:m[1]||"", time:m[2]||"", ocp, parms, rows};
}

export function movingAvg(y,w){
  const out=new Array(y.length).fill(0);
  for(let i=0;i<y.length;i++){ let s=0,c=0; for(let k=-w;k<=w;k++){const j=i+k; if(j>=0&&j<y.length){s+=y[j];c++;}} out[i]=s/c; }
  return out;
}

// interpolate onto common grid (E descending)
export function resample(E, I, grid){
  const out=new Array(grid.length);
  // E descending; build ascending copies
  const idx=[...E.keys()].sort((a,b)=>E[a]-E[b]);
  const Ex=idx.map(i=>E[i]), Iy=idx.map(i=>I[i]);
  for(let g=0;g<grid.length;g++){
    const x=grid[g];
    if(x<Ex[0]||x>Ex[Ex.length-1]){ out[g]=NaN; continue; }
    let lo=0, hi=Ex.length-1;
    while(hi-lo>1){ const mid=(lo+hi)>>1; if(Ex[mid]<=x) lo=mid; else hi=mid; }
    const t=(x-Ex[lo])/((Ex[hi]-Ex[lo])||1e-12);
    out[g]=Iy[lo]+t*(Iy[hi]-Iy[lo]);
  }
  return out;
}

// linear baseline across a window, peak height relative to it
export function peakFeature(E, I, eHigh, eLow, frac=0.12){
  const inWin=[]; for(let i=0;i<E.length;i++) if(E[i]<=eHigh && E[i]>=eLow) inWin.push(i);
  if(inWin.length<5) return null;
  const S=movingAvg(I,1);
  let ip=inWin[0], best=S[inWin[0]];
  for(const i of inWin) if(S[i]<best){ best=S[i]; ip=i; }
  const edgePts=3;
  const atEdge = (ip-inWin[0]<edgePts) || (inWin[inWin.length-1]-ip<edgePts);
  if(atEdge) return {Ep:E[ip], Ip:S[ip], base:NaN, height:NaN, fwhm:NaN, area:NaN, slope:NaN, noPeak:true};
  const span=eHigh-eLow;
  const edge=Math.max(2, Math.round(inWin.length*frac));
  const left=inWin.slice(0,edge), right=inWin.slice(-edge);
  const xs=[...left,...right].map(i=>E[i]), ys=[...left,...right].map(i=>S[i]);
  const n=xs.length, mx=xs.reduce((a,b)=>a+b,0)/n, my=ys.reduce((a,b)=>a+b,0)/n;
  let sxy=0,sxx=0; for(let k=0;k<n;k++){ sxy+=(xs[k]-mx)*(ys[k]-my); sxx+=(xs[k]-mx)**2; }
  const slope=sxx?sxy/sxx:0, intercept=my-slope*mx;
  const base=slope*E[ip]+intercept;
  const height=base-S[ip];            // >0 when the peak goes below baseline (cathodic)
  // FWHM
  const half=base-height/2; let a=ip,b=ip;
  while(a>inWin[0] && S[a]<half) a--;
  while(b<inWin[inWin.length-1] && S[b]<half) b++;
  const fwhm=Math.abs(E[b]-E[a]);
  // area by trapezoid above baseline
  let area=0; for(let k=inWin[0];k<inWin[inWin.length-1];k++){
    const h1=Math.max(0,(slope*E[k]+intercept)-S[k]), h2=Math.max(0,(slope*E[k+1]+intercept)-S[k+1]);
    area += 0.5*(h1+h2)*Math.abs(E[k+1]-E[k]);
  }
  return {Ep:E[ip], Ip:S[ip], base, height, fwhm, area, slope};
}

export function trapz(x,y){ let s=0; for(let i=0;i<x.length-1;i++) s+=0.5*(y[i]+y[i+1])*Math.abs(x[i+1]-x[i]); return s; }

// ---------- statistics ----------
export function mean(v){ return v.reduce((a,b)=>a+b,0)/v.length; }
export function sd(v){ const m=mean(v); return Math.sqrt(v.reduce((a,b)=>a+(b-m)**2,0)/(v.length-1)); }
export function median(v){ const s=[...v].sort((a,b)=>a-b); const n=s.length; return n%2?s[(n-1)/2]:(s[n/2-1]+s[n/2])/2; }

function lgamma(x){ const g=[676.5203681218851,-1259.1392167224028,771.32342877765313,-176.61502916214059,
  12.507343278686905,-0.13857109526572012,9.9843695780195716e-6,1.5056327351493116e-7];
  if(x<0.5) return Math.log(Math.PI/Math.sin(Math.PI*x))-lgamma(1-x);
  x-=1; let a=0.99999999999980993; const t=x+7.5;
  for(let i=0;i<8;i++) a+=g[i]/(x+i+1);
  return 0.5*Math.log(2*Math.PI)+(x+0.5)*Math.log(t)-t+Math.log(a); }

function betacf(a,b,x){ const MAXIT=200, EPS=3e-12, FPMIN=1e-300;
  let qab=a+b, qap=a+1, qam=a-1, c=1, d=1-qab*x/qap;
  if(Math.abs(d)<FPMIN) d=FPMIN; d=1/d; let h=d;
  for(let m=1;m<=MAXIT;m++){ const m2=2*m;
    let aa=m*(b-m)*x/((qam+m2)*(a+m2));
    d=1+aa*d; if(Math.abs(d)<FPMIN) d=FPMIN; c=1+aa/c; if(Math.abs(c)<FPMIN) c=FPMIN; d=1/d; h*=d*c;
    aa=-(a+m)*(qab+m)*x/((a+m2)*(qap+m2));
    d=1+aa*d; if(Math.abs(d)<FPMIN) d=FPMIN; c=1+aa/c; if(Math.abs(c)<FPMIN) c=FPMIN; d=1/d;
    const del=d*c; h*=del; if(Math.abs(del-1)<EPS) break; }
  return h; }
export function betai(a,b,x){ if(x<=0) return 0; if(x>=1) return 1;
  const bt=Math.exp(lgamma(a+b)-lgamma(a)-lgamma(b)+a*Math.log(x)+b*Math.log(1-x));
  return x<(a+1)/(a+b+2) ? bt*betacf(a,b,x)/a : 1-bt*betacf(b,a,1-x)/b; }

export function tTest(a,b){ // Welch
  const na=a.length, nb=b.length, ma=mean(a), mb=mean(b), va=sd(a)**2, vb=sd(b)**2;
  const se=Math.sqrt(va/na+vb/nb); const t=(ma-mb)/se;
  const df=(va/na+vb/nb)**2/((va/na)**2/(na-1)+(vb/nb)**2/(nb-1));
  const p=betai(df/2,0.5,df/(df+t*t));
  const sp=Math.sqrt(((na-1)*va+(nb-1)*vb)/(na+nb-2));
  return {t, df, p, diff:ma-mb, d:(ma-mb)/sp};
}
export function anova(groups){ // groups: array of arrays
  const k=groups.length, all=groups.flat(), N=all.length, gm=mean(all);
  let ssb=0, ssw=0;
  for(const g of groups){ const m=mean(g); ssb+=g.length*(m-gm)**2; ssw+=g.reduce((a,b)=>a+(b-m)**2,0); }
  const dfb=k-1, dfw=N-k, F=(ssb/dfb)/(ssw/dfw);
  const p=betai(dfw/2, dfb/2, dfw/(dfw+dfb*F));
  const eta=ssb/(ssb+ssw);
  return {F, dfb, dfw, p, eta2:eta, ssb, ssw};
}

// ---------- linear algebra ----------
export function jacobiEigen(Ain, iters=200){
  const n=Ain.length; const A=Ain.map(r=>[...r]); const V=Array.from({length:n},(_,i)=>Array.from({length:n},(_,j)=>i===j?1:0));
  for(let sweep=0;sweep<iters;sweep++){
    let off=0; for(let i=0;i<n;i++) for(let j=i+1;j<n;j++) off+=A[i][j]**2;
    if(off<1e-22) break;
    for(let p=0;p<n-1;p++) for(let q=p+1;q<n;q++){
      if(Math.abs(A[p][q])<1e-18) continue;
      const theta=(A[q][q]-A[p][p])/(2*A[p][q]);
      const t=Math.sign(theta||1)/(Math.abs(theta)+Math.sqrt(theta*theta+1));
      const c=1/Math.sqrt(t*t+1), s=t*c;
      for(let i=0;i<n;i++){ const aip=A[i][p], aiq=A[i][q]; A[i][p]=c*aip-s*aiq; A[i][q]=s*aip+c*aiq; }
      for(let i=0;i<n;i++){ const api=A[p][i], aqi=A[q][i]; A[p][i]=c*api-s*aqi; A[q][i]=s*api+c*aqi; }
      for(let i=0;i<n;i++){ const vip=V[i][p], viq=V[i][q]; V[i][p]=c*vip-s*viq; V[i][q]=s*vip+c*viq; }
    }
  }
  const vals=Array.from({length:n},(_,i)=>A[i][i]);
  const order=vals.map((v,i)=>i).sort((a,b)=>vals[b]-vals[a]);
  return {values:order.map(i=>vals[i]), vectors:order.map(i=>V.map(r=>r[i]))}; // vectors[j] = j-th PC
}

// baseline-corrected current at a fixed potential, using a linear baseline fitted over [eHigh,eLow]
export function baselineAt(E, I, eTarget, eHigh, eLow){
  const S=movingAvg(I,1);
  const idx=[]; for(let i=0;i<E.length;i++) if(E[i]<=eHigh && E[i]>=eLow) idx.push(i);
  const edge=Math.max(2, Math.round(idx.length*0.12));
  const use=[...idx.slice(0,edge), ...idx.slice(-edge)];
  const xs=use.map(i=>E[i]), ys=use.map(i=>S[i]);
  const n=xs.length, mx=xs.reduce((a,b)=>a+b,0)/n, my=ys.reduce((a,b)=>a+b,0)/n;
  let sxy=0,sxx=0; for(let k=0;k<n;k++){ sxy+=(xs[k]-mx)*(ys[k]-my); sxx+=(xs[k]-mx)**2; }
  const slope=sxx?sxy/sxx:0, intercept=my-slope*mx;
  let it=0, bd=1e9; for(let i=0;i<E.length;i++){ const d=Math.abs(E[i]-eTarget); if(d<bd){bd=d; it=i;} }
  return (slope*E[it]+intercept)-S[it];
}
