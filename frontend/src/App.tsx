import React, { useEffect, useMemo, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8330'
const CHAMP_IMG_BASE = import.meta.env.VITE_CHAMP_IMG_BASE || ''

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!res.ok) throw new Error(await res.text())
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

const CHAMPIONS = [
  "Ashka","Bakko","Blossom","Croak","Destiny","Ezmo","Freya","Iva","Jade","Jamila",
  "Jumong","Lucie","Oldur","Pestilus","Poloma","Raigon","Rook","Ruh Kaan","Shifu","Sirius",
  "Taya","Thorn","Ulric","Varesh","Zander"
]

function slugifyChamp(name:string){
  return name.toLowerCase().replace(/\s+/g,'-').replace(/[^a-z0-9\-]/g,'')
}

function ChampImg({name}:{name:string}){
  const [ok,setOk]=useState(!!CHAMP_IMG_BASE)
  if (!CHAMP_IMG_BASE) return null
  const url = `${CHAMP_IMG_BASE}${slugifyChamp(name)}.png`
  return <img src={url} alt={name} onError={()=>setOk(false)} style={{width:24,height:24,borderRadius:4,objectFit:'cover',display: ok? 'block':'none'}} />
}
function ChampChip({name}:{name:string}){
  const letters = name.split(' ').map(p=>p[0]).join('').slice(0,2).toUpperCase()
  return <span className="svgchip" title={name}>{letters}</span>
}
function ChampCard({name}:{name:string}){
  return <span className="champ-btn"><ChampImg name={name}/><ChampChip name={name}/>{name}</span>
}

function useUsers() {
  const [users, setUsers] = useState<any[]>([])
  useEffect(() => {
    let alive = true
    const tick = async () => { try { const d = await api('/users'); if (alive) setUsers(d) } catch {} }
    tick()
    const id = setInterval(tick, 2000)
    return () => { alive = false; clearInterval(id) }
  }, [])
  const byId = useMemo(() => Object.fromEntries(users.map(u => [u.id, u])), [users])
  return { users, byId }
}

function useMatches() {
  const [matches, setMatches] = useState<any[]>([])
  useEffect(() => {
    let alive = true
    const tick = async () => { try { const d = await api('/matches'); if (alive) setMatches(d) } catch {} }
    tick()
    const id = setInterval(tick, 1500)
    return () => { alive = false; clearInterval(id) }
  }, [])
  return matches
}

