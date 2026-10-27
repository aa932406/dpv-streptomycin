
import fs from "node:fs";
import { Canvas, niceTicks } from "./dpv_plot.mjs";
import * as L from "./dpv_lib.mjs";

const GROUP_DEF = [
  { key:"材料",            label:"MATERIAL ONLY",       color:[31,119,180] },
  { key:"材料10uM.MB",     label:"MATERIAL + 10uM MB",  color:[44,160,44]  },
  { key:"靶标、无酶",       label:"TARGET, NO ENZYME",   color:[214,39,40]  },
  { key:"靶标、酶",         label:"TARGET + ENZYME",     color:[148,103,189]}
];
function groupKey(f){
  const b = f.replace(/\.cor$/i,"").replace(/(_ReStart)+/g,"");
  if (b.startsWith("材料10uM.MB")) return "材料10uM.MB";
  if (b.startsWith("材料")) return "材料";
  if (b.startsWith("靶标、无酶")) return "靶标、无酶";
  if (b.startsWith("靶标、酶")) return "靶标、酶";
  return "?";
}
function electrodeId(f){
  return f.replace(/\.cor$/i,"").replace(/(_ReStart)+/g,"");
}

const files = fs.readdirSync(".").filter(f=>/\.cor$/i.test(f)).sort();
const recs = files.map(f=>L.parseCor(f)).filter(r=>r.type==="ID_DiffPulseVA");
const grid=[]; for(let e=0.8;e>=-0.7801;e-=0.02) grid.push(Math.round(e*1000)/1000);

const data = recs.map(r=>{
  const E=r.rows.map(x=>x[0]), I=r.rows.map(x=>x[1]);
  const Ir=L.resample(E,I,grid);
  const p1=L.peakFeature(grid,Ir,0.60,0.10);
  const p2=L.peakFeature(grid,Ir,-0.10,-0.70);
  return {file:r.file, group:groupKey(r.file), electrode:electrodeId(r.file),
    date:r.date, time:r.time, ocp:r.ocp, Ir,
    Ep1:p1?p1.Ep:NaN, H1:p1&&!p1.noPeak?p1.height*1e6:0, W1:p1?p1.fwhm:NaN, A1:p1?p1.area*1e6:NaN,
    Ep2:p2&&!p2.noPeak?p2.Ep:NaN, H2:p2&&!p2.noPeak?p2.height*1e6:0, W2:p2?p2.fwhm:NaN,
    Q:L.trapz(grid,Ir)*1e6, Iend:Ir[Ir.length-1]*1e6, Istart:Ir[0]*1e6,
    I36:Ir[grid.indexOf(-0.36)]*1e6, I48:Ir[grid.indexOf(-0.48)]*1e6};
});

let long="file,group,electrode,E_V,I_uA\n";
for(const d of data) for(let i=0;i<grid.length;i++)
  long += '"'+d.file+'","'+d.group+'","'+d.electrode+'",'+grid[i]+','+(d.Ir[i]*1e6).toFixed(5)+'\n';
fs.writeFileSync("out_dpv_long.csv","\ufeff"+long);

const cols=["file","group","electrode","date","time","ocp","Ep1","H1","W1","A1","Ep2","H2","W2","Q","Istart","Iend"];
let feat=cols.join(",")+"\n";
for(const d of data){
  feat += cols.map(c=>{ const v=d[c];
    if(typeof v==="number") return isNaN(v)?"":v.toFixed(5);
    return '"'+v+'"'; }).join(",")+"\n";
}
fs.writeFileSync("out_dpv_features.csv","\ufeff"+feat);

const stats={};
for(const g of GROUP_DEF){
  const sub=data.filter(d=>d.group===g.key);
  const h1=sub.map(d=>d.H1), h2=sub.map(d=>d.H2), ep2=sub.map(d=>d.Ep2);
  stats[g.key]={n:sub.length, nElec:new Set(sub.map(d=>d.electrode)).size,
    H1:{mean:L.mean(h1), sd:L.sd(h1)}, H2:{mean:L.mean(h2), sd:L.sd(h2)},
    Ep2:{mean:L.mean(ep2), sd:L.sd(ep2)}};
}
const aov1=L.anova(GROUP_DEF.map(g=>data.filter(d=>d.group===g.key).map(d=>d.H1)));
const aov2=L.anova(GROUP_DEF.map(g=>data.filter(d=>d.group===g.key).map(d=>d.H2)));

