"use client";

import {useCallback, useEffect, useState, type FormEvent, type ReactNode} from "react";
import {ArrowDownToLine, ArrowRight, Bell, BookOpen, Check, CheckCircle2, ChevronRight, Clock3, Code2, ExternalLink, FileText, Globe2, History, Loader2, LogOut, Mail, Play, Radio, RefreshCw, Settings2, ShieldCheck, Sparkles, Sun, Terminal, Workflow, X} from "lucide-react";
import {api, type User, type Health, type Prefs, type Run, type Digest, type Trace, type Notice} from "./types";

const sourceNames: Record<string, string> = {openai: "OpenAI", huggingface: "Hugging Face", google_ai: "Google AI", techcrunch: "TechCrunch"};
const statusNames: Record<string, string> = {queued: "排队中", running: "执行中", completed: "已完成", incomplete: "未完成", failed: "失败", interrupted: "已中断", pending: "待推送", sent: "已送达", sending: "发送中", uncertain: "待核查", cancelled: "已取消"};
type Tab = "today" | "preferences" | "history" | "trace";
const nav: {id: Tab; label: string; icon: typeof Sun; small: string}[] = [
  {id: "today", label: "日报工作台", icon: Sun, small: "Overview"},
  {id: "preferences", label: "订阅配置", icon: Settings2, small: "Preferences"},
  {id: "history", label: "历史日报", icon: History, small: "Archive"},
  {id: "trace", label: "Agent Trace", icon: Workflow, small: "Observability"}
];
const stamp = (s: string) => new Date(s).toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});
function Badge({status}: {status: string}) {return <span className={`badge ${status}`}>{["running", "queued", "sending"].includes(status) && <Loader2 size={12} className="spin"/>}{statusNames[status] || status}</span>}
function Empty({icon, title, text, children}: {icon: ReactNode; title: string; text: string; children?: ReactNode}) {
  return <div className="empty"><span className="empty-icon">{icon}</span><h3>{title}</h3><p>{text}</p>{children}</div>;
}

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [tab, setTab] = useState<Tab>("today");
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [topics, setTopics] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [digests, setDigests] = useState<Digest[]>([]);
  const [digest, setDigest] = useState<Digest | null>(null);
  const [traceRun, setTraceRun] = useState<Run | null>(null);
  const [trace, setTrace] = useState<Trace[]>([]);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [showNotices, setShowNotices] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [archivePage, setArchivePage] = useState(0);
  const [archive, setArchive] = useState<Digest[]>([]);

  const refresh = useCallback(async () => {
    const [r, d, n] = await Promise.all([api<Run[]>("/runs"), api<Digest[]>("/digests"), api<Notice[]>("/notifications")]);
    setRuns(r); setDigests(d); setNotices(n);
  }, []);
  useEffect(() => {
    api<Health>("/health").then(setHealth).catch(() => setError("后端暂时无法连接，请确认 FastAPI 已启动。"));
    api<User>("/me").then(setUser).catch(() => {}).finally(() => setReady(true));
  }, []);
  useEffect(() => {
    if (!user) return;
    api<Prefs>("/preferences").then(p => {setPrefs(p); setTopics(p.topics.join(", "));}).catch(e => setError(e.message));
    refresh().catch(e => setError(e.message));
    const timer = setInterval(() => refresh().catch(() => {}), 4000);
    return () => clearInterval(timer);
  }, [user, refresh]);
  useEffect(() => {
    if (user && !digest && digests.length) api<Digest>(`/digests/${digests[0].id}`).then(setDigest).catch(e => setError(e.message));
  }, [user, digest, digests]);
  useEffect(() => {
    if (!user || !digest) return;
    const id = digest.id;
    const timer = setInterval(() => api<Digest>(`/digests/${id}`).then(d => setDigest(old => old?.id === id ? d : old)).catch(() => {}), 4000);
    return () => clearInterval(timer);
  }, [user, digest?.id]);
  useEffect(() => {
    if (!traceRun || !user) return;
    let cancelled = false;
    const load = () => Promise.all([api<Trace[]>(`/runs/${traceRun.id}/trace`), api<Run>(`/runs/${traceRun.id}`)]).then(([t, r]) => {
      if (!cancelled) {setTrace(t); setTraceRun(old => old?.id === r.id ? r : old);}
    }).catch(e => {if (!cancelled) setError(e.message);});
    load(); const timer = setInterval(load, 3000);
    return () => {cancelled = true; clearInterval(timer);};
  }, [traceRun?.id, user]);
  useEffect(() => {
    if (tab === "trace" && !traceRun && runs.length) setTraceRun(runs[0]);
  }, [tab, runs, traceRun]);
  useEffect(() => {
    if (user && tab === "history") api<Digest[]>(`/digests?limit=12&offset=${archivePage * 12}`).then(setArchive).catch(e => setError(e.message));
  }, [user, tab, archivePage, digests.length]);
  useEffect(() => {if (message) {const t = setTimeout(() => setMessage(""), 5000); return () => clearTimeout(t);}}, [message]);

  async function authenticate(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try {setUser(await api<User>(`/auth/${register ? "register" : "login"}`, {method: "POST", body: JSON.stringify({email, password})})); setPassword("");}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function generate() {
    setBusy(true); setError("");
    try {
      const r = await api<Run>("/runs", {method: "POST", headers: {"Idempotency-Key": crypto.randomUUID()}});
      setTraceRun(r); setTrace([]); setTab("trace"); await refresh();
      setMessage(r.status === "completed" ? "今天的日报已生成，可查看已有日报。" : "任务已提交，Agent 正在自主选择工具。");
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function savePreferences(e: FormEvent) {
    e.preventDefault(); if (!prefs) return; setBusy(true); setError("");
    try {const updated = await api<Prefs>("/preferences", {method: "PUT", body: JSON.stringify({...prefs, topics: topics.split(/[,，]/).map(v => v.trim()).filter(Boolean)})}); setPrefs(updated); setMessage("订阅配置已保存，下一次任务将使用新配置。");}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function openDigest(id: string) {
    try {setDigest(await api<Digest>(`/digests/${id}`)); setTab("today"); setShowNotices(false);}
    catch (e) {setError((e as Error).message);}
  }
  async function logout() {
    try {await api("/auth/logout", {method: "POST"}); setUser(null); setPrefs(null); setDigest(null); setDigests([]); setRuns([]); setTraceRun(null); setTrace([]); setNotices([]); setTab("today");}
    catch (e) {setError((e as Error).message);}
  }
  function download() {
    if (!digest?.markdown) return;
    const url = URL.createObjectURL(new Blob([digest.markdown], {type: "text/markdown;charset=utf-8"}));
    const a = document.createElement("a"); a.href = url; a.download = `ai-digest-${digest.digest_date}.md`; a.click(); URL.revokeObjectURL(url);
  }
  async function resend() {
    if (!digest) return;
    setBusy(true);
    try {await api(`/digests/${digest.id}/send`, {method: "POST"}); setDigest(await api<Digest>(`/digests/${digest.id}`)); setMessage("已按当前订阅检查推送队列；已送达和待核查的投递不会重复发送。");}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  const activeRun = runs.find(r => ["queued", "running"].includes(r.status));
  const unread = notices.filter(n => !n.read_at).length;
  const patch = <K extends keyof Prefs>(key: K, value: Prefs[K]) => setPrefs(p => p ? {...p, [key]: value} : p);

  if (!ready) return <main className="loading"><Sun className="spin"/><p>正在开启你的 AI 视野…</p></main>;
  if (!user) return <main className="auth-layout">
    <section className="auth-story"><a className="brand"><span className="brand-symbol"><Sun size={26}/></span>daybreak<span className="brand-dot">.</span></a>
      <span className="eyebrow">YOUR SIGNAL IN THE AI NOISE</span><h1>世界正在更新。<br/>你的早报，<br/><em>也该如此。</em></h1>
      <p>让一个自主思考、会查证来源的 Agent，<br/>为你整理真正值得读的 AI 新闻。</p>
      <div className="orbit-art" aria-hidden="true"><div className="orbit one"/><div className="orbit two"/><div className="orbit three"/><div className="orbit-core"><Sun size={56}/></div><span className="orbit-label top"><Globe2 size={14}/> 真实新闻源</span><span className="orbit-label bottom"><Workflow size={14}/> 可追溯的每一步</span></div>
      <footer>LANGGRAPH × DEEPSEEK <span>BUILT FOR CLARITY</span></footer>
    </section>
    <section className="auth-form-wrap"><div className="auth-form"><span className="mini-label">DAILY AI NEWS AGENT</span><h2>{register ? "开始你的每日洞察" : "欢迎回来"}</h2><p>少一点信息噪声，多一点值得关注。</p>
      <form onSubmit={authenticate}><label>邮箱地址<input type="email" required autoComplete="email" placeholder="you@example.com" value={email} onChange={e => setEmail(e.target.value)}/></label>
        <label>密码<input type="password" required minLength={10} maxLength={128} autoComplete={register ? "new-password" : "current-password"} placeholder="至少 10 位字符" value={password} onChange={e => setPassword(e.target.value)}/></label>
        {error && <div role="alert" className="error-box">{error}</div>}
        <button className="button primary wide" disabled={busy}>{busy ? <Loader2 className="spin" size={18}/> : <>{register ? "创建账户" : "进入工作台"}<ArrowRight size={18}/></>}</button>
      </form><p className="auth-switch">{register ? "已有账户？" : "第一次来到这里？"}<button onClick={() => {setRegister(!register); setError("");}}>{register ? "登录" : "创建账户"}</button></p>
      <div className="auth-safety"><ShieldCheck size={16}/><span>独立工作区 · 安全会话 · 来源可验证</span></div>
    </div></section>
  </main>;

  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="/"><span className="brand-symbol"><Sun size={24}/></span>daybreak<span className="brand-dot">.</span></a>
      <div className="workspace-tag"><span className="avatar small">P</span><div>Personal workspace<small>你的 AI 新闻空间</small></div><ChevronRight size={14}/></div>
      <span className="nav-caption">WORKSPACE</span><nav>{nav.map(({id, label, icon: Icon}) => <button key={id} onClick={() => setTab(id)} className={tab === id ? "active" : ""}><Icon size={19}/>{label}{id === "trace" && activeRun && <span className="live-dot"/>}</button>)}</nav>
      <div className="sidebar-note"><span className="note-icon"><Sparkles size={18}/></span><strong>不止摘要，更有依据。</strong><p>每条新闻保留原始来源，<br/>每次决策留下执行轨迹。</p><button onClick={() => setTab("trace")}>了解 Agent 的工作 <ArrowRight size={13}/></button></div>
      <div className="sidebar-bottom"><div className="engine-status"><span className={`live-dot ${health?.model_configured ? "" : "muted"}`}/>{health?.model_configured ? "DeepSeek 已连接配置" : "等待模型配置"}</div><div className="profile"><span className="avatar">{user.email[0].toUpperCase()}</span><div><strong>我的工作区</strong><small title={user.email}>{user.email}</small></div><button aria-label="退出登录" title="退出登录" onClick={logout}><LogOut size={17}/></button></div></div>
    </aside>
    <div className="main-area"><header className="topbar"><div><span className="breadcrumb">Workspace</span><ChevronRight size={14}/><strong>{nav.find(n => n.id === tab)?.label}</strong></div><div className="topbar-actions"><span className="private-label"><ShieldCheck size={14}/> 私有工作区</span><button aria-label="通知" className="icon-button notification-button" onClick={() => setShowNotices(!showNotices)}><Bell size={19}/>{unread > 0 && <span className="notification-count">{unread}</span>}</button><button className="icon-button mobile-logout" aria-label="退出登录" onClick={logout}><LogOut size={17}/></button></div>
      {showNotices && <div className="notification-panel"><div className="panel-heading"><strong>站内通知</strong><button className="icon-button" aria-label="关闭通知" onClick={() => setShowNotices(false)}><X size={16}/></button></div>{notices.length ? notices.map(n => <button key={n.id} className={`notice ${!n.read_at ? "unread" : ""}`} onClick={async () => {try {await api(`/notifications/${n.id}/read`, {method: "POST"}); await openDigest(n.digest_id); await refresh();} catch(e) {setError((e as Error).message);}}}><FileText size={18}/><span><strong>{n.title}</strong><small>{stamp(n.created_at)}</small></span></button>) : <p className="subtle">日报送达后，通知会出现在这里。</p>}</div>}
    </header>
    <main className="content">
      {error && <div role="alert" className="error-box banner">{error}<button aria-label="关闭错误提示" onClick={() => setError("")}><X size={16}/></button></div>}
      {message && <div role="status" className="success-box"><CheckCircle2 size={17}/>{message}</div>}
      <div className="page-heading"><div><span className="eyebrow">{tab === "today" ? "A LITTLE LESS NOISE. A LOT MORE SIGNAL." : nav.find(n => n.id === tab)?.small.toUpperCase()}</span><h1>{tab === "today" ? "今天的 AI，值得你知道。" : tab === "preferences" ? "让信息，与你有关。" : tab === "history" ? "每一天，都有迹可循。" : "看见 Agent 的每一步。"}</h1><p>{tab === "today" ? "你的专属 AI 新闻简报。从真实来源出发，让每一条洞察都有依据。" : tab === "preferences" ? "选择关注的主题与信源，安排每天的阅读时刻。" : tab === "history" ? "回看已生成的日报、原始来源和推送记录。" : "模型自主决定工具顺序；这里展示真实调用与结果，不展示私密思维链。"}</p></div>
        <button className="button primary" disabled={busy || !!activeRun || !health?.model_configured} onClick={generate}>{activeRun ? <Loader2 size={17} className="spin"/> : <Sparkles size={17}/>} {activeRun ? "Agent 工作中" : "生成今日日报"}</button>
      </div>

      {tab === "today" && <>
        <div className="metric-grid"><Metric icon={<BookOpen/>} label="已生成日报" value={String(digests.length)} suffix={digests.length === 30 ? "篇 · 最近 30 篇" : "篇"}/><Metric icon={<Globe2/>} label="订阅新闻源" value={String(prefs?.sources.length || 0)} suffix="个可信入口"/><Metric icon={<Clock3/>} label="每日送达时间" value={prefs?.delivery_time || "—"} suffix={prefs?.schedule_enabled ? prefs.timezone : "自动订阅未开启"}/><Metric icon={<Workflow/>} label="最近任务" value={runs.length ? statusNames[runs[0].status] || runs[0].status : "待开始"} suffix={runs[0]?.model || "让 Agent 为你工作"}/></div>
        <div className="dashboard-grid"><section className="digest-section"><div className="section-heading"><h2><FileText size={19}/> {digest ? "你的 AI 简报" : "今日简报"}</h2><span className="mini-label">DAILY BRIEFING</span></div>
          {digest ? <article className="digest-paper"><div className="paper-meta"><span className="edition">EDITION / {digest.digest_date.replaceAll("-", ".")}</span><button className="text-button" onClick={download}><ArrowDownToLine size={14}/> 导出 Markdown</button></div><h2>{digest.title}</h2><div className="paper-byline"><span><Sparkles size={13}/> DeepSeek 整理</span><span>·</span><span>{digest.items?.length} 条来源可核查的新闻</span></div>
            {digest.items?.map((item, i) => <section className="news-item" key={item.article_id}><div className="news-number">{String(i + 1).padStart(2, "0")}</div><div className="news-content"><div className="news-source"><span>{sourceNames[item.source] || item.source}</span><time>{stamp(item.published_at)}</time></div><h3><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}<ExternalLink size={14}/></a></h3><p>{item.summary}</p><details className="evidence"><summary><ShieldCheck size={13}/> 查看原文证据与来源指纹 <ChevronRight size={13}/></summary><blockquote>{item.evidence_quote}</blockquote><small>抓取于 {stamp(item.fetched_at)}</small><code>SHA-256 / {item.sha256}</code><a href={item.url} target="_blank" rel="noopener noreferrer">阅读完整原文 <ExternalLink size={12}/></a></details></div></section>)}
            <div className="paper-footer"><span><ShieldCheck size={15}/> 引用来自本次真实抓取；AI 摘要仍需结合原文判断。</span><button className="text-button" onClick={() => {setTraceRun(runs.find(r => r.id === digest.run_id) || {id: digest.run_id, status: "completed", trigger: "manual", created_at: digest.created_at, model: health?.model || ""}); setTab("trace");}}>查看生成轨迹 <ArrowRight size={13}/></button></div>
          </article> : <div className="card"><Empty icon={<Sun size={36}/>} title="一份更清晰的 AI 视野，从这里开始" text="配置感兴趣的主题，点击生成。Agent 将自主查找、阅读并核验新闻来源。"><button className="button secondary" onClick={() => setTab("preferences")}>设置我的订阅 <ArrowRight size={15}/></button></Empty></div>}
        </section><aside className="right-column"><div className="card schedule-card"><div className="section-heading"><h3>阅读节奏</h3><Clock3 size={17}/></div><div className="schedule-time">{prefs?.delivery_time || "08:00"}<span>{prefs?.timezone}</span></div><div className="schedule-state"><span className={`live-dot ${prefs?.schedule_enabled ? "" : "muted"}`}/>{prefs?.schedule_enabled ? "每日自动生成" : "当前使用手动生成"}</div><div className="divider"/><div className="channel"><Bell size={15}/> 站内推送 <span>{prefs?.in_app_enabled ? "已开启" : "已关闭"}</span></div><div className="channel"><Mail size={15}/> 邮件推送 <span>{prefs?.email_enabled ? health?.smtp_configured ? "已开启" : "待配置 SMTP" : "已关闭"}</span></div><button className="button secondary wide" onClick={() => setTab("preferences")}>管理订阅 <Settings2 size={14}/></button></div>
          <div className="card sources-card"><div className="section-heading"><h3>你的新闻源</h3><Globe2 size={17}/></div>{prefs?.sources.map((s, i) => <div className="source-row" key={s}><span className={`source-logo logo-${i}`}>{sourceNames[s]?.[0]}</span><span>{sourceNames[s]}</span><Check size={14}/></div>)}<p className="micro-copy">直连公开 RSS 与原文。不可用的来源会在 Trace 中如实记录。</p></div>
          <div className="trace-promo"><Code2 size={20}/><h3>摘要之外，过程透明。</h3><p>查看工具参数、来源抓取、耗时与模型 Token 用量。</p><button onClick={() => setTab("trace")}>打开 Agent Trace <ArrowRight size={14}/></button></div>
          {digest?.deliveries && <div className="card"><h3>本期送达记录</h3><button className="text-button" disabled={busy} onClick={resend}>检查 / 重试未送达推送 <RefreshCw size={12}/></button>{digest.deliveries.map(d => <div className="delivery-row" key={d.channel}><span>{d.channel === "email" ? "邮件" : "站内"}</span><Badge status={d.status}/>{d.error && <small>{d.error}</small>}</div>)}</div>}
        </aside></div>
      </>}

      {tab === "preferences" && prefs && <form onSubmit={savePreferences} className="preferences-grid"><section className="card settings-card"><div className="section-heading"><h2>01 <span>内容偏好</span></h2><BookOpen size={19}/></div><label>关注主题<span className="field-hint">用逗号分隔，最多 8 个主题</span><input value={topics} onChange={e => setTopics(e.target.value)} placeholder="AI, LLM, Agent, 多模态" required/></label><label>新闻来源<span className="field-hint">选择 Agent 可以检索的公开来源</span></label><div className="source-options">{Object.entries(sourceNames).map(([id, label]) => <label className={`source-option ${prefs.sources.includes(id) ? "selected" : ""}`} key={id}><input type="checkbox" checked={prefs.sources.includes(id)} onChange={e => patch("sources", e.target.checked ? [...prefs.sources, id] : prefs.sources.filter(s => s !== id))}/><Globe2 size={17}/><span>{label}</span><Check size={15}/></label>)}</div><div className="form-row"><label>日报语言<select value={prefs.language} onChange={e => patch("language", e.target.value as "zh" | "en")}><option value="zh">简体中文</option><option value="en">English</option></select></label><label>最多新闻数<select value={prefs.max_articles} onChange={e => patch("max_articles", Number(e.target.value))}>{[1,2,3,4,5,6,7,8].map(v => <option key={v} value={v}>{v} 条</option>)}</select></label></div><label>新闻时间范围<select value={prefs.lookback_days} onChange={e => patch("lookback_days", Number(e.target.value))}>{[1,2,3,7,14].map(v => <option key={v} value={v}>最近 {v} 天</option>)}</select></label></section>
        <section className="card settings-card"><div className="section-heading"><h2>02 <span>送达方式</span></h2><Radio size={19}/></div><Toggle label="每日自动生成" note="服务运行时，在指定时刻生成；当天错过后会补跑一次。" checked={prefs.schedule_enabled} onChange={v => patch("schedule_enabled", v)}/><div className="form-row"><label>每日时间<input type="time" value={prefs.delivery_time} onChange={e => patch("delivery_time", e.target.value)} required/></label><label>时区<select value={prefs.timezone} onChange={e => patch("timezone", e.target.value)}>{["Asia/Shanghai", "Asia/Tokyo", "Asia/Singapore", "Europe/London", "America/New_York", "America/Los_Angeles", "UTC"].map(v => <option key={v}>{v}</option>)}</select></label></div><div className="divider"/><Toggle label="站内通知" note="日报完成后，在工作区收到通知。" checked={prefs.in_app_enabled} onChange={v => patch("in_app_enabled", v)}/><Toggle label="邮件推送" note={`仅发送至当前登录账户：${user.email}`} checked={prefs.email_enabled} onChange={v => patch("email_enabled", v)}/>{!health?.smtp_configured && <div className="info-note"><Mail size={16}/><span>尚未配置 SMTP。启用后会记录发送失败，不会显示虚假的送达状态。</span></div>}<div className="settings-submit"><button className="button primary" disabled={busy || !prefs.sources.length}>{busy ? <Loader2 className="spin" size={16}/> : <Check size={16}/>}保存订阅配置</button></div></section></form>}

      {tab === "history" && <section className="card archive-card"><div className="section-heading"><h2>日报档案</h2><span className="mini-label">YOUR KNOWLEDGE, COMPOUNDING.</span></div>{archive.length ? <><div className="archive-header"><span>日报 / 标题</span><span>生成时间</span><span/></div>{archive.map(d => <button key={d.id} className="archive-row" onClick={() => openDigest(d.id)}><span className="archive-date"><FileText size={19}/><span><small>{d.digest_date}</small><strong>{d.title}</strong></span></span><time>{stamp(d.created_at)}</time><ArrowRight size={17}/></button>)}</> : <Empty icon={<History size={32}/>} title="你的第一份日报，即将归档" text="所有生成的日报会保存在这里，随时回看和导出。"/>}<div className="pagination"><button className="button secondary" disabled={archivePage === 0} onClick={() => setArchivePage(p => p - 1)}>上一页</button><span>第 {archivePage + 1} 页</span><button className="button secondary" disabled={archive.length < 12} onClick={() => setArchivePage(p => p + 1)}>下一页</button></div></section>}

      {tab === "trace" && <div className="trace-layout"><section className="card run-list"><div className="section-heading"><h3>执行记录</h3><button aria-label="刷新任务" className="icon-button" onClick={() => refresh().catch(e => setError(e.message))}><RefreshCw size={15}/></button></div>{runs.length ? runs.map(r => <button key={r.id} onClick={() => {setTraceRun(r); setTrace([]);}} className={`run-item ${traceRun?.id === r.id ? "selected" : ""}`}><span><Terminal size={16}/><strong>{r.trigger === "schedule" ? "定时日报" : "手动日报"}</strong><Badge status={r.status}/></span><small>{stamp(r.created_at)} · {r.id.slice(0,8)}</small></button>) : <p className="subtle">尚无执行记录。</p>}</section><section className="card trace-detail">{traceRun ? <><div className="trace-detail-header"><div><span className="mini-label">EXECUTION TRACE</span><h2>{traceRun.model}<Badge status={traceRun.status}/></h2><code>{traceRun.id}</code></div><span className="trace-count">{trace.filter(t => t.kind === "tool").length} 次工具调用</span></div>{traceRun.error && <div className="error-box">{traceRun.error}</div>}<div className="timeline">{trace.map((event, i) => <TraceEvent key={event.id} event={event} index={i}/>)}{["queued", "running"].includes(traceRun.status) && <div className="trace-wait"><Loader2 size={16} className="spin"/> 等待下一个真实执行事件…</div>}</div>{traceRun.final_text && <div className="agent-final"><span className="mini-label">AGENT RESPONSE</span><p>{traceRun.final_text}</p></div>}{digests.some(d => d.run_id === traceRun.id) && <button className="button primary" onClick={() => openDigest(digests.find(d => d.run_id === traceRun.id)!.id)}>阅读本次日报 <ArrowRight size={16}/></button>}</> : <Empty icon={<Workflow size={34}/>} title="透明的过程，从一次执行开始" text="生成日报后，这里会显示模型与工具的实际交互。没有预填轨迹或模拟数据。"/>}</section></div>}
      <footer className="page-footer"><span><Sun size={13}/> DAYBREAK · DAILY AI NEWS AGENT</span><span>由真实来源驱动，为清晰判断而设计。</span></footer>
    </main></div>
  </div>;
}

function Metric({icon, label, value, suffix}: {icon: ReactNode; label: string; value: string; suffix: string}) {
  return <div className="metric card"><div className="metric-top"><span>{label}</span>{icon}</div><div className="metric-value">{value}</div><small>{suffix}</small></div>;
}
function Toggle({label, note, checked, onChange}: {label: string; note: string; checked: boolean; onChange: (v: boolean) => void}) {
  return <label className="toggle-row"><span><strong>{label}</strong><small>{note}</small></span><input className="switch" type="checkbox" role="switch" checked={checked} onChange={e => onChange(e.target.checked)}/></label>;
}
function TraceEvent({event, index}: {event: Trace; index: number}) {
  const d = event.data;
  const isTool = event.kind === "tool";
  const calls = (d.tool_calls || []) as {function: {name: string}}[];
  const title = isTool ? String(d.name) : event.kind === "model" ? `模型调用 · 第 ${d.turn} 轮` : event.kind === "error" ? "执行错误" : `任务${statusNames[String(d.status)] || String(d.status)}`;
  const usage = d.usage as {total_tokens?: number} | undefined;
  return <details className={`trace-event ${isTool && !d.ok ? "tool-error" : ""}`}><summary><span className="timeline-icon">{isTool ? <Terminal size={15}/> : event.kind === "model" ? <Sparkles size={15}/> : <Play size={13}/>}</span><div className="event-summary"><span className="event-title"><small>{String(index + 1).padStart(2,"0")}</small><strong>{title}</strong>{isTool && <span className={d.ok ? "ok-text" : "bad-text"}>{d.ok ? "成功" : "已拦截 / 失败"}</span>}</span><span className="event-meta">{stamp(event.created_at)}{d.duration_ms !== undefined ? ` · ${Number(d.duration_ms).toLocaleString()} ms` : ""}{usage?.total_tokens ? ` · ${usage.total_tokens} tokens` : ""}{calls.length ? ` · ${calls.map(c => c.function.name).join(" → ")}` : ""}</span></div><ChevronRight size={15}/></summary><pre>{JSON.stringify(d, null, 2)}</pre></details>;
}
