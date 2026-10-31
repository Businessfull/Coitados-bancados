const ALARM = "deusold-highscore-poll";
async function cfg() {
  return chrome.storage.local.get({apiUrl: "https://coitados-bancados.onrender.com", ingestKey: "", enabled: false});
}
chrome.runtime.onInstalled.addListener(async () => {
  const c = await cfg();
  if (c.enabled) chrome.alarms.create(ALARM, {periodInMinutes: 5});
});
chrome.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name !== ALARM) return;
  const c = await cfg();
  if (!c.enabled) return;
  const tabs = await chrome.tabs.query({url: ["https://www.deusold.com/ranking*", "https://deusold.com/ranking*"]});
  if (tabs.length) await chrome.tabs.reload(tabs[0].id);
  else await chrome.tabs.create({url: "https://www.deusold.com/ranking", active: false});
});
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg?.type === "SEND_HIGHSCORE") {
    (async () => {
      const c = await cfg();
      if (!c.enabled) throw Error("Coletor desativado.");
      if (!c.ingestKey) throw Error("Configure INGEST_KEY no Render e nesta extensão.");
      if (!Array.isArray(msg.players) || !msg.players.length) throw Error("Nenhum personagem reconhecido.");
      const response = await fetch(c.apiUrl.replace(/\/+$/, "") + "/api/ingest", {
        method: "POST",
        headers: {"Content-Type": "application/json", "x-ingest-key": c.ingestKey},
        body: JSON.stringify({players: msg.players, deaths: []})
      });
      const body = await response.text();
      if (!response.ok) throw Error("API HTTP " + response.status + ": " + body.slice(0, 300));
      await chrome.storage.local.set({lastSent: new Date().toISOString(), lastCount: msg.players.length, lastError: ""});
      reply({ok: true, count: msg.players.length});
    })().catch(async error => {
      await chrome.storage.local.set({lastError: String(error), lastAttempt: new Date().toISOString()});
      reply({ok: false, error: String(error)});
    });
    return true;
  }
  if (msg?.type === "SET_CONFIG") {
    (async () => {
      const config = {apiUrl: String(msg.apiUrl || "").trim(), ingestKey: String(msg.ingestKey || "").trim(), enabled: !!msg.enabled};
      await chrome.storage.local.set(config);
      await chrome.alarms.clear(ALARM);
      if (config.enabled) chrome.alarms.create(ALARM, {periodInMinutes: 5});
      reply({ok: true});
    })();
    return true;
  }
});