const X=data.map(d=>d.Ir.map(v=>v*1e6));
const D=X.length, P=X[0].length;
const mu=Array.from({length:P},(_,j)=>L.mean(X.map(r=>r[j])));
const Xc=X.map(r=>r.map((v,j)=>v-mu[j]));
const cov=Array.from({length:P},()=>new Array(P).fill(0));
for(const r of Xc) for(let i=0;i<P;i++) for(let j=i;j<P;j++) cov[i][j]+=r[i]*r[j];
for(let i=0;i<P;i++) for(let j=i;j<P;j++){ cov[i][j]/=(D-1); cov[j][i]=cov[i][j]; }
const eig=L.jacobiEigen(cov);
const scores=Xc.map(r=>[0,1,2].map(k=>r.reduce((a,v,j)=>a+v*eig.vectors[k][j],0)));
const totalVar=eig.values.reduce((a,b)=>a+b,0);
const expl=eig.values.slice(0,3).map(v=>v/totalVar*100);

function fmt(v){ const a=Math.abs(v);
  if(a===0) return "0";
  if(a<0.01||a>=10000) return v.toExponential(1).replace("e","E");
  return (Math.round(v*100)/100).toString(); }
function axes(c,x,y,w,h,xr,yr,xlab,ylab){
  c.frame(x,y,w,h,[0,0,0]);
  const xt=niceTicks(xr[0],xr[1],5), yt=niceTicks(yr[0],yr[1],5);
  const X=v=>x+(v-xr[0])/(xr[1]-xr[0])*w, Y=v=>y+h-(v-yr[0])/(yr[1]-yr[0])*h;
  for(const t of xt){ c.line(X(t),y+h,X(t),y+h+4,[0,0,0]); c.textCenter(X(t),y+h+8,fmt(t),[0,0,0]); }
  for(const t of yt){ c.line(x,Y(t),x-4,Y(t),[0,0,0]); c.textRight(x-7,Y(t)-3,fmt(t),[0,0,0]); }
  c.textCenter(x+w/2,y+h+28,xlab,[0,0,0]);
  for(let i=0;i<ylab.length;i++) c.text(x-46, y+h/2 - ylab.length*3 + i*7, ylab[i], [0,0,0]);
  return {X,Y};
}

