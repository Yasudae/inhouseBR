import React, { useEffect, useMemo, useState, useCallback } from 'react'

/**
 * Inhouse BR — App.tsx (arquivo único, pronto pra colar)
 * - Fila: nicks + contador X/6
 * - Draft: picks revelados juntos (par por rodada)
 * - Leaderboard: perfil clicável (modal)
 * - Admin: exige token, seed bots e demo draft
 * - Bets: contador "MM:SS restantes"
 * - Histórico: em aba própria
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8330'
const CHAMP_IMG_BASE = import.meta.env.VITE_CHAMP_IMG_BASE || '' // e.g. "https://seu.cdn/champions/"

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let msg = ''
    try { msg = await res.text() } catch {}
    throw new Error(msg || `HTTP ${res.status}`)
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

const CHAMPIONS = [
  'Alysia', 'Ashka','Bakko','Blossom','Croak','Destiny','Ezmo','Freya','Iva','Jade','Jamila',
  'Jumong','Lucie','Oldur','Pestilus','Poloma','Raigon','Rook','Ruh Kaan','Shen Rao', 'Shifu','Sirius',
  'Taya','Thorn','Ulric','Varesh','Zander'
]

function slugifyChamp(name:string){
  return name.toLowerCase().replace(/\s+/g,'-').replace(/[^a-z0-9\-]/g,'')
}

function ChampImg({name, size=40}:{name:string, size?:number}){
  const [ok,setOk]=useState(!!CHAMP_IMG_BASE)
  if (!CHAMP_IMG_BASE) return <span className="chip-fallback">{name.slice(0,2).toUpperCase()}</span>
  const url = `${CHAMP_IMG_BASE}${slugifyChamp(name)}.png`
  return (
    <img
      src={url}
      alt={name}
      title={name}
      width={size}
      height={size}
      onError={()=>setOk(false)}
      style={{display: ok? 'inline-block':'none', objectFit:'cover', borderRadius:6}}
    />
  )
}

function useSSE(onEvent:(e:any)=>void){
  useEffect(()=>{
    const es = new EventSource(`${API_BASE}/events`)
    es.onmessage = (ev)=>{ try{ const data = JSON.parse(ev.data); onEvent(data) }catch{} }
    return ()=>{ es.close() }
  }, [onEvent])
}

/* ===================== Hooks de dados ===================== */

function useUsers() {
  const [users, setUsers] = useState<any[]>([])
  const refresh = useCallback(async()=>{
    try{ const d = await api('/users'); setUsers(Array.isArray(d)? d:[]) }catch{}
  }, [])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 3000); return ()=>clearInterval(id) },[refresh])
  const byId = useMemo(()=>Object.fromEntries(users.map(u=>[u.id,u])),[users])
  return { users, byId, refresh }
}

function useMatches() {
  const [matches, setMatches] = useState<any[]>([])
  const refresh = useCallback(async()=>{
    try{ const d = await api('/matches'); setMatches(Array.isArray(d)? d:[]) }catch{}
  }, [])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 2500); return ()=>clearInterval(id) },[refresh])
  return { matches, refresh }
}

function useLeaderboard(){
  const [rows,setRows]=useState<any[]>([])
  const refresh = useCallback(async()=>{
    try{ const d = await api('/leaderboard'); setRows(Array.isArray(d)? d:[]) }catch{}
  }, [])
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

/* ===================== App ===================== */

export default function App(){
  const [tab, setTab] = useState<'home'|'history'|'leaderboard'|'admin'>('home')
  const [nick,setNick]=useState('')
  const [me,setMe]=useState<any>(null)
  const { users, byId, refresh: refreshUsers } = useUsers()
  const { matches, refresh: refreshMatches } = useMatches()
  const { rows: leaderboard, refresh: refreshLeaderboard } = useLeaderboard()
  const [profileId,setProfileId]=useState<string|null>(null)

  useSSE(()=>{ refreshUsers(); refreshMatches(); refreshLeaderboard() })

  async function upsertMe(){
    const name = nick.trim()
    if (!name) return alert('Informe um nickname')
    try{
      const u = await api('/users/upsert', { method:'POST', body: JSON.stringify({ name }) })
      setMe(u)
    }catch(e:any){ alert(e.message||'Falha no login') }
  }

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
          <QueueArea me={me} />
          <section className="card">
            <h2>Partidas em andamento</h2>
            {ongoing.length===0 && <div>Nenhuma.</div>}
            {ongoing.map((m:any)=> (
              <MatchCard key={m.id} m={m} me={me} byId={byId} onOpenProfile={(uid)=>setProfileId(uid)} />
            ))}
          </section>
        </div>
      )}

      {tab==='history' && <HistoryTab finished={finished} byId={byId} onOpenProfile={(uid)=>setProfileId(uid)} />}

      {tab==='leaderboard' && <LeaderboardTab rows={leaderboard} onOpenProfile={(uid)=>setProfileId(uid)} />}

      {tab==='admin' && <AdminPanel me={me} />}

      {profileId && <ProfileModal userId={profileId} onClose={()=>setProfileId(null)} />}
    </div>
  )
}

