"use client";
import {useState} from "react";
import {api, type NewsSource, type Prefs, type WatchObject, type SearchPreview} from "./types";

const objectTypes = {model: "模型", company: "公司", project: "开源项目", topic: "技术话题"};
type Props = {prefs: Prefs; sources: NewsSource[]; reloadSources: () => Promise<void>; change: (p: Partial<Prefs>) => void};

export function SubscriptionExtras({prefs, sources, reloadSources, change}: Props) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState<number | null>(null);
  const [objectName, setObjectName] = useState("");
  const [aliases, setAliases] = useState("");
  const [kind, setKind] = useState<WatchObject["type"]>("model");

  async function action(fn: () => Promise<void>) {
    setWorking(true); setError("");
    try {await fn(); await reloadSources();} catch(e) {setError((e as Error).message);} finally {setWorking(false);}
  }
  function saveObject() {
    const clean = objectName.trim();
    const values = Array.from(new Set(aliases.split(/[,，\n]/).map(v => v.trim()).filter(Boolean)));
    if (!clean || clean.length > 60 || values.length > 6 || values.some(v => v.length > 60)) {setError("对象名称最多 60 字；别名最多 6 个，每个最多 60 字。"); return;}
    if (prefs.watch_objects.some((o, i) => i !== edit && o.name.toLowerCase() === clean.toLowerCase())) {setError("该关注对象已经存在。"); return;}
    const object: WatchObject = {type: kind, name: clean, aliases: values};
    change({watch_objects: edit === null ? [...prefs.watch_objects, object] : prefs.watch_objects.map((o, i) => i === edit ? object : o)});
    setObjectName(""); setAliases(""); setEdit(null); setError("");
  }
  return <div className="subscription-extras">
    {error && <p role="alert" className="error-box">{error}</p>}
    <details className="subscription-detail"><summary>更多新闻源与自定义 RSS <span>{sources.filter(s => s.custom).length} / 8 自定义</span></summary>
      <p className="field-hint">仅接受公开 HTTPS RSS/Atom。新增后需启用；自定义来源的启停和删除立即保存。</p>
      <div className="feed-list">{sources.map(s => <article className="feed-card" key={s.id}>
        <strong>{s.name}</strong><small className="feed-url">{s.feed}</small>
        <small>{s.checked_at ? new Date(s.checked_at).toLocaleString("zh-CN") : "尚未检测"} · {s.ok == null ? "未验证" : s.ok ? "检测成功" : "检测失败"}</small>
        {s.error && <p className="feed-error">{s.error}</p>}
        <div className="feed-actions">
          {s.custom ? <button type="button" className="button secondary" disabled={working} onClick={() => action(async () => {
            await api(`/sources/${s.id}`, {method: "PUT", body: JSON.stringify({enabled: !s.enabled})});
            change({sources: s.enabled ? prefs.sources.filter(v => v !== s.id) : Array.from(new Set([...prefs.sources, s.id]))});
          })}>{s.enabled ? "禁用" : "启用"} {s.name}</button> : <label className="feed-select"><input type="checkbox" aria-label={`订阅 ${s.name}`} disabled={(!s.enabled && !prefs.sources.includes(s.id)) || working} checked={prefs.sources.includes(s.id)} onChange={e => change({sources: e.target.checked ? [...prefs.sources, s.id] : prefs.sources.filter(v => v !== s.id)})}/>订阅</label>}
          <button type="button" className="text-button" disabled={working} onClick={() => action(async () => {await api(`/sources/${s.id}/check`, {method: "POST"});})}>检测 {s.name}</button>
          {s.custom && <button type="button" className="text-button" disabled={working} onClick={() => action(async () => {await api(`/sources/${s.id}`, {method: "DELETE"}); change({sources: prefs.sources.filter(v => v !== s.id)});})}>删除 {s.name}</button>}
        </div>
      </article>)}</div>
      <button type="button" className="button secondary" disabled={working || sources.filter(s => s.custom).length >= 8} onClick={() => setAdding(!adding)}>添加 RSS 新闻源</button>
      {adding && <div className="inline-editor"><label>来源名称<input maxLength={60} value={name} onChange={e => setName(e.target.value)}/></label><label>RSS/Atom URL<input type="url" maxLength={1500} placeholder="https://example.com/feed.xml" value={url} onChange={e => setUrl(e.target.value)}/></label>
        <button type="button" className="button primary" disabled={working || !name.trim() || !url.trim()} onClick={() => action(async () => {const source = await api<NewsSource>("/sources", {method: "POST", body: JSON.stringify({name, url})}); setName(""); setUrl(""); setAdding(false); if (!source.ok) setError(`来源已保存为禁用状态：${source.error}`);})}>{working ? "正在检测…" : "检测并添加"}</button>
      </div>}
    </details>
    <details className="subscription-detail"><summary>重点关注对象 <span>{prefs.watch_objects.length} / 8</span></summary><p className="field-hint">对象与普通主题共同检索；别名用逗号分隔。编辑后点击「保存订阅配置」。</p>
      {prefs.watch_objects.map((o, i) => <article className="focus-card" key={o.name}><strong>{o.name}</strong><small>{objectTypes[o.type]} · {o.aliases.join("、") || "无别名"}</small><div className="feed-actions"><button type="button" className="text-button" onClick={() => {setEdit(i); setObjectName(o.name); setAliases(o.aliases.join(", ")); setKind(o.type);}}>编辑 {o.name}</button><button type="button" className="text-button" onClick={() => {change({watch_objects: prefs.watch_objects.filter((_, j) => j !== i)}); setEdit(null); setObjectName(""); setAliases("");}}>删除 {o.name}</button></div></article>)}
      <div className="inline-editor"><label>对象类型<select value={kind} onChange={e => setKind(e.target.value as WatchObject["type"])}>{Object.entries(objectTypes).map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select></label><label>对象名称<input value={objectName} maxLength={60} placeholder="Qwen3-VL、DeepSeek、LangGraph、vLLM" onChange={e => setObjectName(e.target.value)}/></label><label>检索别名<input value={aliases} onChange={e => setAliases(e.target.value)} placeholder="例如：Qwen 3 VL, 通义千问"/></label><button type="button" className="button secondary" disabled={!objectName.trim() || (edit === null && prefs.watch_objects.length >= 8)} onClick={saveObject}>{edit === null ? "添加关注对象" : "更新关注对象"}</button>{edit !== null && <button type="button" className="text-button" onClick={() => {setEdit(null); setObjectName(""); setAliases("");}}>取消编辑</button>}</div>
    </details>
  </div>;
}