function useLeaderboard() {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => {
    let alive = true
    const tick = async () => { try { const d = await api('/leaderboard'); if (alive) setRows(d) } catch {} }
    tick()
    const id = setInterval(tick, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [])
  return rows
}

function countdown(deadlineISO?: string) {
  if (!deadlineISO) return '--:--'
  const diff = Math.max(0, new Date(deadlineISO).getTime() - Date.now())
  const s = Math.ceil(diff/1000)
  const m2 = String(Math.floor(s/60)).padStart(2,'0')
  const s2 = String(s%60).padStart(2,'0')
  return `${m2}:${s2}`
}

function BetCountBadge({id}:{id:string}){
  const [c,setC]=useState<{team1:number,team2:number}|null>(null)
  useEffect(()=>{ let alive=true; const tick=async()=>{ try{ const d=await api(`/bets/count?match_id=${id}`); if(alive) setC(d) }catch{} }; tick(); const it=setInterval(tick, 3000); return ()=>{alive=false; clearInterval(it)} },[id])
  if(!c) return <span className="badge">Apostas: …</span>
  return <span className="badge">T1: {c.team1} | T2: {c.team2}</span>
}

function useSSE(onEvent:(e:any)=>void){
  useEffect(()=>{
    const es = new EventSource(`${API_BASE}/events`)
    es.onmessage = (ev)=>{ try{ const data = JSON.parse(ev.data); onEvent(data) }catch{} }
    es.onerror = ()=>{ /* fallback no polling */ }
    return ()=>{ es.close() }
  }, [onEvent])
}

function QueueBox({me}:{me:any}){
  const [status,setStatus]=useState<{count:number,queued:boolean,match_id?:string}|null>(null)
  async function refresh(){
    try{ const s = await api(`/queue${me?`?user_id=${me.id}`:''}`); setStatus(s) }catch{}
  }
  useEffect(()=>{ let alive=true; const tick=async()=>{ await refresh() }; tick(); const it=setInterval(tick,1500); return ()=>{alive=false; clearInterval(it)} },[me?.id])
  useSSE((e)=>{ if(e?.type==='queue_update'||e?.type==='match_created') refresh() })
  async function enter(){ if(!me) return alert('Faça login'); try{ const s=await api('/queue/enter', {method:'POST', body: JSON.stringify({ user_id: me.id })}); setStatus(s); if(s.match_id) alert('Partida criada: '+s.match_id) }catch(e:any){ alert(e.message||'Falha ao entrar na fila') } }
  async function leave(){ if(!me) return; try{ const s=await api('/queue/leave', {method:'POST', body: JSON.stringify({ user_id: me.id })}); setStatus(s) }catch(e:any){ alert(e.message||'Falha ao sair da fila') } }
  const canEnter = me && status && !status.queued
  const canLeave = me && status && status.queued
  return (
    <div className="card">
      <h3>Fila</h3>
      <div className="row">
        <span className="badge">{status? `${status.count}/6 na fila` : '...'}</span>
        <button className="btn" onClick={enter} disabled={!canEnter}>Entrar na fila</button>
        <button className="btn" onClick={leave} disabled={!canLeave}>Sair da fila</button>
        <span style={{fontSize:12, color:'#6b7280'}}>Nomes ocultos — contador apenas</span>
      </div>
    </div>
  )
}

export default function App() {
  const [nick, setNick] = useState('')
  const [me, setMe] = useState<any>(null)
  const { users, byId } = useUsers()
  const matches = useMatches()
  const leaderboard = useLeaderboard()
  const [nowTick, setNowTick] = useState(Date.now())
  const [profile, setProfile] = useState<any|null>(null)
  const [refreshTick, setRefreshTick] = useState(0)

  useEffect(() => { const id = setInterval(()=>setNowTick(Date.now()),1000); return ()=>clearInterval(id) }, [])
  useSSE((e)=>{ if(['queue_update','match_created','draft_update','bets_update','match_finalized','config_update'].includes(e?.type)){ setRefreshTick(x=>x+1) } })
  useEffect(()=>{ (async()=>{ try{ await api('/matches') }catch{}; try{ await api('/users') }catch{}; try{ await api('/leaderboard') }catch{} })() }, [refreshTick])

  async function upsertMe() {
    const name = nick.trim()
    if (!name) return alert('Informe um nickname')
    const u = await api('/users/upsert', { method:'POST', body: JSON.stringify({ name }) })
    setMe(u)
  }
  async function seedBots() { await api('/seed/test-bots', { method:'POST'}); alert('Bots criados/atualizados') }
  async function createMatchWithBots() {
    if (!me) return alert('Faça login primeiro')
    await seedBots()
    const all = await api('/users')
    const bots = all.filter((u:any)=>/^BOT[1-5]$/.test(u.name)).slice(0,5)
    const ids = [me.id, ...bots.map((b:any)=>b.id)]
    if (ids.length !== 6) return alert('Precisa de 5 bots')
    const m = await api('/match/create', { method:'POST', body: JSON.stringify({ user_ids: ids })})
    alert('Partida criada: ' + m.id)
  }
  async function autoRound(id: string) { await api(`/draft/auto_current?match_id=${id}`, { method:'POST'}) }
  async function autoAll(id: string) { for (let i=0;i<3;i++) await autoRound(id) }
  async function pick(m: any, champ: string) {
    if (!me) return alert('Faça login')
    await api('/draft/pick', { method:'POST', body: JSON.stringify({ match_id: m.id, user_id: me.id, champion_id: champ }) })
  }
  async function bet(m:any, team: 1|2) { if (!me) return alert('Faça login'); await api('/bets/place', { method:'POST', body: JSON.stringify({ match_id: m.id, team, user_id: me.id }) }) }
  async function finalize(id:string, team:1|2) { await api('/match/finalize', { method:'POST', body: JSON.stringify({ match_id: id, winner_team: team }) }) }
  async function openProfile(userId:string) { const p = await api(`/users/${userId}/profile`); setProfile(p) }

  const ongoing = matches.filter((m:any)=>m.status!=='finished')
  const finished = matches.filter((m:any)=>m.status==='finished')

  return (
    <div style={{padding:'16px', margin:'0 auto', maxWidth: '1000px'}}>
      <style>{`
        .card { border:1px solid #e5e7eb; border-radius:12px; padding:12px; margin:8px 0; }
        .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap }
        .grid { display:grid; gap:8px; }
        .btn { padding:8px 12px; border-radius:8px; border:1px solid #e5e7eb; background:#f9fafb; cursor:pointer }
        .btn:disabled { opacity:.6; cursor:not-allowed }
        .badge { display:inline-block; padding:2px 8px; border-radius:9999px; background:#eef2ff; border:1px solid #e5e7eb; font-size:12px }
        input { padding:8px 10px; border:1px solid #e5e7eb; border-radius:8px }
        .link { color:#2563eb; text-decoration:underline; background:none; border:none; padding:0; cursor:pointer }
        .grid6 { grid-template-columns: repeat(6, minmax(0, 1fr)); }
        .champ-btn { display:flex; align-items:center; gap:6px; justify-content:flex-start }
        .svgchip { width:20px; height:20px; border-radius:50%; border:1px solid #e5e7eb; display:inline-flex; align-items:center; justify-content:center; font-size:11px; background:#fff }
      `}</style>

      <div className="card">
        <div className="row">
          <input placeholder="Seu nickname" value={nick} onChange={e=>setNick(e.target.value)} />
          <button className="btn" onClick={upsertMe}>Entrar / garantir usuário</button>
          <span className="badge">Backend: {API_BASE}</span>
          {me && <span className="badge">Você: {me.name}</span>}
        </div>
        <div className="row" style={{marginTop:8}}>
          <button className="btn" onClick={seedBots}>Seed bots</button>
          <button className="btn" onClick={createMatchWithBots} disabled={!me}>Criar partida (você + bots)</button>
        </div>
      </div>

      <QueueBox me={me} />

      <div className="card">
        <h3>Em andamento</h3>
        {ongoing.length===0 && <div>Nenhuma partida em andamento.</div>}
        {ongoing.map((m:any)=>(
          <div key={m.id} className="card">
            <div className="row" style={{justifyContent:'space-between'}}>
              <div><b>Partida {m.id.slice(0,8)}</b> — {m.map} — <span className="badge">{m.status}</span></div>
              {m.status==='draft' && <span className="badge">Rodada {m.draft_round+1}/3</span>}
              {m.status==='in_progress' && m.bet_deadline && <span className="badge">Apostas: {countdown(m.bet_deadline)}</span>}
            </div>
            <div className="row"><b>Time 1:</b> {(m.team1||[]).map((id:string)=>(
              <button key={id} className="link" onClick={()=>openProfile(id)}>{byId[id]?.name||id}</button>
            ))}</div>
            <div className="row"><b>Time 2:</b> {(m.team2||[]).map((id:string)=>(
              <button key={id} className="link" onClick={()=>openProfile(id)}>{byId[id]?.name||id}</button>
            ))}</div>
            <div style={{fontSize:12, color:'#6b7280'}}>Picks: {JSON.stringify(m.picks||{})}</div>
            {m.status==='draft' && (
              <div>
                <div className="row">
                  <button className="btn" onClick={()=>autoRound(m.id)}>Auto-draft (rodada)</button>
                  <button className="btn" onClick={()=>autoAll(m.id)}>Auto-draft (tudo)</button>
                </div>
                <div className="grid grid6" style={{marginTop:8}}>
                  {CHAMPIONS.map(c => (
                    <button key={c} className="btn champ-btn" onClick={()=>pick(m,c)}><ChampCard name={c}/></button>
                  ))}
                </div>
              </div>
            )}
            {m.status==='in_progress' && (
              <div className="row">
                <button className="btn" onClick={()=>bet(m,1)} disabled={!me}>Apostar T1</button>
                <button className="btn" onClick={()=>bet(m,2)} disabled={!me}>Apostar T2</button>
                <BetCountBadge id={m.id} />
              </div>
            )}
            {m.status!=='draft' && (
              <div className="row">
                <button className="btn" onClick={()=>finalize(m.id,1)}>Finalizar: T1 vence</button>
                <button className="btn" onClick={()=>finalize(m.id,2)}>Finalizar: T2 vence</button>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="card">
        <h3>Histórico</h3>
        {finished.length===0 && <div>Sem histórico.</div>}
        {finished.map((m:any)=>(
          <div key={m.id} className="card">
            <div><b>Partida {m.id.slice(0,8)}</b> — {m.map} — finalizada</div>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>Leaderboard</h3>
        {leaderboard.length===0 && <div>Sem dados.</div>}
        {leaderboard.length>0 && (
          <div>
            <div className="row" style={{fontWeight:600}}>
              <div style={{width:40}}>Pos</div><div style={{width:200}}>Jogador</div><div style={{width:80}}>Score</div>
              <div style={{width:40}}>W</div><div style={{width:40}}>L</div><div style={{width:80}}>WinRate</div>
            </div>
            {leaderboard.map((r:any,i:number)=>(
              <div key={r.user_id} className="row">
                <div style={{width:40}}>{i+1}</div>
                <button className="link" style={{width:200, textAlign:'left'}} onClick={()=>openProfile(r.user_id)}>{r.name}</button>
                <div style={{width:80}}>{Number(r.score).toFixed(2)}</div>
                <div style={{width:40}}>{r.wins}</div>
                <div style={{width:40}}>{r.losses}</div>
                <div style={{width:80}}>{(r.played? (r.wins/r.played*100):0).toFixed(1)}%</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <AdminPanel />
      </div>

      {profile && (
        <div className="card">
          <div className="row" style={{justifyContent:'space-between'}}>
            <b>Perfil — {profile.name}</b>
            <button className="btn" onClick={()=>setProfile(null)}>Fechar</button>
          </div>
          <div className="row"><span className="badge">Jogos: {profile.stats.played}</span><span className="badge">W: {profile.stats.wins}</span><span className="badge">L: {profile.stats.losses}</span><span className="badge">WinRate: {profile.stats.played? (profile.stats.wins/profile.stats.played*100).toFixed(1):'0.0'}%</span></div>
          <div className="row"><span className="badge">Streak atual: {profile.stats.current_streak}</span><span className="badge">Max streak: {profile.stats.max_streak}</span><span className="badge">Streaks quebradas: {profile.stats.streaks_broken}</span><span className="badge">Apostas corretas: {profile.stats.correct_bets}</span><span className="badge">Score: {Number(profile.stats.score).toFixed(2)}</span></div>
          <div style={{marginTop:8}}>
            <b>Por campeão</b>
            {(profile.champions||[]).length===0 && <div>Sem jogos por campeão.</div>}
            <div className="grid" style={{gridTemplateColumns:'repeat(4, minmax(0,1fr))'}}>
              {(profile.champions||[]).map((c:any)=>(
                <div key={c.champion} className="card">
                  <div><b>{c.champion}</b></div>
                  <div>Jogos: {c.played}</div>
                  <div>WinRate: {c.played? (c.wins/c.played*100).toFixed(1):'0.0'}%</div>
                  <div>Streaks quebradas: {c.streaks_broken}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function AdminPanel(){
  const [token,setToken]=useState('')
  const [cfg,setCfg]=useState<any|null>(null)
  const [saving,setSaving]=useState(false)

  async function load(){
    try{ const d=await api(`/admin/config${token?`?token=${encodeURIComponent(token)}`:''}`); setCfg(d) }catch(e:any){ alert(e.message||'Falha ao carregar config') }
  }
  async function save(){
    if(!cfg) return
    setSaving(true)
    try{
      const body = JSON.stringify({ points: cfg.points, streak_bonus: cfg.streak_bonus, active_maps: cfg.active_maps, active_champions: cfg.active_champions })
      const d = await api(`/admin/config${token?`?token=${encodeURIComponent(token)}`:''}`, { method:'POST', body })
      setCfg(d)
      alert('Config salva')
    }catch(e:any){ alert(e.message||'Falha ao salvar') } finally { setSaving(false) }
  }
  function toggleList(list:string[], item:string){
    const s = new Set(list); if(s.has(item)) s.delete(item); else s.add(item); return Array.from(s)
  }

  return (
    <div>
      <h3>Admin</h3>
      <div className="row">
        <input placeholder="Admin token (se definido no backend)" value={token} onChange={e=>setToken(e.target.value)} />
        <button className="btn" onClick={load}>Carregar config</button>
      </div>
      {!cfg && <div style={{marginTop:8}}>Carregue a config para editar.</div>}
      {cfg && (
        <div style={{marginTop:8}}>
          <div className="row">
            <div className="card">
              <b>Pontos</b>
              <div className="row"><label>Win</label><input value={cfg.points.win} onChange={e=>setCfg({...cfg, points:{...cfg.points, win: Number(e.target.value)||0}})} /></div>
              <div className="row"><label>Loss</label><input value={cfg.points.loss} onChange={e=>setCfg({...cfg, points:{...cfg.points, loss: Number(e.target.value)||0}})} /></div>
            </div>
            <div className="card">
              <b>Streak bonus</b>
              {Object.entries(cfg.streak_bonus).map(([k,v]:any)=>(
                <div className="row" key={k}><label>{k}</label><input value={v} onChange={e=>setCfg({...cfg, streak_bonus:{...cfg.streak_bonus, [k]: Number(e.target.value)||0}})} /></div>
              ))}
            </div>
          </div>
          <div className="card">
            <b>Mapas ativos</b>
            <div className="grid" style={{gridTemplateColumns:'repeat(4, minmax(0,1fr))'}}>
              {cfg.maps.map((m:string)=>(
                <label key={m} className="row"><input type="checkbox" checked={cfg.active_maps.includes(m)} onChange={()=>setCfg({...cfg, active_maps: toggleList(cfg.active_maps, m)})} /> {m}</label>
              ))}
            </div>
          </div>
          <div className="card">
            <b>Campeões ativos</b>
            <div className="grid" style={{gridTemplateColumns:'repeat(6, minmax(0,1fr))'}}>
              {cfg.champions.map((c:string)=>(
                <label key={c} className="row"><input type="checkbox" checked={cfg.active_champions.includes(c)} onChange={()=>setCfg({...cfg, active_champions: toggleList(cfg.active_champions, c)})} /> {c}</label>
              ))}
            </div>
          </div>
          <div className="row"><button className="btn" disabled={saving} onClick={save}>{saving?'Salvando...':'Salvar'}</button></div>
        </div>
      )}
    </div>
  )
}
