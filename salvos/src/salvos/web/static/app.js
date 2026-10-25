"use strict";

const TODOS = "__todos__";
const REVISAR = "__revisar__";
const OUTROS = "Outros";
const SEM_CLASSIFICACAO = "Sem classificação";

const estado = { filtro: TODOS, busca: "", nichos: [], posts: [], aberto: null };
const $ = (id) => document.getElementById(id);

async function api(caminho, opcoes = {}) {
  const resp = await fetch(caminho, {
    headers: { "Content-Type": "application/json" },
    ...opcoes,
    body: opcoes.body ? JSON.stringify(opcoes.body) : undefined,
  });
  if (!resp.ok) {
    let msg = `Erro ${resp.status}`;
    try { msg = (await resp.json()).detail || msg; } catch (_) {}
    alert(msg);
    throw new Error(msg);
  }
  return resp.json();
}

const enc = encodeURIComponent;
const midia = (post, arquivo) => `/midia/${enc(post.shortcode)}/${enc(arquivo)}`;
const ehVideo = (arquivo) => arquivo && arquivo.endsWith(".mp4");
const dataCurta = (iso) => (iso || "").slice(0, 10).split("-").reverse().join("/");

function el(tag, props = {}, ...filhos) {
  const n = document.createElement(tag);
  Object.assign(n, props);
  for (const f of filhos) if (f != null) n.append(f);
  return n;
}

// --- barra lateral --------------------------------------------------------

async function carregarNichos() {
  estado.nichos = await api("/api/nichos");
  const revisar = (await api("/api/posts?revisar=true")).length;
  const total = estado.nichos.reduce((s, n) => s + n.total, 0);
  const nav = $("lista-nichos");
  nav.replaceChildren();
  const item = (chave, rotulo, num, alerta = false) => {
    const b = el("button", { type: "button", className: "item-nicho" + (estado.filtro === chave ? " ativo" : "") },
      el("span", { textContent: rotulo }),
      el("span", { className: "num" + (alerta ? " alerta" : ""), textContent: String(num) }));
    b.addEventListener("click", () => { selecionar(chave); fecharLateral(); });
    nav.append(b);
  };
  item(TODOS, "Todos", total);
  if (revisar) item(REVISAR, "Revisar", revisar, true);
  nav.append(el("div", { className: "separador" }));
  for (const n of estado.nichos) item(n.nome, n.nome, n.total);
}

function selecionar(chave) {
  estado.filtro = chave;
  carregarNichos();
  carregarPosts();
}

// --- grade -----------------------------------------------------------------

async function carregarPosts() {
  const params = new URLSearchParams();
  if (estado.filtro === REVISAR) params.set("revisar", "true");
  else if (estado.filtro !== TODOS) params.set("nicho", estado.filtro);
  if (estado.busca) params.set("q", estado.busca);
  estado.posts = await api(`/api/posts?${params}`);
  desenharTopo();
  desenharGrade();
}

function desenharTopo() {
  const f = estado.filtro;
  const ehNicho = f !== TODOS && f !== REVISAR;
  $("titulo").textContent = f === TODOS ? "Todos" : f === REVISAR ? "Revisar" : f;
  $("total").textContent = `${estado.posts.length} ${estado.posts.length === 1 ? "post" : "posts"}`;
  $("exportar").hidden = !ehNicho;
  $("menu-nicho").hidden = !ehNicho || f === OUTROS || f === SEM_CLASSIFICACAO;
  if (ehNicho) {
    $("exportar-md").href = `/api/exportar/${enc(f)}.md`;
    $("exportar-zip").href = `/api/exportar/${enc(f)}.zip`;
  }
}

function desenharGrade() {
  const grade = $("grade");
  grade.replaceChildren();
  $("vazio").hidden = estado.posts.length > 0;
  for (const p of estado.posts) {
    const capa = el("div", { className: "card-capa" });
    if (p.capa) {
      capa.append(ehVideo(p.capa)
        ? el("video", { src: midia(p, p.capa) + "#t=0.5", muted: true, preload: "metadata" })
        : el("img", { src: midia(p, p.capa), loading: "lazy", alt: "" }));
    }
    const icone = p.tipo === "video" ? "▶ vídeo" : p.tipo === "carrossel" ? `▦ ${p.arquivos.length}` : null;
    if (icone) capa.append(el("span", { className: "card-icone", textContent: icone }));
    if (p.revisar) capa.append(el("span", { className: "card-selo", textContent: "revisar" }));
    const card = el("button", { type: "button", className: "card" }, capa,
      el("div", { className: "card-corpo" },
        el("div", { className: "card-autor", textContent: "@" + p.autor }),
        el("div", { className: "card-data", textContent: dataCurta(p.data) + (p.nicho && estado.filtro === TODOS ? " · " + p.nicho : "") }),
        el("p", { className: "card-legenda", textContent: p.legenda || "(sem legenda)" })));
    card.addEventListener("click", () => abrirDetalhe(p.shortcode));
    grade.append(card);
  }
}