export function SearchResults({result, sources}: {result: SearchPreview; sources: NewsSource[]}) {
  return <section className="card preview-results" aria-label="测试检索结果"><h2>测试检索结果</h2><p className="field-hint">使用已保存配置 · 最多 5 条 · {result.budget_seconds} 秒预算 · 未生成日报或发送推送</p>
    {!result.candidates.length && <p>没有找到相关更新。可以调整已保存的主题、别名或时间范围。</p>}
    {result.candidates.map(c => <article className="preview-item" key={c.url}><a href={c.url} target="_blank" rel="noopener noreferrer">{c.title}</a><small>{c.source_name} · {new Date(c.published_at).toLocaleString("zh-CN")}</small><small className="feed-url">{c.url}</small><small>匹配对象：{c.matched_objects.join("、") || "普通关注主题"}</small></article>)}
    {!!result.unmatched_objects.length && <p>没有找到相关更新的对象：{result.unmatched_objects.join("、")}</p>}
    {!!result.source_errors.length && <div className="info-note"><div><strong>部分来源不可用 / 检索预算提示</strong>{result.source_errors.map(e => <p key={e.source}>{sources.find(s => s.id === e.source)?.name || e.source}：{e.error}</p>)}</div></div>}
    <p className="field-hint">检索于 {new Date(result.retrieved_at).toLocaleString("zh-CN")}。候选来自 RSS，生成日报时仍需抓取原文并校验引用。</p>
  </section>;
}
