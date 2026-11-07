// Standalone full-page language navigation; no dependency on the MyST client router.
export function languagePath(pathname, base, language) {
  const prefix = base ? base + '/' : '/';
  if (!pathname.startsWith(prefix)) throw new Error('Path is outside the project');
  let relative = pathname.slice(prefix.length).replace(/^en(?:\/|$)/, '');
  return prefix + (language === 'en' ? 'en/' : '') + relative;
}

if (typeof document !== 'undefined') {
  const start = async () => {
    const metadata = document.querySelector('meta[name="tutorial-language"]');
    if (!metadata) return;
    const language = metadata.content;
    const base = document.querySelector('meta[name="tutorial-base"]').content;
    const mapping = await fetch(base + '/language-map.json').then(r => {
      if (!r.ok) throw new Error('Language map unavailable');
      return r.json();
    });
    document.documentElement.lang = language;
    const nav = document.createElement('nav');
    nav.id = 'tutorial-language-switch';
    nav.setAttribute('aria-label', 'Language / 언어');
    nav.style.cssText = 'position:fixed;bottom:16px;right:16px;z-index:1000;padding:8px 12px;border:1px solid #888;border-radius:8px;background:Canvas;color:CanvasText;box-shadow:0 2px 8px #0003;font:14px system-ui;display:flex;gap:12px';
    const links = ['ko', 'en'].map(lang => {
      const a = document.createElement('a');
      a.textContent = lang === 'ko' ? '한국어' : 'English';
      a.hreflang = lang;
      a.lang = lang;
      a.style.color = 'inherit';
      if (lang === language) a.setAttribute('aria-current', 'page');
      a.addEventListener('click', event => {
        event.preventDefault();
        // A full navigation loads the other language's config and search index.
        location.assign(a.href);
      });
      nav.append(a);
      return a;
    });
    const update = () => {
      const prefix = base ? base + '/' : '/';
      const route = location.pathname.slice(prefix.length).replace(/^en(?:\/|$)/,'')
        .replace(/(?:^|\/)index\.html$/,'').replace(/\/$/,'') || 'index';
      const hash = decodeURIComponent(location.hash.slice(1));
      const translated = mapping.anchors[route]?.[language]?.[hash];
      links.forEach((a, i) => {
        const lang = i === 0 ? 'ko' : 'en';
        const fragment = lang === language ? hash : translated;
        a.href = languagePath(location.pathname, base, lang) + location.search + (fragment ? '#' + encodeURIComponent(fragment) : '');
      });
    };
    update();
    document.body.append(nav);
    new MutationObserver(update).observe(document.body, {childList:true,subtree:true});
    addEventListener('popstate', update);
    addEventListener('hashchange', update);
  };
  const run = () => setTimeout(() => start().catch(console.error), 100);
  if (document.readyState === 'complete') run(); else addEventListener('load', run, {once:true});
}