/* ===================== Fila ===================== */

function useQueue(me:any){
  const [status,setStatus]=useState<{count:number,queued:boolean}|null>(null)
  const [members,setMembers]=useState<any[]>([])
  const refresh = useCallback(async()=>{
    try{ const s=await api(`/queue${me?`?user_id=${me.id}`:''}`); setStatus(s) }catch{}
    try{ const list = await api('/queue/members'); setMembers(Array.isArray(list)? list: []) }catch{}
  },[me?.id])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 1500); return ()=>clearInterval(id) },[refresh])
  return { status, members }
}

function QueueArea({me}:{me:any}){
  const { status, members } = useQueue(me)
  async function enter(){ if(!me) return alert('Faça login'); try{ const s=await api('/queue/enter',{method:'POST',body:JSON.stringify({user_id:me.id})}); if(s.match_id) alert('Partida criada: '+s.match_id) }catch(e:any){ alert(e.message) } }
  async function leave(){ if(!me) return; try{ await api('/queue/leave',{method:'POST',body:JSON.stringify({user_id:me.id})}); }catch(e:any){ alert(e.message) } }
  return (
    <section className="card">
      <h2>Fila</h2>
      <div className="row">
        <span className="badge">{status? `${status.count}/6` : '...'}</span>
        <span className="hint">Nicks visíveis na fila</span>
      </div>
      <div className="queue-list" style={{marginTop:8}}>
        {members.map((u:any)=> <span key={u.user_id} className="pill">{u.name}</span>)}
        {Array.from({length: Math.max(0,6 - (members?.length||0))}).map((_,i)=>(<span key={`s${i}`} className="pill ghost">vago</span>))}
      </div>
      <div className="row" style={{marginTop:8}}>
        <button onClick={enter} disabled={!me}>Entrar na fila</button>
        <button onClick={leave} disabled={!me}>Sair da fila</button>
      </div>
    </section>
  )
}

/* ===================== Match / Draft ===================== */

