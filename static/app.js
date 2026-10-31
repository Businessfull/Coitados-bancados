const $=id=>document.getElementById(id);
let data={summary:{},players:[],deaths:[],collector:{}};
const n=v=>Number(v||0).toLocaleString('pt-BR');
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(){
 const s=data.summary||{}, c=data.collector||{};
 $('totalXp').textContent=n(s.total_xp); $('recentXp').textContent=n(s.recent_xp);
 $('players').textContent=n(s.player_count??data.players.length); $('deaths').textContent=n(s.death_count??data.deaths.length);
 let q=$('search').value.toLowerCase(),sort=$('sort').value;
 let ps=data.players.filter(p=>(p.name||'').toLowerCase().includes(q));
 ps.sort((a,b)=>sort==='name'?(a.name||'').localeCompare(b.name||''):sort==='recent'?(b.recent_xp||0)-(a.recent_xp||0):(b.daily_xp||0)-(a.daily_xp||0));
 $('playerRows').innerHTML=ps.length?ps.map(p=>`<tr><td><b>${esc(p.name)}</b></td><td>${n(p.level)}</td><td class="xp">${n(p.daily_xp)}</td><td>${n(p.total_xp)}</td><td class="recent">${n(p.recent_xp)}</td><td>${esc(p.updated_at)}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">Nenhum personagem encontrado.</td></tr>';
 $('deathRows').innerHTML=data.deaths.length?data.deaths.slice(0,40).map(d=>`<tr><td>${esc(d.time)}</td><td><b>${esc(d.character)}</b></td><td>${n(d.level)}</td><td>${esc(d.involved||d.cause)}</td></tr>`).join(''):'<tr><td colspan="4" class="empty">Nenhuma morte registrada pela fonte disponível.</td></tr>';
 $('updated').textContent=c.mode==='screenshot_baseline'?'Base inicial transcrita dos prints • sem atualização automática':(c.last_success?'Última coleta concluída: '+new Date(c.last_success).toLocaleString('pt-BR'):'Aguardando a primeira coleta concluída');
 const notice=$('collectorNotice');
 if(c.last_error){notice.hidden=false;$('collectorError').textContent=c.last_error;$('collectorState').textContent='A coleta automática encontrou um erro';}
 else if(!data.players.length){notice.hidden=false;$('collectorError').textContent='A API está respondendo, mas ainda não há personagens gravados. Aguarde a primeira coleta ou confira os logs do serviço no Render.';$('collectorState').textContent='Sem dados coletados';}
 else{notice.hidden=true;}
}
async function load(){
 try{
  const r=await fetch('/api/dashboard',{cache:'no-store'}); if(!r.ok)throw Error('HTTP '+r.status);
  data=await r.json(); render(); const c=data.collector||{};
  $('connection').textContent=c.last_error?'● Coletor com erro':(c.mode==='screenshot_baseline'?'● Base importada dos prints':'● Monitor ativo');
 }catch(e){$('connection').textContent='● API indisponível';$('updated').textContent='Falha ao consultar a API: '+e.message;}
}
$('search').addEventListener('input',render); $('sort').addEventListener('change',render);
load();setInterval(load,60000);
