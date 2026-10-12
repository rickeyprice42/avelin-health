(async () => {
  const options=window.__AVELIN_COLLECTOR__||{};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  if (!location.hostname.endsWith("fix-price.com")) {
    alert("Сначала откройте каталог Fix Price, затем нажмите закладку ещё раз.");
    return;
  }

  const currentHtml = document.documentElement.outerHTML;
  const countMatch = currentHtml.match(/productsCount\s*:\s*"?(\d+)/);
  const advertised = countMatch ? Number(countMatch[1]) : 0;
  const linkedPages = [...document.querySelectorAll('a[href*="page="]')]
    .map((link) => Number(new URL(link.href, location.href).searchParams.get("page")) || 1);
  const totalPages = Math.max(1, ...linkedPages, advertised ? Math.ceil(advertised / 24) : 1);
  if (!options.automatic&&!confirm(`Fix Price сообщает примерно ${advertised || "неизвестное число"} товаров. Собрать ${totalPages} страниц?`)) {
    return;
  }

  const panel = document.createElement("div");
  Object.assign(panel.style, {
    position: "fixed", right: "20px", bottom: "20px", zIndex: 2147483647,
    padding: "14px 18px", borderRadius: "12px", background: "#17212b",
    color: "white", font: "600 15px system-ui", boxShadow: "0 8px 30px #0007"
  });
  document.body.appendChild(panel);
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;width:1px;height:1px;opacity:.01;left:-10px;bottom:0";
  document.body.appendChild(frame);

  async function loadPage(pageNumber) {
    const url = new URL("/catalog/produkty-i-napitki", location.origin);
    if (pageNumber > 1) url.searchParams.set("page", String(pageNumber));
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      panel.textContent = `Fix Price: страница ${pageNumber}/${totalPages}, попытка ${attempt}`;
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("страница загружалась дольше 60 секунд")), 60000);
        frame.onload = () => { clearTimeout(timer); resolve(); };
        frame.src = url.href;
      });
      await sleep(1200);
      const doc = frame.contentDocument;
      const state = doc && [...doc.scripts].find((script) => script.textContent.includes("window.__NUXT__"));
      if (state && /\bproducts\s*:\s*\[/.test(state.textContent)) {
        return { url: url.href, html: `<script>${state.textContent}</script>` };
      }
      await sleep(2000 * attempt);
    }
    throw new Error(`не удалось получить товары со страницы ${pageNumber}`);
  }

  try {
    const pages = [];
    for (let pageNumber = 1; pageNumber <= totalPages; pageNumber += 1) {
      if(options.stopped)throw new Error("Сбор остановлен пользователем");
      pages.push(await loadPage(pageNumber));
      await sleep(500);
    }
    const capture = {
      format: "fixprice-pages-v1",
      created_at: new Date().toISOString(),
      advertised_products: advertised,
      total_pages: totalPages,
      pages
    };
    if(options.onResult){await options.onResult({kind:"fixprice",data:capture});return;}
    const payload=JSON.stringify(capture);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
    link.download = `fixprice_pages_${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 30000);
    panel.textContent = `Готово: сохранено ${pages.length} страниц`;
    alert("Автосбор Fix Price завершён. Импортируйте скачанный JSON в программе «Каталоги магазинов».");
  } catch (error) {
    panel.textContent = "Автосбор остановлен";
    if(options.onError)options.onError(error.message);else alert(`Fix Price: ${error.message}`);
  } finally {
    frame.remove();
    setTimeout(() => panel.remove(), 15000);
  }
})();