// --- detalhe ---------------------------------------------------------------

async function abrirDetalhe(shortcode) {
  const p = await api(`/api/posts/${enc(shortcode)}`);
  estado.aberto = p;
  const area = $("detalhe-midia");
  area.replaceChildren(...p.arquivos.map((a) => ehVideo(a)
    ? el("video", { src: midia(p, a), controls: true, preload: "metadata" })
    : el("img", { src: midia(p, a), alt: "" })));
  $("detalhe-autor").textContent = "@" + p.autor;
  $("detalhe-data").textContent = dataCurta(p.data);
  $("detalhe-link").href = p.url;
  $("detalhe-legenda").textContent = p.legenda || "(sem legenda)";
  $("bloco-transcricao").hidden = !p.transcricao;
  $("detalhe-transcricao").textContent = p.transcricao;
  const sel = $("detalhe-select");
  sel.replaceChildren();
  if (!p.nicho) sel.append(el("option", { value: "", textContent: SEM_CLASSIFICACAO, selected: true, disabled: true }));
  for (const n of estado.nichos) {
    if (n.nome === SEM_CLASSIFICACAO) continue;
    sel.append(el("option", { value: n.nome, textContent: n.nome, selected: n.nome === p.nicho }));
  }
  $("detalhe").showModal();
}

$("detalhe-select").addEventListener("change", async (e) => {
  await api(`/api/posts/${enc(estado.aberto.shortcode)}`, { method: "PATCH", body: { nicho: e.target.value } });
  await carregarNichos();
  await carregarPosts();
});

function fecharDetalhe() {
  const d = $("detalhe");
  d.querySelectorAll("video").forEach((v) => v.pause());
  d.close();
}
$("fechar").addEventListener("click", fecharDetalhe);
$("detalhe").addEventListener("click", (e) => { if (e.target === $("detalhe")) fecharDetalhe(); });
$("detalhe").addEventListener("close", () => $("detalhe").querySelectorAll("video").forEach((v) => v.pause()));

// --- ações de nicho ----------------------------------------------------------

$("novo-nicho").addEventListener("click", async () => {
  const nome = prompt("Nome do novo nicho:");
  if (!nome || !nome.trim()) return;
  const descricao = prompt("Descrição curta (ajuda a IA a classificar):") || "";
  await api("/api/nichos", { method: "POST", body: { nome: nome.trim(), descricao } });
  selecionar(nome.trim());
});

$("btn-renomear").addEventListener("click", async () => {
  const novo = prompt("Novo nome:", estado.filtro);
  if (!novo || novo.trim() === estado.filtro) return;
  await api(`/api/nichos/${enc(estado.filtro)}`, { method: "PATCH", body: { novo_nome: novo.trim() } });
  selecionar(novo.trim());
});

$("btn-juntar").addEventListener("click", async () => {
  const opcoes = estado.nichos.map((n) => n.nome).filter((n) => n !== estado.filtro && n !== SEM_CLASSIFICACAO);
  const destino = prompt(`Juntar "${estado.filtro}" em qual nicho?\n\n${opcoes.join("\n")}`);
  if (!destino) return;
  if (!opcoes.includes(destino.trim())) { alert("Nicho não encontrado."); return; }
  await api(`/api/nichos/${enc(estado.filtro)}`, { method: "PATCH", body: { juntar_em: destino.trim() } });
  selecionar(destino.trim());
});

$("btn-apagar").addEventListener("click", async () => {
  if (!confirm(`Apagar o nicho "${estado.filtro}"? Os posts dele vão para "${OUTROS}".`)) return;
  await api(`/api/nichos/${enc(estado.filtro)}`, { method: "DELETE" });
  selecionar(TODOS);
});

// --- busca e layout ---------------------------------------------------------

let espera;
$("busca").addEventListener("input", (e) => {
  clearTimeout(espera);
  espera = setTimeout(() => { estado.busca = e.target.value.trim(); carregarPosts(); }, 300);
});

const fecharLateral = () => $("lateral").classList.remove("aberta");
$("abrir-lateral").addEventListener("click", () => $("lateral").classList.toggle("aberta"));
document.addEventListener("click", (e) => {
  const exp = $("exportar");
  if (exp.open && !exp.contains(e.target)) exp.open = false;
});

carregarNichos();
carregarPosts();
