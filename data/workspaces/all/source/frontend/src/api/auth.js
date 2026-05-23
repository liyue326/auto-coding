/** API 客户端 — Vue 3，与 api_contract 一致 */
const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function register(data) {
  const res = await fetch(`${BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("注册失败");
  return res.json();
}

export async function login(data) {
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("登录失败");
  return res.json();
}