function MatchCard({m, me, byId, onOpenProfile}:{m:any, me:any, byId:Record<string,any>, onOpenProfile:(uid:string)=>void}){
  const [local,setLocal]=useState<any>(m)
  const refresh = useCallback(async()=>{ try{ const d=await api(`/match/${m.id}`); setLocal(d) }catch{} },[m.id])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 1500); return ()=>clearInterval(id) },[refresh])

  async function auto(){ await api(`/draft/auto_current?match_id=${m.id}`,{method:'POST'}); refresh() }
  async function pick(champ:string){
    if(!me) return alert('Faça login')
    await api('/draft/pick',{method:'POST',body:JSON.stringify({match_id:m.id,user_id:me.id,champion_id:champ})})
    refresh()
  }
  async function bet(team:1|2){
    if(!me) return alert('Faça login')
    await api('/bets/place',{method:'POST',body:JSON.stringify({match_id:m.id,team,user_id:me.id})})
    refresh()
  }
  async function finalize(team:1|2){
    await api('/match/finalize',{method:'POST',body:JSON.stringify({match_id:m.id,winner_team:team})})
    refresh()
  }

  const picks = local.picks||{}
  const t1 = local.team1||[]
  const t2 = local.team2||[]

  const teamOf = (uid:string)=> t1.includes(uid)? 1 : (t2.includes(uid)? 2 : 0)
  const viewerTeam = me? teamOf(me.id) : 0
  const currentRound = local.draft_round ?? 0

  // round index de cada jogador = posição na lista (0,1,2) => rótulos 1,2,3
  const roundIndexOf = (uid:string) => (t1.includes(uid)? t1.indexOf(uid) : t2.includes(uid)? t2.indexOf(uid) : -1)
  const bothPickedAtIndex = (idx:number) => {
    const u1 = t1[idx]; const u2 = t2[idx]
    return Boolean(u1 && u2 && picks[u1] && picks[u2])
  }

  // nomes: 1º de cada time visível desde início; demais quando chega a vez. Seu time sempre se enxerga por completo.
  const baseReveal = {
    t1: new Set<string>([ t1[0], ...(currentRound>0?[t1[1]]:[]), ...(currentRound>1?[t1[2]]:[]) ]),
    t2: new Set<string>([ t2[0], ...(currentRound>0?[t2[1]]:[]), ...(currentRound>1?[t2[2]]:[]) ])
  }
  const revealAllT1 = viewerTeam===1
  const revealAllT2 = viewerTeam===2

  // visibilidade do campeão para QUEM está vendo (eu):
  function visibleChampForViewer(uid:string): {champ?:string, waiting:boolean}{
    const champ = picks[uid]
    if (!champ) return { waiting:false }

    const idx = roundIndexOf(uid)
    if (idx < 0) return { waiting:false }

    const isAlly = viewerTeam === teamOf(uid)
    const pairDone = bothPickedAtIndex(idx)

    if (pairDone) return { champ, waiting:false }
    if (isAlly)   return { champ, waiting:true }
    return { waiting:false }
  }

  // campeões já escolhidos NO MEU TIME (para desabilitar botões do grid central)
  const takenInMyTeam = useMemo(()=>{
    const set = new Set<string>()
    if (!me) return set
    const myTeam = viewerTeam===1 ? t1 : viewerTeam===2 ? t2 : []
    myTeam.forEach(uid => { if (picks[uid]) set.add(picks[uid]) })
    return set
  }, [viewerTeam, t1, t2, picks, me])

  return (
    <div className="match">
      <div className="match-head">
        <div>
          <b>ID:</b> {local.display_id || local.id.slice(0,8)} — <b>Mapa:</b> {local.map} —{' '}
          <span className="badge">{local.status}</span>
        </div>
        {local.status==='draft' && <span className="badge">Rodada {Math.min(currentRound+1,3)}/3</span>}
        {local.status==='in_progress' && <span className="badge">Apostas: {fmtTimer(local.bet_deadline)}</span>}
      </div>

      <div className="draft-grid">
        <TeamColumn
          side="t1" title="Time 1" users={t1} byId={byId}
          nameRevealSet={revealAllT1? new Set(t1): baseReveal.t1}
          getViewData={visibleChampForViewer}
          onOpenProfile={onOpenProfile}
          currentRound={currentRound}
        />
        <ChampionsGrid onPick={(c)=>pick(c)} disabled={local.status!=='draft'} takenInMyTeam={takenInMyTeam}/>
        <TeamColumn
          side="t2" title="Time 2" users={t2} byId={byId}
          nameRevealSet={revealAllT2? new Set(t2): baseReveal.t2}
          getViewData={visibleChampForViewer}
          onOpenProfile={onOpenProfile}
          currentRound={currentRound}
        />
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

/* ===================== TeamColumn (SUBSTITUIR INTEIRO) ===================== */

/* ===================== TeamColumn (SUBSTITUIR INTEIRO) ===================== */

function TeamColumn({
  side, title, users, byId, nameRevealSet, getViewData, onOpenProfile, currentRound
}:{side:'t1'|'t2', title:string, users:string[], byId:Record<string,any>, nameRevealSet:Set<string>,
  getViewData:(uid:string)=>{champ?:string, waiting:boolean}, onOpenProfile:(uid:string)=>void, currentRound:number }){
  return (
    <div className={`team team-${side}`}>
      <h3>{title}</h3>
      <div className="team-list">
        {users.map((uid, idx)=>{
          const {champ, waiting} = getViewData(uid)
          const name = byId[uid]?.name || uid
          const nameRevealed = nameRevealSet.has(uid)
          const roundLabel = `Round ${idx+1}` // idx 0->R1, 1->R2, 2->R3
          const isCurrent = idx === currentRound

          return (
            <div key={uid} className={`slot ${isCurrent? `slot-current-${side}`:''}`}>
              <div className="slot-head">
                <span className={`round-badge ${side==='t1'?'blue':'red'}`}>{roundLabel}</span>
              </div>
              <div className="slot-top">
                {champ ? <ChampImg name={champ} size={56}/> : <div className="placeholder"/>}
                <div className="champ-name">
                  {champ || '—'}
                  {waiting && <span className="chip waiting">aguardando oponente</span>}
                </div>
              </div>
              <div className="user-name">
                {nameRevealed
                  ? <button className="linklike name-btn" onClick={()=>onOpenProfile(uid)} title="Ver perfil">{name}</button>
                  : 'Jogador oculto'}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}



/* ===================== ChampionsGrid (SUBSTITUIR INTEIRO) ===================== */

type ChampGroups = {
  melee: string[]
  ranged: string[]
  support: string[]
}
const CHAMP_GROUPS: ChampGroups = {
  melee: [
    'Bakko','Croak','Freya','Jamila','Raigon','Rook','Ruh Kaan','Shifu','Thorn',
  ],
  ranged: [
    'Alysia','Ashka','Destiny','Ezmo','Iva','Jade','Jumong','Shen Rao','Taya','Varesh',
  ],
  support: [
    'Blossom','Lucie','Oldur','Pestilus','Poloma','Sirius','Ulric','Zander',
  ],
}

function sortAZ(list: string[]) {
  return [...list].sort((a,b)=> a.localeCompare(b, 'pt-BR'))
}

/**
 * onPick: callback para clicar no campeão
 * disabled: desativa tudo (ex.: fora do draft)
 * takenInMyTeam: set de campeões já escolhidos no SEU time (para desabilitar botões)
 */
function ChampionsGrid({
  onPick, disabled, takenInMyTeam = new Set<string>()
}:{onPick:(c:string)=>void, disabled:boolean, takenInMyTeam?: Set<string>}){
  const melee = sortAZ(CHAMP_GROUPS.melee)
  const ranged = sortAZ(CHAMP_GROUPS.ranged)
  const support = sortAZ(CHAMP_GROUPS.support)

  const Section = ({title, champs}:{title:string, champs:string[]}) => (
    <>
      <div className="champ-section-title">{title}</div>
      <div className="champ-wrap">
        {champs.map(c=> {
          const isDisabled = disabled || takenInMyTeam.has(c)
          return (
            <button
              key={c}
              className={`champ-btn ${isDisabled? 'is-disabled':''}`}
              disabled={isDisabled}
              onClick={()=>onPick(c)}
              title={isDisabled? 'Já escolhido pelo seu time' : c}
            >
              <ChampImg name={c} size={48}/>
              <span>{c}</span>
            </button>
          )
        })}
      </div>
    </>
  )

  return (
    <div className="champ-grid">
      <div className="champ-title">Seleção de Campeões</div>
      <Section title="[Melee]" champs={melee}/>
      <Section title="[Ranged]" champs={ranged}/>
      <Section title="[Support]" champs={support}/>
    </div>
  )
}


function BetsCount({matchId}:{matchId:string}){
  const [c,setC]=useState<{team1:number,team2:number}|null>(null)
  const refresh = useCallback(async()=>{
    try{ const d=await api(`/bets/count?match_id=${matchId}`); setC(d) }catch{}
  },[matchId])
  useEffect(()=>{ refresh(); const id=setInterval(refresh, 2500); return ()=>clearInterval(id) },[refresh])
  return <span className="badge">Apostas — T1: {c?.team1??'…'} | T2: {c?.team2??'…'}</span>
}

/* ===================== Histórico ===================== */

function HistoryTab({finished, byId, onOpenProfile}:{finished:any[], byId:Record<string,any>, onOpenProfile:(uid:string)=>void}){
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
                    <button className="linklike" onClick={()=>onOpenProfile(uid)}>{byId[uid]?.name||uid}</button>
                    <span className="pill pick">{m.picks?.[uid]||'—'}</span>
                  </div>
                ))}
              </div>
              <div className="hist-mid">VS</div>
              <div className="hist-team">
                <div className="team-title">Time 2</div>
                {(m.team2||[]).map((uid:string)=> (
                  <div key={uid} className="hist-row">
                    <button className="linklike" onClick={()=>onOpenProfile(uid)}>{byId[uid]?.name||uid}</button>
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

/* ===================== Leaderboard & Perfil ===================== */

/* ===================== Leaderboard (SUBSTITUIR INTEIRO) ===================== */

function LeaderboardTab({rows, onOpenProfile}:{rows:any[], onOpenProfile:(uid:string)=>void}){
  return (
    <section className="page card">
      <h2>Leaderboard</h2>
      {rows.length===0 && <div>Sem dados.</div>}
      {rows.length>0 && (
        <div className="lb-table">
          <div className="lb-row lb-head">
            <div>#</div><div>Jogador</div><div>Score</div><div>W</div><div>L</div><div>WinRate</div><div></div>
          </div>
          {rows.map((r:any,i:number)=>(
            <RowWithDetails key={r.user_id} rank={i+1} row={r} onOpenProfile={onOpenProfile}/>
          ))}
        </div>
      )}
    </section>
  )
}

function RowWithDetails({rank, row, onOpenProfile}:{rank:number,row:any,onOpenProfile:(uid:string)=>void}){
  const [open,setOpen]=useState(false)
  const [prof,setProf]=useState<any|null>(null)
  useEffect(()=>{
    if(open && !prof){
      (async()=>{
        try{ const d=await api(`/users/${row.user_id}/profile`); setProf(d) }catch{}
      })()
    }
  },[open, prof, row.user_id])

  const winrate = row.played? (row.wins/row.played*100).toFixed(1) : '0.0'

  return (
    <>
      <div className="lb-row">
        <div>{rank}</div>
        <div>
          <button className="linklike" onClick={()=>onOpenProfile(row.user_id)} title="Abrir perfil">{row.name}</button>
        </div>
        <div>{Number(row.score).toFixed(2)}</div>
        <div>{row.wins}</div>
        <div>{row.losses}</div>
        <div>{winrate}%</div>
        <div>
          <button className="mini-btn" onClick={()=>setOpen(o=>!o)}>{open? 'Ocultar':'Por Campeão'}</button>
        </div>
      </div>
      {open && (
        <div className="lb-detail">
          {!prof && <div>Carregando…</div>}
          {prof && <ChampionStatsMini champions={prof.champions||[]} />}
        </div>
      )}
    </>
  )
}

function ChampionStatsMini({champions}:{champions:any[]}){
  const rows = [...champions].sort((a,b)=> (b.played||0)-(a.played||0))
  return (
    <div className="mini-table">
      <div className="mini-row mini-head">
        <div>Campeão</div><div>Jogos</div><div>Vitórias</div><div>Derrotas</div><div>WinRate</div><div>Seq. quebradas</div>
      </div>
      {rows.map((c:any)=> {
        const played = c.played||0
        const wins = c.wins||0
        const losses = Math.max(0, played - wins)
        const wr = played? ((wins/played)*100).toFixed(0)+'%' : '0%'
        return (
          <div key={c.champion} className="mini-row">
            <div className="mini-champ">
              <ChampImg name={c.champion} size={22}/>
              <span>{c.champion}</span>
            </div>
            <div>{played}</div>
            <div>{wins}</div>
            <div>{losses}</div>
            <div>{wr}</div>
            <div>{c.streaks_broken||0}</div>
          </div>
        )
      })}
      {rows.length===0 && <div className="mini-empty">Sem histórico por campeão.</div>}
    </div>
  )
}


function ProfileModal({userId, onClose}:{userId:string, onClose:()=>void}){
  const [profile,setProfile]=useState<any|null>(null)
  useEffect(()=>{ (async()=>{ try{ const d=await api(`/users/${userId}/profile`); setProfile(d) }catch(e:any){ console.error(e) } })() },[userId])
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()}>
        {!profile && <div>Carregando…</div>}
        {profile && (
          <>
            <h3>Perfil — {profile.user?.name}</h3>
            <div className="profile-grid">
              <div className="stat"><b>Partidas</b><span>{profile.stats?.played ?? 0}</span></div>
              <div className="stat"><b>Vitórias</b><span>{profile.stats?.wins ?? 0}</span></div>
              <div className="stat"><b>Derrotas</b><span>{profile.stats?.losses ?? 0}</span></div>
              <div className="stat"><b>WinRate</b><span>{profile.stats?.played? ((profile.stats.wins/profile.stats.played)*100).toFixed(1):'0.0'}%</span></div>
              <div className="stat"><b>Streak atual</b><span>{profile.stats?.current_streak ?? 0}</span></div>
              <div className="stat"><b>Streak máx</b><span>{profile.stats?.max_streak ?? 0}</span></div>
              <div className="stat"><b>Streaks quebradas</b><span>{profile.stats?.streaks_broken ?? 0}</span></div>
              <div className="stat"><b>Apostas corretas</b><span>{profile.stats?.correct_bets ?? 0}</span></div>
              <div className="stat"><b>Score</b><span>{Number(profile.stats?.score||0).toFixed(2)}</span></div>
            </div>
            <div style={{marginTop:10}}>
              <b>Heróis jogados</b>
              <div className="champ-list">
                {(profile.champions||[]).sort((a:any,b:any)=> (b.played||0)-(a.played||0)).map((c:any)=> (
                  <div key={c.champion} className="champ-row">
                    <ChampImg name={c.champion} size={28}/>
                    <span className="champ-nm">{c.champion}</span>
                    <span className="chip">{c.played} jogos</span>
                    <span className="chip">{c.wins||0} vitórias</span>
                    <span className="chip">{c.wins && c.played? ((c.wins/c.played)*100).toFixed(0):'0'}%</span>
                    <span className="chip">{c.streaks_broken||0} seq. quebradas</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="row" style={{marginTop:10, justifyContent:'flex-end'}}>
              <button onClick={onClose}>Fechar</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/* ===================== Admin ===================== */
/* ===================== Admin (SUBSTITUIR INTEIRO) ===================== */

function AdminPanel({me}:{me:any}){
  const [token,setToken]=useState(localStorage.getItem('admin_token')||'')
  const [cfg,setCfg]=useState<any|null>(null)
  const [saving,setSaving]=useState(false)
  const [err,setErr]=useState<string|null>(null)

  useEffect(()=>{ localStorage.setItem('admin_token', token) },[token])

  async function load(){
    setErr(null)
    try{
      const d=await api(`/admin/config${token?`?token=${encodeURIComponent(token)}`:''}`)
      setCfg(d)
    }catch(e:any){
      setCfg(null)
      setErr(e?.message || 'Falha ao carregar configuração')
    }
  }
  async function save(){
    if(!cfg) return
    setSaving(true); setErr(null)
    try{
      const d=await api(`/admin/config${token?`?token=${encodeURIComponent(token)}`:''}`,{
        method:'POST',
        body:JSON.stringify({
          points:cfg.points,
          streak_bonus:cfg.streak_bonus,
          active_maps:cfg.active_maps,
          active_champions:cfg.active_champions
        })
      })
      setCfg(d)
      alert('Config salva')
    }catch(e:any){
      setErr(e?.message || 'Falha ao salvar')
    } finally{
      setSaving(false)
    }
  }
  async function seedBots(){
    setErr(null)
    try{
      await api(`/seed/test-bots${token?`?token=${encodeURIComponent(token)}`:''}`,{method:'POST'})
      alert('Bots criados/garantidos.')
    }catch(e:any){ setErr(e?.message || 'Falha no seed') }
  }
  async function createDemo(){
    if(!me){ alert('Faça login com seu nick antes.'); return }
    setErr(null)
    try{
      const all = await api('/users')
      const bots = all.filter((u:any)=>/^BOT[1-5]$/.test(u.name)).slice(0,5)
      if(bots.length<5){ alert('Crie os bots primeiro.'); return }
      const ids = [me.id, ...bots.map((b:any)=>b.id)]
      const created = await api(`/match/create${token?`?token=${encodeURIComponent(token)}`:''}`,{
        method:'POST', body: JSON.stringify({ user_ids: ids })
      })
      // 3 rodadas simultâneas
      await api(`/draft/auto_current?match_id=${created.id}${token?`&token=${encodeURIComponent(token)}`:''}`,{method:'POST'})
      await api(`/draft/auto_current?match_id=${created.id}${token?`&token=${encodeURIComponent(token)}`:''}`,{method:'POST'})
      await api(`/draft/auto_current?match_id=${created.id}${token?`&token=${encodeURIComponent(token)}`:''}`,{method:'POST'})
      alert('Partida demo criada e draft concluído.')
    }catch(e:any){
      setErr(e?.message || 'Falha ao criar demo')
    }
  }

  return (
    <section className="page card">
      <h2>Admin</h2>
      <div className="row">
        <input placeholder="Admin token" value={token} onChange={e=>setToken(e.target.value)} />
        <button onClick={load}>Carregar</button>
        {cfg && <button onClick={save} disabled={saving}>{saving? 'Salvando…':'Salvar config'}</button>}
      </div>
      {err && <div className="admin-error">⚠ {err}</div>}
      <div className="row" style={{marginTop:8}}>
        <button onClick={seedBots}>Seed bots (admin)</button>
        <button onClick={createDemo}>Criar partida demo (eu + 5 bots)</button>
      </div>
      {!cfg && <div style={{marginTop:8}}>Carregue a configuração para editar pontos/mapas/campeões.</div>}
      {cfg && (
        <div className="admin-grid">
          <div className="admin-card">
            <b>Pontos</b>
            <label>Win <input value={cfg.points.win} onChange={e=>setCfg({...cfg, points:{...cfg.points, win:Number(e.target.value)||0}})} /></label>
            <label>Loss <input value={cfg.points.loss} onChange={e=>setCfg({...cfg, points:{...cfg.points, loss:Number(e.target.value)||0}})} /></label>
          </div>
          <div className="admin-card">
            <b>Streak bonus</b>
            {Object.entries(cfg.streak_bonus||{}).map(([k,v]:any)=> (
              <label key={k}>{k} <input value={v} onChange={e=>setCfg({...cfg, streak_bonus:{...cfg.streak_bonus, [k]:Number(e.target.value)||0}})} /></label>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}


/* ===================== CSS inline ===================== */

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
.linklike{ background:none; border:none; color:#2563eb; cursor:pointer; padding:0 }
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

.modal-backdrop{ position:fixed; inset:0; background:rgba(0,0,0,.4); display:flex; align-items:center; justify-content:center; padding:16px; z-index:50 }
.modal{ background:#fff; border-radius:12px; border:1px solid var(--line); padding:16px; max-width:720px; width:100% }
.profile-grid{ display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:8px; margin-top:8px }
.stat{ display:flex; flex-direction:column; gap:2px; padding:8px; border:1px solid var(--line); border-radius:8px; background:#fafafa }
.champ-list{ display:grid; gap:6px; margin-top:8px }
.champ-row{ display:flex; gap:8px; align-items:center }
.chip{ border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; background:#fff }
.champ-nm{ min-width:120px }

/* ---- Ajustes novos ---- */
.admin-error{ margin-top:8px; padding:8px; background:#fff3f3; border:1px solid #fca5a5; border-radius:8px; color:#991b1b }
.name-btn{ font-weight:600 }

.chip.waiting{ margin-left:6px; font-size:11px; background:#fff7ed; border-color:#fed7aa }
.lb-row > div:last-child{ text-align:right }

.lb-detail{ padding:8px 12px; background:#f9fafb; border-left:3px solid #e5e7eb; }
.mini-table{ display:grid; gap:4px }
.mini-row{ display:grid; grid-template-columns: 1.2fr 0.6fr 0.6fr 0.6fr 0.8fr 1fr; gap:8px; padding:6px; border-bottom:1px dashed #e5e7eb }
.mini-head{ font-weight:700; background:#f3f4f6 }
.mini-champ{ display:flex; align-items:center; gap:6px }
.mini-empty{ padding:6px; color:#6b7280 }

.mini-btn{ border:1px solid var(--line); background:#fff; border-radius:999px; padding:4px 8px; cursor:pointer }

/* ---- Draft layout ajustes (categorias & rounds) ---- */
.champ-section-title{
  font-weight:700;
  margin-top:6px;
  margin-bottom:2px;
  text-align:center;
  color:#374151;
}
.champ-btn.is-disabled{
  opacity:.45;
  cursor:not-allowed;
  filter: grayscale(0.4);
}
.round-badge{
  display:inline-block; font-size:11px; padding:2px 6px; border-radius:999px; color:#111827; background:#e5e7eb; border:1px solid var(--line)
}
.round-badge.blue{ background:#e0f2fe; border-color:#bae6fd }
.round-badge.red{ background:#fee2e2; border-color:#fecaca }
.slot-head{ display:flex; justify-content:flex-start; margin-bottom:6px }
.slot-current-t1{ box-shadow: 0 0 0 2px rgba(59,130,246,.25) inset }
.slot-current-t2{ box-shadow: 0 0 0 2px rgba(239,68,68,.25) inset }
`
