export type User = {id: string; email: string};
export type Health = {model_configured: boolean; smtp_configured: boolean; model: string};
export type WatchObject = {type: "model" | "company" | "project" | "topic"; name: string; aliases: string[]};
export type NewsSource = {id: string; name: string; feed: string; custom: boolean; enabled: boolean; checked_at: string | null; ok: boolean | number | null; error: string | null};
export type SearchPreview = {candidates: {title: string; source: string; source_name: string; published_at: string; url: string; matched_objects: string[]}[]; source_errors: {source: string; error: string}[]; unmatched_objects: string[]; retrieved_at: string; budget_seconds: number};
export type Prefs = {topics: string[]; sources: string[]; watch_objects: WatchObject[]; language: "zh" | "en"; max_articles: number; lookback_days: number; timezone: string; delivery_time: string; schedule_enabled: boolean; in_app_enabled: boolean; email_enabled: boolean};
export type Run = {id: string; status: string; trigger: string; created_at: string; finished_at?: string; error?: string; model: string; final_text?: string};
export type Item = {article_id: string; title: string; summary: string; evidence_quote: string; url: string; source: string; published_at: string; fetched_at: string; sha256: string};
export type Digest = {id: string; run_id: string; digest_date: string; title: string; created_at: string; items?: Item[]; markdown?: string; deliveries?: {channel: string; status: string; error?: string}[]};
export type Trace = {id: number; kind: string; created_at: string; data: Record<string, unknown>};
export type Notice = {id: string; digest_id: string; title: string; created_at: string; read_at?: string};
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {...init, credentials: "include", cache: "no-store", headers: {"Content-Type": "application/json", "X-Requested-With": "daily-ai-news", ...init.headers}});
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请检查输入格式后重试");
  return data as T;
}
