(async () => {
  const norm = s => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  const num = s => { const v = String(s || "").replace(/[^\d]/g, ""); return v ? Number(v) : null; };
  const roster = await fetch(chrome.runtime.getURL("roster.json")).then(r => r.json());
  const allowed = new Set(roster.map(norm));

  function parse(doc) {
    let best = [];
    for (const table of doc.querySelectorAll("table")) {
      const trs = [...table.querySelectorAll("tr")];
      const hr = trs.find(tr => tr.querySelector("th"));
      const headers = hr ? [...hr.querySelectorAll("th")].map(x => norm(x.innerText)) : [];
      const idx = (re, fallback) => { const i = headers.findIndex(h => re.test(h)); return i >= 0 ? i : fallback; };
      const ni = idx(/name|character|player|personagem|nome/, 1);
      const li = idx(/level|lvl/, 4);
      const xi = idx(/experience|exp|xp|experiencia/, -1);
      const ri = idx(/rank|position|posicao/, 0);
      const rows = [];
      for (const tr of trs) {
        const cells = [...tr.querySelectorAll("td")].map(td => td.innerText.replace(/\s+/g, " ").trim());
        if (cells.length < 4) continue;
        const name = cells[ni];
        if (!name || !allowed.has(norm(name))) continue;
        const level = num(cells[li]);
        if (!level || level > 500) continue;
        let xp = xi >= 0 ? num(cells[xi]) : null;
        if (xp === null) {
          const candidates = cells.map(num).filter(v => v !== null && v > 1000 && v !== level);
          if (candidates.length) xp = candidates[candidates.length - 1];
        }
        rows.push({name, level, total_xp: xp, rank: num(cells[ri]) || 0, updated_at: new Date().toISOString()});
      }
      if (rows.length > best.length) best = rows;
    }
    return best;
  }

  try {
    const all = new Map();
    let empty = 0;
    for (let page = 1; page <= 30; page++) {
      let doc;
      if (page === 1) doc = document;
      else {
        const url = new URL(location.href);
        url.searchParams.set("page", String(page));
        const response = await fetch(url.toString(), {credentials: "include"});
        if (!response.ok) throw Error("Highscore página " + page + ": HTTP " + response.status);
        doc = new DOMParser().parseFromString(await response.text(), "text/html");
      }
      const rows = parse(doc);
      empty = rows.length ? 0 : empty + 1;
      for (const p of rows) all.set(norm(p.name), p);
      if (empty >= 3) break;
    }
    const players = [...all.values()];
    if (!players.length) throw Error("Nenhum dos personagens monitorados apareceu. A estrutura da tabela pode ter mudado.");
    chrome.runtime.sendMessage({type: "SEND_HIGHSCORE", players}, result => {
      if (chrome.runtime.lastError) console.error(chrome.runtime.lastError.message);
      else if (!result?.ok) console.error("Coitados Bancados:", result?.error);
      else console.info("Coitados Bancados: " + result.count + " personagens enviados.");
    });
  } catch (e) {
    console.error("Coitados Bancados — falha na coleta:", e);
  }
})();