import React, { useEffect, useMemo, useState, useCallback } from 'react'

/**
 * Inhouse BR v5.0 — Frontend
 * - Tabs (Home, Histórico, Leaderboard, Admin)
 * - Draft layout inspired by brdraft: Team1 | Champions Grid | Team2
 * - Champion images via VITE_CHAMP_IMG_BASE (host your own assets)
 * - Queue: names shown; during draft, reveal-by-turn (1º de cada time revelado, demais ao chegar a vez; seu time é sempre visível para você)
 * - History tab: rich details (id, mapa, players, picks, bets count, winner, streak flags if provided by backend)
 * - Bets timer label “MM:SS restantes”
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8330'
const CHAMP_IMG_BASE = import.meta.env.VITE_CHAMP_IMG_BASE || ''

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!res.ok) throw new Error(await res.text())
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

const CHAMPIONS = [
  'Ashka','Bakko','Blossom','Croak','Destiny','Ezmo','Freya','Iva','Jade','Jamila',
  'Jumong','Lucie','Oldur','Pestilus','Poloma','Raigon','Rook','Ruh Kaan','Shifu','Sirius',
  'Taya','Thorn','Ulric','Varesh','Zander'
]

const MAPS = [
  'Mount Araz Day','Mount Araz Night','Orman Night',
  'Blackstone Day','Blackstone Night','Dragon Garden Day','Dragon Garden Night','Meriko Night'
]

function slugifyChamp(name:string){
  return name.toLowerCase().replace(/\s+/g,'-').replace(/[^a-z0-9\-]/g,'')
}

function ChampImg({name, size=40}:{name:string, size?:number}){
  const [ok,setOk]=useState(!!CHAMP_IMG_BASE)
  if (!CHAMP_IMG_BASE) return <span className="chip-fallback">{name.slice(0,2).toUpperCase()}</span>
  const url = `${CHAMP_IMG_BASE}${slugifyChamp(name)}.png`
  return <img src={url} alt={name} title={name} width={size} height={size}
              onError={()=>setOk(false)} style={{display: ok? 'inline-block':'none', objectFit:'cover', borderRadius:6}}/>
}

function useSSE(onEvent:(e:any)=>void){
  useEffect(()=>{
    const es = new EventSource(`${API_BASE}/events`)
    es.onmessage = (ev)=>{ try{ const data = JSON.parse(ev.data); onEvent(data) }catch{} }
    return ()=>{ es.close() }
  }, [onEvent])
}

function useUsers() {
  const [users, setUsers] = useState<any[]>([])
  const refresh = useCallback(async()=>{ try{ const d = await api('/users'); setUsers(d) }catch{} }, [])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 2500); return ()=>clearInterval(id) },[refresh])
  const byId = useMemo(()=>Object.fromEntries(users.map(u=>[u.id,u])),[users])
  return { users, byId, refresh }
}

function useMatches() {
  const [matches, setMatches] = useState<any[]>([])
  const refresh = useCallback(async()=>{ try{ const d = await api('/matches'); setMatches(d) }catch{} }, [])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 2000); return ()=>clearInterval(id) },[refresh])
  return { matches, refresh }
}

function useLeaderboard(){
  const [rows,setRows]=useState<any[]>([])
  const refresh = useCallback(async()=>{ try{ const d = await api('/leaderboard'); setRows(d) }catch{} }, [])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 4000); return ()=>clearInterval(id) },[refresh])
  return { rows, refresh }
}

function fmtTimer(deadlineISO?: string){
  if (!deadlineISO) return '—'
  const diff = Math.max(0, new Date(deadlineISO).getTime() - Date.now())
  const s = Math.ceil(diff/1000)
  const mm = String(Math.floor(s/60)).padStart(2,'0')
  const ss = String(s%60).padStart(2,'0')
  return `${mm}:${ss} restantes`
}

function TabBar({tab,setTab}:{tab:string,setTab:(t:string)=>void}){
  const tabs = [
    {id:'home', label:'Início'},
    {id:'history', label:'Histórico'},
    {id:'leaderboard', label:'Leaderboard'},
    {id:'admin', label:'Admin'}
  ]
  return (
    <div className="tabs">
      {tabs.map(t=> (
        <button key={t.id} className={`tab ${tab===t.id?'active':''}`} onClick={()=>setTab(t.id)}>{t.label}</button>
      ))}
    </div>
  )
}

function TeamList({title, users, picks, revealAll}:{title:string, users:string[], picks:Record<string,string|undefined>, revealAll:boolean}){
  return (
    <div className="team-col">
      <h3>{title}</h3>
      <div className="team-picks">
        {users.map(uid=>{
          const champ = picks[uid]
          return (
            <div key={uid} className="pick-card">
              <div className="pick-top">
                {champ ? <ChampImg name={champ} size={48}/> : <div className="placeholder"/>}
                <div className="champ-name">{champ || '—'}</div>
              </div>
              <div className="user-name">{revealAll ? (uid) : 'Jogador oculto'}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function App(){
  const [tab, setTab] = useState<'home'|'history'|'leaderboard'|'admin'>('home')
  const [nick,setNick]=useState('')
  const [me,setMe]=useState<any>(null)
  const { users, byId, refresh: refreshUsers } = useUsers()
  const { matches, refresh: refreshMatches } = useMatches()
  const { rows: leaderboard, refresh: refreshLeaderboard } = useLeaderboard()

  useSSE(()=>{ refreshUsers(); refreshMatches(); refreshLeaderboard() })

  async function upsertMe(){
    const name = nick.trim()
    if (!name) return alert('Informe um nickname')
    try{
      const u = await api('/users/upsert', { method:'POST', body: JSON.stringify({ name }) })
      setMe(u)
    }catch(e:any){ alert(e.message||'Falha no login') }
  }

  async function seedBots(){ try{ await api('/seed/test-bots', {method:'POST'}); alert('Bots OK') }catch(e:any){ alert(e.message) } }

  async function queueEnter(){ if(!me) return alert('Faça login'); try{ const s=await api('/queue/enter',{method:'POST',body:JSON.stringify({user_id:me.id})}); if(s.match_id) alert('Partida criada: '+s.match_id) }catch(e:any){ alert(e.message) } }
  async function queueLeave(){ if(!me) return; try{ await api('/queue/leave',{method:'POST',body:JSON.stringify({user_id:me.id})}); }catch(e:any){ alert(e.message) } }

  const ongoing = matches.filter((m:any)=>m.status!=='finished')
  const finished = matches.filter((m:any)=>m.status==='finished')

  return (
    <div className="shell">
      <style>{CSS}</style>
      <header className="header">
        <div className="brand">Inhouse BR</div>
        <TabBar tab={tab} setTab={setTab} />
        <div className="auth">
          <input placeholder="Seu nickname" value={nick} onChange={e=>setNick(e.target.value)} />
          <button onClick={upsertMe}>Entrar</button>
          {me && <span className="badge">Você: {me.name}</span>}
          <span className="badge">API: {API_BASE}</span>
        </div>
      </header>

      {tab==='home' && (
        <div className="page">
          <div className="card row">
            <button onClick={seedBots}>Seed bots</button>
            <button onClick={queueEnter} disabled={!me}>Entrar na fila</button>
            <button onClick={queueLeave} disabled={!me}>Sair da fila</button>
            <span className="hint">Fila: nicks visíveis — quando draft inicia, revelação por turno</span>
          </div>

          <QueueArea me={me} />

          <section className="card">
            <h2>Partidas em andamento</h2>
            {ongoing.length===0 && <div>Nenhuma.</div>}
            {ongoing.map((m:any)=> <MatchCard key={m.id} m={m} me={me} byId={byId} />)}
          </section>
        </div>
      )}

      {tab==='history' && <HistoryTab finished={finished} byId={byId} />}

      {tab==='leaderboard' && (
        <section className="page card">
          <h2>Leaderboard</h2>
          {leaderboard.length===0 && <div>Sem dados.</div>}
          {leaderboard.length>0 && (
            <div className="lb-table">
              <div className="lb-row lb-head">
                <div>#</div><div>Jogador</div><div>Score</div><div>W</div><div>L</div><div>WinRate</div>
              </div>
              {leaderboard.map((r:any,i:number)=>(
                <div className="lb-row" key={r.user_id}>
                  <div>{i+1}</div>
                  <div>{r.name}</div>
                  <div>{Number(r.score).toFixed(2)}</div>
                  <div>{r.wins}</div>
                  <div>{r.losses}</div>
                  <div>{r.played? (r.wins/r.played*100).toFixed(1):'0.0'}%</div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {tab==='admin' && <AdminPanel />}
    </div>
  )
}

function QueueArea({me}:{me:any}){
  const [status,setStatus]=useState<{count:number,queued:boolean}|null>(null)
  const [members,setMembers]=useState<any[]>([])
  const refresh = useCallback(async()=>{
    try{ const s=await api(`/queue${me?`?user_id=${me.id}`:''}`); setStatus(s) }catch{}
    try{ const list = await api('/queue/members') ; setMembers(list) }catch{}
  },[me?.id])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 1500); return ()=>clearInterval(id) },[refresh])

  return (
    <section className="card">
      <h2>Fila</h2>
      <div className="row">
        <span className="badge">{status? `${status.count}/6` : '...'}</span>
      </div>
      <div className="queue-list">
        {members.map((u:any)=> <span key={u.user_id} className="pill">{u.name}</span>)}
        {Array.from({length: Math.max(0,6 - members.length)}).map((_,i)=>(<span key={`s${i}`} className="pill ghost">vago</span>))}
      </div>
    </section>
  )
}

function MatchCard({m, me, byId}:{m:any, me:any, byId:Record<string,any>}){
  const [local,setLocal]=useState<any>(m)
  const refresh = useCallback(async()=>{ try{ const d=await api(`/match/${m.id}`); setLocal(d) }catch{} },[m.id])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 2000); return ()=>clearInterval(id) },[refresh])

  async function auto(){ await api(`/draft/auto_current?match_id=${m.id}`,{method:'POST'}); refresh() }
  async function pick(champ:string){ if(!me) return alert('Faça login'); await api('/draft/pick',{method:'POST',body:JSON.stringify({match_id:m.id,user_id:me.id,champion_id:champ})}); refresh() }
  async function bet(team:1|2){ if(!me) return alert('Faça login'); await api('/bets/place',{method:'POST',body:JSON.stringify({match_id:m.id,team,user_id:me.id})}); refresh() }
  async function finalize(team:1|2){ await api('/match/finalize',{method:'POST',body:JSON.stringify({match_id:m.id,winner_team:team})}); refresh() }

  const picks = local.picks||{}
  const t1 = local.team1||[]
  const t2 = local.team2||[]

  // Visibilidade: 1º de cada time sempre; demais revelam quando sua pick ocorre. Seu time sempre visível.
  const round = local.draft_round||0
  const revealT1 = new Set([t1[0], ...(round>0?[t1[1]]:[]), ...(round>1?[t1[2]]:[])])
  const revealT2 = new Set([t2[0], ...(round>0?[t2[1]]:[]), ...(round>1?[t2[2]]:[])])
  const revealAllT1 = me && t1.includes(me.id)
  const revealAllT2 = me && t2.includes(me.id)

  return (
    <div className="match">
      <div className="match-head">
        <div><b>ID:</b> {local.display_id || local.id.slice(0,8)} — <b>Mapa:</b> {local.map} — <span className="badge">{local.status}</span></div>
        {local.status==='draft' && <span className="badge">Rodada {round+1}/3</span>}
        {local.status==='in_progress' && <span className="badge">Apostas: {fmtTimer(local.bet_deadline)}</span>}
      </div>
      <div className="draft-grid">
        <TeamColumn side="t1" title="Time 1" users={t1} picks={picks} byId={byId} revealSet={revealAllT1? new Set(t1): revealT1} />
        <ChampionsGrid onPick={(c)=>pick(c)} disabled={local.status!=='draft'} />
        <TeamColumn side="t2" title="Time 2" users={t2} picks={picks} byId={byId} revealSet={revealAllT2? new Set(t2): revealT2} />
      </div>
      <div className="row">
        {local.status==='draft' && (
          <>
            <button onClick={auto}>Auto-draft (rodada)</button>
            <button onClick={async()=>{ await auto(); await auto(); await auto() }}>Auto-draft (tudo)</button>
          </>
        )}
        {local.status==='in_progress' && (
          <>
            <button onClick={()=>bet(1)}>Apostar T1</button>
            <button onClick={()=>bet(2)}>Apostar T2</button>
            <BetsCount matchId={local.id}/>
          </>
        )}
        {local.status!=='draft' && (
          <>
            <button onClick={()=>finalize(1)}>Finalizar: T1</button>
            <button onClick={()=>finalize(2)}>Finalizar: T2</button>
          </>
        )}
      </div>
    </div>
  )
}

function TeamColumn({side, title, users, picks, byId, revealSet}:{side:'t1'|'t2', title:string, users:string[], picks:Record<string,string|undefined>, byId:Record<string,any>, revealSet:Set<string>}){
  return (
    <div className={`team team-${side}`}>
      <h3>{title}</h3>
      <div className="team-list">
        {users.map(uid=>{
          const champ = picks[uid]
          const name = byId[uid]?.name || uid
          const revealed = revealSet.has(uid)
          return (
            <div key={uid} className="slot">
              <div className="slot-top">
                {champ ? <ChampImg name={champ} size={56}/> : <div className="placeholder"/>}
                <div className="champ-name">{champ || '—'}</div>
              </div>
              <div className="user-name">{revealed? name : 'Jogador oculto'}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ChampionsGrid({onPick, disabled}:{onPick:(c:string)=>void, disabled:boolean}){
  return (
    <div className="champ-grid">
      <div className="champ-title">Campeões</div>
      <div className="champ-wrap">
        {CHAMPIONS.map(c=> (
          <button key={c} className="champ-btn" disabled={disabled} onClick={()=>onPick(c)}>
            <ChampImg name={c} size={48}/>
            <span>{c}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function BetsCount({matchId}:{matchId:string}){
  const [c,setC]=useState<{team1:number,team2:number}|null>(null)
  const refresh = useCallback(async()=>{ try{ const d=await api(`/bets/count?match_id=${matchId}`); setC(d) }catch{} },[matchId])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 2500); return ()=>clearInterval(id) },[refresh])
  return <span className="badge">Apostas — T1: {c?.team1??'…'} | T2: {c?.team2??'…'}</span>
}

function HistoryTab({finished, byId}:{finished:any[], byId:Record<string,any>}){
  return (
    <section className="page card">
      <h2>Histórico</h2>
      {finished.length===0 && <div>Sem partidas finalizadas.</div>}
      <div className="hist-list">
        {finished.map((m:any)=> (
          <div key={m.id} className="hist-item">
            <div className="hist-head">
              <div><b>ID:</b> {m.display_id || m.id.slice(0,8)} — <b>Mapa:</b> {m.map}</div>
              <BetsCount matchId={m.id}/>
            </div>
            <div className="hist-body">
              <div className="hist-team">
                <div className="team-title">Time 1</div>
                {(m.team1||[]).map((uid:string)=> (
                  <div key={uid} className="hist-row">
                    <span className="pill player">{byId[uid]?.name||uid}</span>
                    <span className="pill pick">{m.picks?.[uid]||'—'}</span>
                  </div>
                ))}
              </div>
              <div className="hist-mid">VS</div>
              <div className="hist-team">
                <div className="team-title">Time 2</div>
                {(m.team2||[]).map((uid:string)=> (
                  <div key={uid} className="hist-row">
                    <span className="pill player">{byId[uid]?.name||uid}</span>
                    <span className="pill pick">{m.picks?.[uid]||'—'}</span>
                  </div>
                ))}
              </div>
            </div>
            {m.winner_team && <div className="winner">Vencedor: Time {m.winner_team}</div>}
            {Array.isArray(m.streaked_player_ids) && m.streaked_player_ids.length>0 && (
              <div className="streak-flag">Streakados: {m.streaked_player_ids.map((id:string)=>byId[id]?.name||id).join(', ')}</div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

function AdminPanel(){
  const [token,setToken]=useState('')
  const [cfg,setCfg]=useState<any|null>(null)
  const [saving,setSaving]=useState(false)
  async function load(){ try{ const d=await api(`/admin/config${token?`?token=${encodeURIComponent(token)}`:''}`); setCfg(d) }catch(e:any){ alert(e.message) } }
  async function save(){ if(!cfg) return; setSaving(true); try{ const d=await api(`/admin/config${token?`?token=${encodeURIComponent(token)}`:''}`,{method:'POST',body:JSON.stringify({points:cfg.points,streak_bonus:cfg.streak_bonus,active_maps:cfg.active_maps,active_champions:cfg.active_champions})}); setCfg(d); alert('Config salva') }catch(e:any){ alert(e.message) } finally{ setSaving(false) } }
  function toggle(list:string[], item:string){ const s=new Set(list); s.has(item)? s.delete(item): s.add(item); return Array.from(s) }
  return (
    <section className="page card">
      <h2>Admin</h2>
      <div className="row">
        <input placeholder="Admin token (se configurado na API)" value={token} onChange={e=>setToken(e.target.value)} />
        <button onClick={load}>Carregar</button>
      </div>
      {!cfg && <div>Carregue a configuração.</div>}
      {cfg && (
        <div className="admin-grid">
          <div className="admin-card">
            <b>Pontos</b>
            <label>Win <input value={cfg.points.win} onChange={e=>setCfg({...cfg, points:{...cfg.points, win:Number(e.target.value)||0}})} /></label>
            <label>Loss <input value={cfg.points.loss} onChange={e=>setCfg({...cfg, points:{...cfg.points, loss:Number(e.target.value)||0}})} /></label>
          </div>
          <div className="admin-card">
            <b>Streak bonus</b>
            {Object.entries(cfg.streak_bonus).map(([k,v]:any)=> (
              <label key={k}>{k} <input value={v} onChange={e=>setCfg({...cfg, streak_bonus:{...cfg.streak_bonus, [k]:Number(e.target.value)||0}})} /></label>
            ))}
          </div>
          <div className="admin-card">
            <b>Mapas ativos</b>
            <div className="grid4">
              {cfg.maps.map((m:string)=> (
                <label key={m}><input type="checkbox" checked={cfg.active_maps.includes(m)} onChange={()=>setCfg({...cfg, active_maps: toggle(cfg.active_maps, m)})} /> {m}</label>
              ))}
            </div>
          </div>
          <div className="admin-card">
            <b>Campeões ativos</b>
            <div className="grid6">
              {cfg.champions.map((c:string)=> (
                <label key={c}><input type="checkbox" checked={cfg.active_champions.includes(c)} onChange={()=>setCfg({...cfg, active_champions: toggle(cfg.active_champions, c)})} /> {c}</label>
              ))}
            </div>
          </div>
          <div className="row">
            <button disabled={saving} onClick={save}>{saving?'Salvando…':'Salvar'}</button>
          </div>
        </div>
      )}
    </section>
  )
}

const CSS = `
:root{ --fg:#111827; --muted:#6b7280; --card:#ffffff; --line:#e5e7eb; }
*{ box-sizing:border-box }
body{ margin:0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, Noto Sans, 'Apple Color Emoji','Segoe UI Emoji'; color:var(--fg); background:#fafafa }
.shell{ max-width:1200px; margin:0 auto; padding:16px }
.header{ display:flex; align-items:center; gap:12px; justify-content:space-between; padding:8px 0 }
.brand{ font-weight:800; font-size:18px }
.tabs{ display:flex; gap:6px }
.tab{ padding:6px 10px; border:1px solid var(--line); background:#fff; border-radius:999px; cursor:pointer }
.tab.active{ background:#eef2ff }
.auth input{ padding:6px 8px; border:1px solid var(--line); border-radius:8px }
.auth .badge{ margin-left:6px }
.page{ margin-top:8px }
.card{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; margin:8px 0 }
.row{ display:flex; gap:8px; align-items:center; flex-wrap:wrap }
.badge{ display:inline-block; padding:2px 8px; border:1px solid var(--line); border-radius:999px; background:#f9fafb; font-size:12px }
.hint{ color:var(--muted); font-size:12px }
.queue-list{ display:flex; gap:6px; margin-top:8px; flex-wrap:wrap }
.pill{ padding:4px 8px; border:1px solid var(--line); border-radius:999px; background:#fff }
.pill.ghost{ opacity:.5 }

.match{ border:1px dashed var(--line); border-radius:12px; padding:10px; margin:10px 0 }
.match-head{ display:flex; gap:8px; align-items:center; justify-content:space-between; flex-wrap:wrap }
.draft-grid{ display:grid; grid-template-columns: 1fr 1.2fr 1fr; gap:12px; align-items:stretch; margin-top:10px }
.team{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:10px }
.team h3{ margin:6px 0 10px 0 }
.team-list{ display:grid; gap:8px }
.slot{ border:1px solid var(--line); border-radius:10px; padding:8px; background:#fcfcff }
.slot-top{ display:flex; gap:8px; align-items:center }
.placeholder{ width:56px; height:56px; background:#f3f4f6; border-radius:6px; border:1px dashed var(--line) }
.champ-name{ font-weight:600 }
.user-name{ color:var(--muted); font-size:12px }

.champ-grid{ border:1px solid var(--line); border-radius:12px; padding:10px; background:#fff; display:flex; flex-direction:column; gap:8px }
.champ-title{ font-weight:700; text-align:center }
.champ-wrap{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:8px; max-height: 360px; overflow:auto; padding:4px }
.champ-btn{ display:flex; align-items:center; gap:8px; justify-content:flex-start; border:1px solid var(--line); background:#ffffff; padding:8px; border-radius:10px; cursor:pointer }
.champ-btn:disabled{ opacity:.5; cursor:not-allowed }
.chip-fallback{ display:inline-flex; width:40px; height:40px; align-items:center; justify-content:center; border-radius:6px; border:1px solid var(--line); background:#fff; font-weight:700 }

.lb-table{ display:grid; gap:4px }
.lb-row{ display:grid; grid-template-columns: 40px 1fr 90px 50px 50px 90px; gap:8px; padding:6px; border-bottom:1px solid var(--line) }
.lb-head{ font-weight:700; background:#f9fafb; border-radius:8px }

.hist-list{ display:grid; gap:10px }
.hist-item{ border:1px solid var(--line); border-radius:12px; padding:10px; background:#fff }
.hist-head{ display:flex; align-items:center; justify-content:space-between; gap:8px }
.hist-body{ display:grid; grid-template-columns: 1fr 60px 1fr; gap:8px; align-items:start; margin-top:6px }
.hist-row{ display:flex; gap:8px; align-items:center }
.team-title{ font-weight:700; margin-bottom:4px }
.hist-mid{ display:flex; align-items:center; justify-content:center; font-weight:800 }
.winner{ margin-top:6px; font-weight:700 }
.streak-flag{ margin-top:4px; font-size:12px; color:#6b7280 }

.admin-grid{ display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:10px; margin-top:8px }
.admin-card{ border:1px solid var(--line); border-radius:10px; padding:10px; background:#fff; display:flex; flex-direction:column; gap:6px }
.grid4{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:6px }
.grid6{ display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); gap:6px }
`
