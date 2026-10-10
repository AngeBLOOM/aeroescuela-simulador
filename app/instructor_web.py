"""Puesto del instructor por red local (navegador web en otra computadora, tableta o móvil).

El simulador abre un pequeño servidor HTTP en la red local (puerto 8765). El instructor entra en
http://<ip-del-simulador>:8765 e introduce el código de 4 cifras que muestra el simulador.
Desde ahí puede elegir y reiniciar lecciones, pausar, cambiar la meteorología, provocar o programar
fallas, reposicionar el avión y seguir el vuelo en directo (mapa, instrumentos y radio).

Los comandos llegan en un hilo aparte y se encolan; el simulador los ejecuta en su bucle principal,
así nunca se toca el estado del vuelo desde dos hilos a la vez.
"""
import json
import queue
import random
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class InstructorServer:
    def __init__(self, port=8765, code=None):
        self.port = port
        self.code = code or f"{random.randint(0, 9999):04d}"
        self.cmds = queue.Queue()
        self.status = {}
        self.catalog = {}
        self.lock = threading.Lock()
        self.httpd = None
        self.thread = None
        self.error = None
        self.last_seen = 0.0

    @property
    def url(self):
        return f"http://{local_ip()}:{self.port}"

    @property
    def connected(self):
        return time.time() - self.last_seen < 5

    def start(self):
        if self.httpd is not None:
            return
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _auth(self):
                return self.headers.get("X-Codigo", "") == srv.code

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self._send(200, PAGE, "text/html; charset=utf-8")
                elif self.path == "/api/estado":
                    if not self._auth():
                        self._send(403, json.dumps({"error": "codigo"}))
                        return
                    srv.last_seen = time.time()
                    with srv.lock:
                        body = json.dumps({"estado": srv.status, "catalogo": srv.catalog}, ensure_ascii=False)
                    self._send(200, body)
                else:
                    self._send(404, "{}")

            def do_POST(self):
                if not self._auth():
                    self._send(403, json.dumps({"error": "codigo"}))
                    return
                n = int(self.headers.get("Content-Length", "0") or 0)
                try:
                    cmd = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                except Exception:
                    self._send(400, "{}")
                    return
                srv.cmds.put(cmd)
                self._send(200, json.dumps({"ok": True}))
        try:
            self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), H)
        except OSError as ex:
            self.error = f"No se pudo abrir el puerto {self.port}: {ex}"
            self.httpd = None
            return
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def publish(self, status, catalog=None):
        with self.lock:
            self.status = status
            if catalog is not None:
                self.catalog = catalog

    def pending(self):
        out = []
        while True:
            try:
                out.append(self.cmds.get_nowait())
            except queue.Empty:
                return out


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AeroEscuela · Instructor</title>
<style>
:root{--bg:#0b1119;--pn:#131c28;--ln:#26364a;--tx:#e6edf5;--mu:#8ea2b8;--ac:#3a9bff;--ok:#3fd07a;--wa:#ffb020;--er:#ff5a4a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px system-ui,Segoe UI,sans-serif}
header{display:flex;align-items:center;gap:12px;padding:10px 16px;background:#0f1722;border-bottom:1px solid var(--ln);flex-wrap:wrap}
h1{font-size:18px;margin:0}.pill{padding:3px 10px;border-radius:12px;background:var(--pn);color:var(--mu);font-size:13px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;padding:12px}
section{background:var(--pn);border:1px solid var(--ln);border-radius:10px;padding:12px}
h2{font-size:14px;margin:0 0 8px;color:var(--ac);text-transform:uppercase;letter-spacing:.04em}
button,select,input{font:inherit;color:var(--tx);background:#1b2737;border:1px solid var(--ln);border-radius:7px;padding:7px 10px}
button{cursor:pointer}button:hover{border-color:var(--ac)}button.on{background:#7a2018;border-color:var(--er)}
button.pend{background:#5c4410}.row{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px}.k{color:var(--mu);font-size:12px}.v{font:600 20px ui-monospace,Consolas,monospace}
canvas{width:100%;height:260px;background:#08101a;border-radius:8px}
#log div{font-size:13px;padding:2px 0;border-bottom:1px solid #1a2636}
#login{max-width:340px;margin:12vh auto;text-align:center}#login input{font-size:28px;width:160px;text-align:center;letter-spacing:.3em}
.err{color:var(--er)}.ok{color:var(--ok)}.wa{color:var(--wa)}
</style></head><body>
<div id="login"><h1>Puesto del instructor</h1><p class="k">Introduzca el código que muestra el simulador</p>
<input id="code" maxlength="4" inputmode="numeric" autofocus><div class="row" style="justify-content:center"><button onclick="login()">Entrar</button></div><p id="lerr" class="err"></p></div>
<div id="app" style="display:none">
<header><h1>AeroEscuela · Instructor</h1><span class="pill" id="les">—</span><span class="pill" id="st">—</span>
<span style="flex:1"></span><button onclick="cmd({c:'pausa'})">⏯ Pausa</button><button onclick="cmd({c:'reiniciar'})">↺ Reiniciar</button></header>
<main>
<section><h2>Vuelo en directo</h2><div class="grid">
<div><div class="k">Velocidad</div><div class="v" id="ias">—</div></div><div><div class="k">Altitud</div><div class="v" id="alt">—</div></div>
<div><div class="k">Rumbo</div><div class="v" id="hdg">—</div></div><div><div class="k">Vertical</div><div class="v" id="vs">—</div></div>
<div><div class="k">Motor</div><div class="v" id="rpm">—</div></div><div><div class="k">Combustible</div><div class="v" id="fuel">—</div></div></div>
<p id="paso" class="k"></p><canvas id="map" width="600" height="300"></canvas></section>
<section><h2>Lección</h2><select id="lsel" style="width:100%"></select>
<div class="row"><button onclick="cmd({c:'leccion',id:document.getElementById('lsel').value})">▶ Comenzar</button></div>
<h2 style="margin-top:12px">Vuelo libre / reposicionar</h2><div class="row" id="pos"></div>
<h2 style="margin-top:12px">Resultado</h2><div id="res" class="k">—</div></section>
<section><h2>Congelar y mover</h2>
<div class="row"><span class="k">Congelar:</span><button id="fz_alt" onclick="fz('alt')">Altitud</button><button id="fz_pos" onclick="fz('pos')">Posición</button><button id="fz_fuel" onclick="fz('fuel')">Combustible</button></div>
<div class="row"><span class="k">Tiempo:</span><button id="rt_1" onclick="cmd({c:'ritmo',x:1})">×1</button><button id="rt_2" onclick="cmd({c:'ritmo',x:2})">×2</button><button id="rt_4" onclick="cmd({c:'ritmo',x:4})">×4</button></div>
<div class="row"><span class="k">Mover:</span><button onclick="cmd({c:'mover',n:1})">1 NM N</button><button onclick="cmd({c:'mover',n:-1})">1 NM S</button><button onclick="cmd({c:'mover',e:1})">1 NM E</button><button onclick="cmd({c:'mover',e:-1})">1 NM O</button></div>
<div class="row"><button onclick="cmd({c:'mover',alt:500})">+500 ft</button><button onclick="cmd({c:'mover',alt:-500})">−500 ft</button><button onclick="cmd({c:'mover',hdg:-30})">Rumbo −30°</button><button onclick="cmd({c:'mover',hdg:30})">Rumbo +30°</button><button onclick="cmd({c:'mover',hdg:180})">Dar la vuelta</button></div>
<p class="k">El tiempo solo se acelera en vuelo, por encima de 500 ft. Mover solo en vuelo.</p></section>
<section><h2>Fallas</h2><div class="row"><span class="k">Cuándo:</span><select id="when"></select></div>
<div class="row" id="fails"></div><div class="row"><button onclick="cmd({c:'reparar'})">✔ Reparar todo</button></div>
<div id="emerg" class="k"></div></section>
<section><h2>Meteorología</h2><div class="row" id="wx"></div><div class="grid">
<label class="k">Viento (°)<input id="wdir" type="number" step="10"></label><label class="k">Viento (kt)<input id="wkt" type="number"></label>
<label class="k">Ráfagas (kt)<input id="gust" type="number"></label><label class="k">Visibilidad (m)<input id="vis" type="number" step="500"></label>
<label class="k">Base nubes (ft)<input id="base" type="number" step="100"></label><label class="k">Nubosidad (0-1)<input id="cov" type="number" step="0.1" min="0" max="1"></label>
<label class="k">Turbulencia (0-1)<input id="turb" type="number" step="0.1" min="0" max="1"></label><label class="k">Hora local<input id="hour" type="number" step="0.5"></label>
<label class="k">Temp − rocío (°C, 0-3 = muy húmedo)<input id="dew" type="number" step="1" min="0" max="25"></label></div>
<div class="row"><button onclick="sendWx()">Aplicar meteorología</button></div><p id="metar" class="k"></p></section>
<section><h2>Radio (ATC)</h2><div id="log"></div></section>
</main></div>
<script>
let CODE=localStorage.getItem('codigo')||'',cat=null,track=[];
async function api(path,opt={}){opt.headers=Object.assign({'X-Codigo':CODE,'Content-Type':'application/json'},opt.headers||{});
 const r=await fetch(path,opt);if(r.status==403)throw 'codigo';return r.json();}
function login(){CODE=document.getElementById('code').value.trim();localStorage.setItem('codigo',CODE);poll(true);}
function cmd(o){api('/api/cmd',{method:'POST',body:JSON.stringify(o)});}
let FROZEN=[];function fz(k){cmd({c:'congelar',k:k,on:!FROZEN.includes(k)});}
function sendWx(){const g=id=>parseFloat(document.getElementById(id).value);
 cmd({c:'clima',wind_dir:g('wdir'),wind_kt:g('wkt'),gust_kt:g('gust'),visibility_m:g('vis'),cloud_base_ft:g('base'),cloud_cover:g('cov'),turbulence:g('turb'),hour:g('hour'),dew_spread:g('dew')});}
function build(c){cat=c;const s=document.getElementById('lsel');s.innerHTML='';let grp=null,og=null;
 c.lecciones.forEach(l=>{if(l.cat!==grp){grp=l.cat;og=document.createElement('optgroup');og.label=grp;s.appendChild(og);}
  const o=document.createElement('option');o.value=l.id;o.textContent=l.titulo+(l.acs?'  ('+l.acs+')':'');og.appendChild(o);});
 const p=document.getElementById('pos');p.innerHTML='';c.posiciones.forEach(([k,n])=>{const b=document.createElement('button');b.textContent=n;b.onclick=()=>cmd({c:'posicion',id:k});p.appendChild(b);});
 const w=document.getElementById('when');w.innerHTML='';c.disparadores.forEach(([k,n])=>{const o=document.createElement('option');o.value=k;o.textContent=n;w.appendChild(o);});
 const x=document.getElementById('wx');x.innerHTML='';c.presets.forEach(n=>{const b=document.createElement('button');b.textContent=n;b.onclick=()=>cmd({c:'preset',nombre:n});x.appendChild(b);});
 const m=document.createElement('button');m.textContent='☁ METAR real';m.onclick=()=>cmd({c:'metar'});x.appendChild(m);}
let wxFilled=false;
function render(e){document.getElementById('les').textContent=e.leccion||'—';
 const st=document.getElementById('st');st.textContent=e.estado+(e.choque?' · ACCIDENTE':'');st.className='pill '+(e.choque?'err':'');
 const f=(id,v)=>document.getElementById(id).textContent=v;
 f('ias',e.ias.toFixed(0)+' kt');f('alt',e.alt.toFixed(0)+' ft');f('hdg',String(Math.round(e.hdg_mag)%360||360).padStart(3,'0')+'°');
 f('vs',(e.vs>0?'+':'')+e.vs.toFixed(0)+' fpm');f('rpm',e.rpm.toFixed(0)+' rpm');f('fuel',e.fuel.toFixed(0)+' L');
 document.getElementById('paso').textContent=e.paso||'';
 FROZEN=e.congelado||[];['alt','pos','fuel'].forEach(k=>document.getElementById('fz_'+k).className=FROZEN.includes(k)?'on':'');
 [1,2,4].forEach(x=>document.getElementById('rt_'+x).className=(e.ritmo||1)===x?'pend':'');
 const fl=document.getElementById('fails');const sig=e.fallas.map(x=>x.k).join(',');
 if(fl.dataset.sig!==sig){fl.innerHTML='';fl.dataset.sig=sig;e.fallas.forEach(x=>{const b=document.createElement('button');
  b.id='f_'+x.k;b.onclick=()=>cmd({c:'falla',k:x.k,cuando:document.getElementById('when').value});fl.appendChild(b);});}
 e.fallas.forEach(x=>{const b=document.getElementById('f_'+x.k);const t=(x.activa?'⚠ ':x.prog?'⏱ ':'')+x.nombre;
  if(b.textContent!==t)b.textContent=t;b.className=x.activa?'on':(x.prog?'pend':'');});
 document.getElementById('emerg').innerHTML=e.emergencias.map(r=>`<div class="${r[2]?'ok':'wa'}">${r[0]}: ${r[1]}</div>`).join('');
 document.getElementById('log').innerHTML=e.radio.slice().reverse().map(r=>`<div><b>${r[0]}</b> ${r[1]}</div>`).join('');
 document.getElementById('res').innerHTML=e.resultado?`<b class="${e.resultado.apto?'ok':'err'}">${e.resultado.nota.toFixed(0)} · ${e.resultado.calif}</b><br>`+e.resultado.items.map(i=>`${i[0]}: ${i[1]}/${i[2]} — ${i[3]}`).join('<br>'):'—';
 document.getElementById('metar').textContent=e.meteo.texto;
 if(!wxFilled){const m=e.meteo;[['wdir',m.wind_dir],['wkt',m.wind_kt],['gust',m.gust_kt],['vis',m.visibility_m],['base',m.cloud_base_ft],['cov',m.cloud_cover],['turb',m.turbulence],['hour',m.hour],['dew',m.dew_spread]].forEach(([i,v])=>document.getElementById(i).value=Math.round(v*100)/100);wxFilled=true;}
 track.push([e.x,e.y]);if(track.length>900)track.shift();drawMap(e);}
function drawMap(e){const c=document.getElementById('map'),g=c.getContext('2d');const W=c.width,H=c.height;g.clearRect(0,0,W,H);
 const sc=H/(2*12000);const cx=W/2,cy=H/2;const P=(n,ea)=>[cx+(ea-e.y)*sc,cy-(n-e.x)*sc];
 g.strokeStyle='#ddd';g.lineWidth=4;(e.pistas||[]).forEach(r=>{const a=P(r[0],r[1]),b=P(r[2],r[3]);g.beginPath();g.moveTo(...a);g.lineTo(...b);g.stroke();});
 if(e.ruta){g.strokeStyle='#e040e0';g.lineWidth=2;g.beginPath();e.ruta.forEach((p,i)=>{const q=P(p[0],p[1]);i?g.lineTo(...q):g.moveTo(...q);});g.stroke();}
 g.strokeStyle='#3a9bff';g.lineWidth=1.5;g.beginPath();track.forEach((p,i)=>{const q=P(p[0],p[1]);i?g.lineTo(...q):g.moveTo(...q);});g.stroke();
 g.fillStyle='#fff';(e.trafico||[]).forEach(t=>{const q=P(t[0],t[1]);g.fillRect(q[0]-3,q[1]-3,6,6);});
 g.save();g.translate(cx,cy);g.rotate(e.hdg*Math.PI/180);g.fillStyle='#ffd23a';g.beginPath();g.moveTo(0,-10);g.lineTo(7,8);g.lineTo(0,4);g.lineTo(-7,8);g.closePath();g.fill();g.restore();
 g.fillStyle='#8ea2b8';g.font='12px sans-serif';g.fillText('12 km · norte arriba',8,H-8);}
async function poll(first){try{const d=await api('/api/estado');document.getElementById('login').style.display='none';
 document.getElementById('app').style.display='';if(!cat&&d.catalogo.lecciones)build(d.catalogo);if(d.estado.ias!==undefined)render(d.estado);}
 catch(e){if(e==='codigo'){document.getElementById('login').style.display='';document.getElementById('app').style.display='none';
 if(first)document.getElementById('lerr').textContent='Código incorrecto';}}}
setInterval(poll,700);if(CODE)poll(false);
</script></body></html>"""
