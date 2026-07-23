# KlineWidget - pure QPainter K-line chart
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont

_BG=QColor('#0D1117'); _PANEL=QColor('#161B22'); _BORDER=QColor('#21262D')
_TEXT=QColor('#E6EDF3'); _TEXTS=QColor('#8B949E'); _ACCENT=QColor('#D4A574')
_UP=QColor('#EF5350'); _DOWN=QColor('#4CAF50'); _GRID=QColor('#1A1F28')
_MA5=QColor('#F0A56A'); _MA10=QColor('#5DADE2'); _MA20=QColor('#AF7AC5')
_MA60=QColor('#F7DC6F'); _MVOL=QColor('#6C757D')

class KlineWidget(QWidget):
    def __init__(s):
        super().__init__(); s.setMouseTracking(True)
        s.setFocusPolicy(Qt.StrongFocus)
        s._bars=[]; s._symbol=''; s._name=''; s._ind='macd'
        s._vs=0; s._ve=0; s._pan=None; s._ch=-1
        s._L=dict(ml=75,mr=10,mt=35,mb=25)

    def set_data(s, data, symbol, name):
        if data is None or data.get('code')!=0: return
        bars=data.get('data',[]); ref=float(bars[0].get('close',0)) if bars else 0
        if ref>0 and len(bars)>5:
            bars=[b for b in bars if abs(float(b.get('close',ref))/ref-1)<0.5]
        if not bars: return
        s._bars=bars; s._symbol=symbol; s._name=name
        n=len(bars); s._vs=max(0,n-60); s._ve=n; s._ch=-1; s.update()

    def switch_indicator(s, t): s._ind=t; s.update()

    def paintEvent(s,ev):
        p=None
        try:
            p=QPainter(s); p.setRenderHint(QPainter.Antialiasing,True)
            W,H=s.width(),s.height(); L=s._L; ml,mr,mt,mb=L['ml'],L['mr'],L['mt'],L['mb']
            cw=W-ml-mr; ah=H-mt-mb; ph0=int(ah*0.6); ph1=int(ah*0.2); ph2=ah-ph0-ph1
            py0,py1,py2=mt,mt+ph0,mt+ph0+ph1
            p.fillRect(s.rect(),_BG)
            bars,n=s._bars,len(s._bars)
            if n==0: p.setPen(_TEXTS); p.drawText(s.rect(),Qt.AlignCenter,'choose stock'); p.end(); p=None; return
            vs,ve=s._vs,min(s._ve,n); vis=ve-vs
            if vis<=0: p.end(); p=None; return
            bw=cw/vis
            s._draw_price(p,ml,py0,ph0,cw,bw,vs,ve)
            s._draw_vol(p,ml,py1,ph1,cw,bw,vs,ve)
            s._draw_ind(p,ml,py2,ph2,cw,bw,vs,ve)
            s._draw_dates(p,ml,W-mr,H-mb,mb,bw,vs,ve)
            s._draw_title(p,W,mt)
            if s._ch>=0: s._draw_cross(p,W,H,ml,cw,bw,vs,ve,[py0,py1,py2],[ph0,ph1,ph2])
        except Exception as exc:
            import sys, traceback
            print(f'[KW] PAINT ERROR at {s._ind}/{s._ch}:', file=sys.stderr)
            traceback.print_exc()
        finally:
            if p is not None: p.end()

    def _vy(s,v,lo,hi,y,h):
        if hi==lo: return y+h//2
        return y+h-int((v-lo)/(hi-lo)*h)

    def _draw_price(s,p,ml,y,h,cw,bw,vs,ve):
        bars=s._bars[vs:ve]; p.fillRect(ml,y,cw,h,_PANEL)
        lo=min((float(b['low']) for b in bars if b.get('low')),default=0)
        hi=max((float(b['high']) for b in bars if b.get('high')),default=1)
        m=max((hi-lo)*0.06,0.05); lo-=m; hi+=m
        p.setPen(QPen(_GRID,1))
        for gy in range(y+20,y+h,20): p.drawLine(ml,gy,ml+cw,gy)
        for i,b in enumerate(bars):
            o,hh,ll,c=(float(b.get(k,0)) for k in ('open','high','low','close'))
            if o<=0 or c<=0: continue
            x=ml+i*bw+bw/2; up=c>=o; col=_UP if up else _DOWN
            p.setPen(QPen(_TEXTS,1))
            p.drawLine(QPointF(x,s._vy(hh,lo,hi,y,h)),QPointF(x,s._vy(ll,lo,hi,y,h)))
            hf=max(bw*0.35,1.5); tp=s._vy(max(c,o),lo,hi,y,h); bt=s._vy(min(c,o),lo,hi,y,h)
            p.setBrush(col); p.setPen(QPen(col.darker(120),0))
            p.drawRect(QRectF(x-hf,tp,hf*2,max(bt-tp,1.5)))
        for per,col in [(5,_MA5),(10,_MA10),(20,_MA20),(60,_MA60)]:
            pts=[]
            for i,b in enumerate(bars):
                v=b.get(f'ma{per}')
                if v is not None and v>0: pts.append(QPointF(ml+i*bw+bw/2,s._vy(float(v),lo,hi,y,h)))
            if len(pts)>1:
                p.setPen(QPen(col,1.2))
                for j in range(1,len(pts)): p.drawLine(pts[j-1],pts[j])
        s._draw_yaxis(p,ml,y,h,lo,hi,'p')

    def _draw_vol(s,p,ml,y,h,cw,bw,vs,ve):
        bars=s._bars[vs:ve]; p.fillRect(ml,y,cw,h,_PANEL)
        hi=max((float(b.get('volume',0)) for b in bars),default=1)
        p.setPen(QPen(_GRID,1))
        for gy in range(y+20,y+h,20): p.drawLine(ml,gy,ml+cw,gy)
        for i,b in enumerate(bars):
            v=float(b.get('volume',0))
            if v<=0: continue
            col=_UP if float(b['close'])>=float(b['open']) else _DOWN
            hf=max(bw*0.35,1.5); tp=s._vy(v,0,hi,y,h)
            p.setBrush(col); p.setPen(QPen(col.darker(120),0))
            p.drawRect(QRectF(ml+i*bw+bw/2-hf,tp,hf*2,s._vy(0,0,hi,y,h)-tp))
        if len(bars)>=5:
            p.setPen(QPen(_MVOL,1)); lp=None
            for i in range(4,len(bars)):
                v5=sum(float(bars[i-j].get('volume',0)) for j in range(5))/5
                pt=QPointF(ml+i*bw+bw/2,s._vy(v5,0,hi,y,h))
                if lp is None:
                    pass
                else:
                    p.drawLine(lp, pt)
                lp = pt
        s._draw_yaxis(p,ml,y,h,0,hi,'v')

    def _draw_ind(s,p,ml,y,h,cw,bw,vs,ve):
        bars=s._bars[vs:ve]; p.fillRect(ml,y,cw,h,_PANEL)
        p.setPen(QPen(_GRID,1))
        for gy in range(y+20,y+h,20): p.drawLine(ml,gy,ml+cw,gy)
        if s._ind=='macd':
            vals=[abs(float(b[k])) for b in bars for k in ('macd','dif','dea') if b.get(k)is not None]
            hi=max(vals)if vals else 1; lo=-hi
            zy=s._vy(0,lo,hi,y,h); p.setPen(QPen(_BORDER,1)); p.drawLine(ml,zy,ml+cw,zy)
            for i,b in enumerate(bars):
                mv=float(b.get('macd') or 0)
                y0=s._vy(0,lo,hi,y,h); y1=s._vy(mv,lo,hi,y,h)
                if y0!=y1:
                    col=_UP if mv>=0 else _DOWN
                    p.setBrush(col); p.setPen(QPen(col,0)); hf=max(bw*0.3,1)
                    p.drawRect(QRectF(ml+i*bw+bw/2-hf,min(y0,y1),hf*2,abs(y1-y0)))
            s._draw_line(p,bars,'dif',_MA5,bw,ml,lo,hi,y,h)
            s._draw_line(p,bars,'dea',_MA10,bw,ml,lo,hi,y,h)
            s._draw_yaxis(p,ml,y,h,lo,hi,'ind')
        else:
            for th,c in [(70,_UP),(50,_BORDER),(30,_DOWN)]:
                ty=s._vy(th,0,100,y,h); p.setPen(QPen(c,1,Qt.DashLine))
                p.drawLine(ml,ty,ml+cw,ty)
            s._draw_line(p,bars,'rsi14',_MA20,bw,ml,lo:=0,hi:=100,y,h)
            s._draw_yaxis(p,ml,y,h,0,100,'ind')

    def _draw_line(s,p,bars,key,col,bw,ml,lo,hi,y,h):
        p.setPen(QPen(col,1.2)); lp=None
        for i,b in enumerate(bars):
            v=b.get(key)
            if v is not None:
                pt=QPointF(ml+i*bw+bw/2,s._vy(float(v),lo,hi,y,h))
                if lp: p.drawLine(lp,pt); lp=pt

    def _draw_yaxis(s,p,ml,y,h,lo,hi,mode):
        f=p.font(); f.setPointSize(9); p.setFont(f)
        for i in range(5):
            val=lo+(hi-lo)*i/4; py=s._vy(val,lo,hi,y,h)
            p.setPen(QPen(_GRID,1)); p.drawLine(ml-3,py,ml,py)
            if mode=='p': txt=f'{val:.2f}'
            elif mode=='v':
                if val>=1e8: txt=f'{val/1e8:.2f}亿'
                elif val>=1e4: txt=f'{val/1e4:.1f}万'
                else: txt=f'{int(val)}'
            else: txt=f'{val:.2f}'if abs(val)<100 else f'{val:.0f}'
            p.setPen(_TEXTS)
            p.drawText(QRectF(0,py-8,ml-6,16),Qt.AlignRight|Qt.AlignVCenter,txt)

    def _draw_dates(s,p,ml,mr,y,h,bw,vs,ve):
        vis=ve-vs; step=max(1,vis//10)
        f=p.font(); f.setPointSize(9); p.setFont(f)
        for i,idx in enumerate(range(vs,ve)):
            if i%step!=0 and i!=vis-1: continue
            x=ml+i*bw+bw/2; d=s._bars[idx]['date']
            label=d[4:6]+'/'+d[6:8]
            p.setPen(QPen(_GRID,1)); p.drawLine(QPointF(x,y),QPointF(x,y+4))
            p.setPen(_TEXTS)
            p.drawText(QRectF(x-20,y+4,40,16),Qt.AlignCenter,label)

    def _draw_title(s,p,W,H):
        p.fillRect(0,0,W,H,_PANEL)
        if not s._bars:
            p.setPen(_TEXTS); p.drawText(QRectF(0,0,W,H),Qt.AlignCenter,'Choose a stock to view chart')
            return
        b0=s._bars[0]; c=float(b0['close']); ch=c-float(b0['open'])
        pct=ch/max(float(b0['open']),0.01)*100; up=ch>=0
        f=p.font(); f.setBold(True); f.setPointSize(12); p.setFont(f)
        p.setPen(_ACCENT)
        p.drawText(QRectF(10,0,200,H),Qt.AlignVCenter,f'{s._symbol}')
        f.setBold(False); f.setPointSize(11); p.setFont(f)
        p.setPen(_TEXT)
        p.drawText(QRectF(80,0,160,H),Qt.AlignVCenter,f'{s._name}')
        p.setPen(_BORDER)
        p.drawText(QRectF(230,0,30,H),Qt.AlignVCenter,'|')
        p.setPen(_TEXTS)
        p.drawText(QRectF(250,0,100,H),Qt.AlignVCenter,f'{len(s._bars)} 日')
        p.setPen(_UP if up else _DOWN)
        ar='\u25b2' if up else '\u25bc'
        f.setBold(True); p.setFont(f)
        p.drawText(QRectF(340,0,300,H),Qt.AlignVCenter,f'{c:.2f}  {ch:+.2f} ({pct:+.2f}%)')

    def _draw_cross(s,p,W,H,ml,cw,bw,vs,ve,py,ph):
        b=s._bars[s._ch]
        x=ml+(s._ch-vs)*bw+bw/2; cv=float(b["close"]); ov=float(b["open"])
        chg=cv-ov; pct=chg/max(ov,0.01)*100; up=cv>=ov
        col=_UP if up else _DOWN
        vis=s._bars[vs:ve]; nv=len(vis)
        # Vertical line across all panels
        p.setPen(QPen(_ACCENT,1,Qt.DashLine))
        p.drawLine(QPointF(x,py[0]),QPointF(x,py[2]+ph[2]))
        # --- Main chart: horizontal at close price ---
        lo=min((float(b2["low"])for b2 in vis if b2.get("low")),default=0)
        hi=max((float(b2["high"])for b2 in vis if b2.get("high")),default=1)
        mg=max((hi-lo)*0.06,0.05)
        cy=s._vy(cv,lo-mg,hi+mg,py[0],ph[0])
        p.setPen(QPen(_ACCENT,1,Qt.DashLine))
        p.drawLine(QPointF(ml,cy),QPointF(ml+nv*bw,cy))
        # Price label at right Y axis
        p.setPen(col); p.setFont(QFont("",8))
        p.drawText(QRectF(ml+cw-80,cy-8,78,16),Qt.AlignRight|Qt.AlignVCenter,f"{cv:.2f}")
        # --- Volume panel: horizontal at bar volume ---
        vv=float(b.get("volume",0))
        if vv>0:
            vhi=max((float(b2.get("volume",0))for b2 in vis),default=1)
            vy_=s._vy(vv,0,vhi*1.15,py[1],ph[1])
            p.setPen(QPen(_TEXTS,1,Qt.DashLine))
            p.drawLine(QPointF(ml,vy_),QPointF(ml+nv*bw,vy_))
            vol_txt=f"{vv/1e8:.1f}亿"if vv>=1e8 else f"{vv/1e4:.0f}万"if vv>=1e4 else f"{vv:.0f}"
            p.setPen(_TEXTS)
            p.drawText(QRectF(ml+cw-80,vy_-8,78,16),Qt.AlignRight|Qt.AlignVCenter,vol_txt)
        # --- Indicator panel: horizontal at bar value ---
        if s._ind=="macd":
            vals=[abs(float(b2.get(k,0)))for b2 in vis for k in ("macd","dif","dea")if b2.get(k)is not None]
            ihi=max(vals)if vals else 1; ilo=-ihi
            iv=float(b.get("macd") or 0); iy=s._vy(iv,ilo,ihi,py[2],ph[2])
            p.setPen(QPen(_MA10,1,Qt.DashLine))
            p.drawLine(QPointF(ml,iy),QPointF(ml+nv*bw,iy))
            p.setPen(_MA10)
            p.drawText(QRectF(ml+cw-80,iy-8,78,16),Qt.AlignRight|Qt.AlignVCenter,f"{iv:.4f}")
        else:
            iv=float(b.get("rsi14") or 50); iy=s._vy(iv,0,100,py[2],ph[2])
            p.setPen(QPen(_MA10,1,Qt.DashLine))
            p.drawLine(QPointF(ml,iy),QPointF(ml+nv*bw,iy))
            p.setPen(_MA10)
            p.drawText(QRectF(ml+cw-80,iy-8,78,16),Qt.AlignRight|Qt.AlignVCenter,f"{iv:.1f}")
        # --- Info card ---
        f=p.font(); f.setPointSize(10); p.setFont(f)
        vol_fmt=f"{vv/1e8:.1f}亿"if vv>=1e8 else f"{vv/1e4:.0f}万"if vv>=1e4 else f"{vv:.0f}"
        ind_fmt=f"{float(b.get("macd") or 0):.4f}"if s._ind=="macd"else f"{float(b.get("rsi14") or 50):.1f}"
        info=(f"  {b["date"]}  {f"▲{pct:+.2f}%"if up else f"▼{pct:+.2f}%"}\n"
              f"  O:{ov:.2f}  H:{float(b["high"]):.2f}  L:{float(b["low"]):.2f}\n"
              f"  C:{cv:.2f}  V:{vol_fmt}  {s._ind.upper()}:{ind_fmt}")
        cr=QRectF(x+8,cy-55,200,72)
        if cr.right()>W: cr.moveRight(x-8)
        if cr.top()<py[0]: cr.moveTop(cy+8)
        p.setBrush(QColor(22,27,34,240)); p.setPen(QPen(_ACCENT,1))
        p.drawRoundedRect(cr,6,6); p.setPen(_TEXT)
        p.drawText(cr.adjusted(6,4,-6,-4),Qt.AlignLeft|Qt.AlignTop,info)

    def mouseMoveEvent(s,e):
        if not s._bars:
            if s._ch>=0: s._ch=-1; s.update()
            return
        L=s._L; ml, cw=L['ml'], s.width()-L['ml']-L['mr']
        ah=s.height()-L['mt']-L['mb']; mx,my=e.x(),e.y(); n=len(s._bars)
        vis=min(s._ve,n)-s._vs
        if mx<ml or mx>ml+cw or my<L['mt'] or my>L['mt']+ah:
            if s._ch>=0: s._ch=-1; s.update()
            return
        if e.buttons()&Qt.LeftButton and s._pan is not None:
            ax,avs=s._pan; bd=int((mx-ax)/(cw/max(vis,1)))
            ns=max(0,min(n-vis,avs-bd))
            if ns!=s._vs:
                s._vs=ns; s._ve=min(ns+vis,n); s._pan=(mx,s._vs); s._ch=-1; s.update()
            return
        if vis<=0: return
        idx=s._vs+int((mx-ml)/(cw/vis))
        if idx<0 or idx>=n:
            if s._ch>=0: s._ch=-1; s.update()
            return
        if idx!=s._ch: s._ch=idx; s.update()

    def mousePressEvent(s,e):
        if e.button()==Qt.LeftButton and s._bars: s._pan=(e.x(),s._vs)

    def mouseReleaseEvent(s,e):
        if e.button()==Qt.LeftButton: s._pan=None

    def wheelEvent(s,e):
        if not s._bars: return
        n=len(s._bars); vis=min(s._ve,n)-s._vs
        if vis<=0: return
        L=s._L; cw=s.width()-L['ml']-L['mr']
        if cw<=0: return
        ci=s._vs+int((e.x()-L['ml'])/(cw/vis)); ci=max(0,min(n-1,ci))
        fac=3/4 if e.angleDelta().y()>0 else 4/3
        nv=max(10,min(n,int(vis*fac))); ni=int(ci-(ci-s._vs)*(nv/vis))
        s._vs=max(0,min(n-nv,ni)); s._ve=min(s._vs+nv,n); s._ch=-1; s.update()

    def leaveEvent(s,e):
        if s._ch>=0: s._ch=-1; s.update()

    def resizeEvent(s,e): s.update()