{
  const c=new Canvas(900,660);
  c.textCenter(450,12,"DPV RAW SCANS BY CONDITION",[0,0,0],2);
  const xr=[-0.80,0.80], yr=[-12,0];
  GROUP_DEF.forEach((g,gi)=>{
    const px=60+(gi%2)*430, py=44+Math.floor(gi/2)*300, w=340,h=210;
    const ax=axes(c,px,py,w,h,xr,yr,"E (V vs REF)","I (uA)");
    for(const d of data.filter(x=>x.group===g.key)){
      let prev=null;
      for(let i=0;i<grid.length;i++){ const X=ax.X(grid[i]),Y=ax.Y(d.Ir[i]*1e6);
        if(prev) c.line(prev[0],prev[1],X,Y,g.color,1); prev=[X,Y]; }
    }
    c.rect(px+w-124,py+5,118,13,[255,255,255]);
    c.text(px+w-120,py+8,g.label.slice(0,18),[0,0,0]);
  });
  c.save("fig1_raw_curves.png");
}
{
  const c=new Canvas(820,520);
  c.textCenter(410,14,"MEAN DPV +/- 1 SD PER CONDITION",[0,0,0],2);
  const ax=axes(c,70,44,700,400,[-0.80,0.80],[-12,0],"E (V vs REF)","I (uA)");
  GROUP_DEF.forEach((g)=>{
    const sub=data.filter(d=>d.group===g.key);
    const ms=grid.map((e,i)=>{ const v=sub.map(d=>d.Ir[i]*1e6); return [L.mean(v), L.sd(v)]; });
    for(let i=0;i<grid.length;i++){
      const x=ax.X(grid[i]);
      c.line(x,ax.Y(ms[i][0]-ms[i][1]),x,ax.Y(ms[i][0]+ms[i][1]),
        g.color.map(v=>Math.round(v+(255-v)*0.68)),1);
    }
    let prev=null;
    for(let i=0;i<grid.length;i++){ const X=ax.X(grid[i]), Y=ax.Y(ms[i][0]);
      if(prev) c.line(prev[0],prev[1],X,Y,g.color,2); prev=[X,Y]; }
  });
  GROUP_DEF.forEach((g,gi)=>{ const ly=52+gi*14;
    c.line(560,ly+3,580,ly+3,g.color,2); c.text(586,ly,g.label,[0,0,0]); });
  c.save("fig2_mean_band.png");
}
{
  const c=new Canvas(760,560);
  c.textCenter(380,14,"CATHODIC (H2) vs ANODIC (H1) PEAK HEIGHT",[0,0,0],2);
  const ax=axes(c,74,44,640,440,[0,6],[-1,6],"H1 ANODIC PEAK HEIGHT (uA)","H2 CATHODIC PEAK HEIGHT (uA)");
  for(const g of GROUP_DEF){ for(const d of data.filter(x=>x.group===g.key)){
    c.fillCircle(ax.X(d.H1),ax.Y(d.H2),5,g.color);
    c.circle(ax.X(d.H1),ax.Y(d.H2),6,[0,0,0]); } }
  GROUP_DEF.forEach((g,gi)=>{ const ly=52+gi*14;
    c.fillCircle(596,ly+3,5,g.color); c.text(608,ly,g.label,[0,0,0]); });
  c.save("fig3_peak_scatter.png");
}
{
  const c=new Canvas(760,560);
  c.textCenter(380,14,"PCA OF DPV CURVES",[0,0,0],2);
  const xs=scores.map(s=>s[0]), ys=scores.map(s=>s[1]);
  const xr=[Math.min(...xs)*1.15,Math.max(...xs)*1.15], yr=[Math.min(...ys)*1.15,Math.max(...ys)*1.15];
  const ax=axes(c,74,44,640,440,xr,yr,
    "PC1 ("+expl[0].toFixed(0)+"%)","PC2 ("+expl[1].toFixed(0)+"%)");
  data.forEach((d,i)=>{ const g=GROUP_DEF.find(x=>x.key===d.group);
    c.fillCircle(ax.X(scores[i][0]),ax.Y(scores[i][1]),5,g.color);
    c.circle(ax.X(scores[i][0]),ax.Y(scores[i][1]),6,[0,0,0]); });
  GROUP_DEF.forEach((g,gi)=>{ const ly=52+gi*14;
    c.fillCircle(596,ly+3,5,g.color); c.text(608,ly,g.label,[0,0,0]); });
  c.save("fig4_pca.png");
}

const report={n:data.length, expl, aov1, aov2, stats,
  pairwise: GROUP_DEF.flatMap((a,i)=>GROUP_DEF.slice(i+1).map(b=>({a:a.key,b:b.key,
    H1:L.tTest(data.filter(d=>d.group===a.key).map(d=>d.H1), data.filter(d=>d.group===b.key).map(d=>d.H1)),
    H2:L.tTest(data.filter(d=>d.group===a.key).map(d=>d.H2), data.filter(d=>d.group===b.key).map(d=>d.H2))}))),
  rows:data.map(d=>({file:d.file,group:d.group,electrode:d.electrode,Ep1:+d.Ep1.toFixed(2),H1:+d.H1.toFixed(3),
    Ep2:+d.Ep2.toFixed(2),H2:+d.H2.toFixed(3),W1:+d.W1.toFixed(3),Q:+d.Q.toFixed(2),ocp:+d.ocp.toFixed(3)}))};
fs.writeFileSync("out_report.json", JSON.stringify(report,null,1));
console.log(JSON.stringify({expl, aov1, aov2, stats}, null, 1));
