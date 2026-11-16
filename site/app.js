const root = document.documentElement;

function start() {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const animated = () => root.classList.contains("js");

  const darkQuery = matchMedia("(prefers-color-scheme: dark)");
  const toggle = $("#theme-toggle");
  const theme = () => root.dataset.theme || (darkQuery.matches ? "dark" : "light");
  function paintToggle() {
    const dark = theme() === "dark";
    $(".icon", toggle).textContent = dark ? "☀️" : "🌙";
    $(".label", toggle).textContent = dark ? "Cahier" : "Tableau";
    toggle.setAttribute("aria-label", dark ? "Passer au thème cahier (clair)" : "Passer au thème tableau (sombre)");
  }
  toggle.addEventListener("click", () => {
    const next = theme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    paintToggle();
  });
  if (darkQuery.addEventListener) darkQuery.addEventListener("change", paintToggle);
  else darkQuery.addListener(paintToggle);
  paintToggle();

  function flash(btn, text, ok) {
    const label = btn.dataset.label || (btn.dataset.label = btn.textContent);
    btn.textContent = text;
    btn.classList.toggle("ok", ok);
    clearTimeout(btn._t);
    btn._t = setTimeout(() => { btn.textContent = label; btn.classList.remove("ok"); }, 2000);
  }
  $$(".code").forEach((fig) => {
    const btn = $(".copy", fig);
    const code = $("code", fig);
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(code.innerText);
        flash(btn, "Copié ✓", true);
      } catch (e) {
        const range = document.createRange();
        range.selectNodeContents(code);
        const sel = getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        flash(btn, "Sélectionné, à copier", false);
      }
    });
  });

  function onVisible(el, fn) {
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { io.disconnect(); fn(el); }
    }, { rootMargin: "0px 0px -18% 0px" });
    io.observe(el);
  }

  async function ringPhone() {
    const phone = $(".phone");
    const clock = $(".lock-time");
    clock.textContent = "06:59";
    $(".hero").classList.add("is-on");
    await sleep(1500);
    clock.textContent = "07:00";
    clock.classList.add("tick");
    await sleep(380);
    phone.classList.add("ring");
  }

  const chat = $("#chat-body");
  const replay = $("#replay");
  const steps = $$(".steps li");
  let run = 0;

  function setStep(n) {
    steps.forEach((s, i) => { s.classList.toggle("done", i < n); s.classList.toggle("active", i === n); });
  }
  function resetChat() {
    $$("[data-seq], .reminders li", chat).forEach((el) => el.classList.remove("shown"));
    $$(".date", chat).forEach((el) => el.classList.remove("lit"));
    $$(".typing", chat).forEach((el) => el.remove());
    replay.hidden = true;
    setStep(-1);
  }
  async function playChat() {
    const me = ++run;
    const wait = async (ms) => { await sleep(ms); if (me !== run) throw new Error("replaced"); };
    const scroll = () => { chat.scrollTop = chat.scrollHeight; };
    const show = (el) => { el.classList.add("shown"); scroll(); };
    const typing = async (ms) => {
      const t = document.createElement("div");
      t.className = "bubble typing";
      t.setAttribute("aria-hidden", "true");
      t.innerHTML = "<span></span><span></span><span></span>";
      chat.append(t);
      scroll();
      try { await wait(ms); } finally { t.remove(); }
    };
    const [sep1, mot, agent, ...days] = $$("[data-seq]", chat);
    resetChat();
    try {
      setStep(0);
      show(sep1);
      await wait(1100);
      await typing(900);
      show(mot);
      setStep(1);
      await wait(1000);
      for (const d of $$(".date", mot)) { d.classList.add("lit"); await wait(700); }
      setStep(2);
      await typing(1300);
      show(agent);
      for (const li of $$(".reminders li", agent)) { await wait(420); li.classList.add("shown"); scroll(); }
      await wait(1300);
      setStep(3);
      for (let i = 0; i < days.length; i += 2) {
        show(days[i]);
        await wait(500);
        await typing(700);
        show(days[i + 1]);
        await wait(1100);
      }
      setStep(4);
      replay.hidden = false;
    } catch (e) {
      if (e.message !== "replaced") throw e;
    }
  }

  if (animated()) {
    $$(".reveal").forEach((el) => onVisible(el, (x) => x.classList.add("is-visible")));
    onVisible($(".fridge"), (x) => x.classList.add("is-visible"));
    ringPhone();
    onVisible($(".chat"), playChat);
    replay.addEventListener("click", playChat);
  }
}

// Any failure falls back to the static page instead of leaving hidden sections hidden.
try {
  start();
} catch (e) {
  root.classList.replace("js", "static");
  console.error(e);
} finally {
  window.__appReady = true;
}
