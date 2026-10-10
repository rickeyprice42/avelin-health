(async () => {
  if (location.hostname !== "web.kuper.ru") {
    alert("Сначала откройте каталог нужного магазина на web.kuper.ru.");
    return;
  }
  const sid = new URL(location.href).searchParams.get("sid");
  if (!sid || !/^\d+$/.test(sid)) {
    alert("В адресе страницы не найден sid магазина. Сначала выберите магазин и адрес доставки.");
    return;
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const panel = document.createElement("div");
  Object.assign(panel.style, {
    position: "fixed", right: "20px", bottom: "20px", zIndex: 2147483647,
    maxWidth: "430px", padding: "14px 18px", borderRadius: "12px",
    background: "#17212b", color: "white", font: "600 15px/1.4 system-ui",
    boxShadow: "0 8px 30px #0007"
  });
  panel.textContent = "Автосбор Kuper: нажмите любую продуктовую категорию в левом меню…";
  document.body.appendChild(panel);

  const nativeFetch = window.fetch.bind(window);
  const originalFetch = window.fetch;
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  const originalSend = XMLHttpRequest.prototype.send;
  let resolveCaptured;
  const capturedPromise = new Promise((resolve) => { resolveCaptured = resolve; });
  let captured = false;

  function finishCapture(value) {
    if (!captured && value && String(value.url).includes("/api/v3/entities")) {
      captured = true;
      resolveCaptured(value);
    }
  }

  window.fetch = async function interceptedFetch(input, init = {}) {
    const url = typeof input === "string" ? input : input.url;
    if (String(url).includes("/api/v3/entities")) {
      const headers = new Headers(typeof input === "string" ? undefined : input.headers);
      new Headers(init.headers || {}).forEach((value, key) => headers.set(key, value));
      let body = init.body || "";
      if (!body && typeof input !== "string") {
        try { body = await input.clone().text(); } catch (_) { body = ""; }
      }
      finishCapture({ url, headers: Object.fromEntries(headers.entries()), body });
    }
    return nativeFetch(input, init);
  };

  XMLHttpRequest.prototype.open = function interceptedOpen(method, url, ...args) {
    this.__kuperCapture = { method, url, headers: {} };
    return originalOpen.call(this, method, url, ...args);
  };
  XMLHttpRequest.prototype.setRequestHeader = function interceptedHeader(name, value) {
    if (this.__kuperCapture) this.__kuperCapture.headers[String(name).toLowerCase()] = value;
    return originalSetHeader.call(this, name, value);
  };
  XMLHttpRequest.prototype.send = function interceptedSend(body) {
    if (this.__kuperCapture) finishCapture({ ...this.__kuperCapture, body: body || "" });
    return originalSend.call(this, body);
  };

  try {
    const capturedRequest = await Promise.race([
      capturedPromise,
      sleep(120000).then(() => { throw new Error("За две минуты не появился запрос каталога. Запустите закладку снова и выберите другую категорию."); })
    ]);
    window.fetch = originalFetch;
    XMLHttpRequest.prototype.open = originalOpen;
    XMLHttpRequest.prototype.setRequestHeader = originalSetHeader;
    XMLHttpRequest.prototype.send = originalSend;

    let template;
    try { template = JSON.parse(capturedRequest.body || "{}"); } catch (_) { template = {}; }
    const allowedHeaders = ["accept", "content-type", "x-csrf-token", "client-id", "client-token", "anonymousid"];
    const requestHeaders = {};
    for (const key of allowedHeaders) {
      const value = capturedRequest.headers[key];
      if (value) requestHeaders[key] = value;
    }
    requestHeaders.accept = "application/json, text/plain, */*";
    requestHeaders["content-type"] = "application/json";

    async function fetchJson(url, options = {}) {
      let lastError;
      for (let attempt = 1; attempt <= 4; attempt += 1) {
        try {
          const response = await nativeFetch(url, { credentials: "include", ...options });
          if (response.ok) return await response.json();
          const message = `${response.status} ${response.statusText}`;
          if (response.status !== 429 && response.status < 500) throw new Error(message);
          lastError = new Error(message);
        } catch (error) {
          lastError = error;
        }
        await sleep(1500 * attempt);
      }
      throw lastError || new Error("ошибка запроса");
    }

    panel.textContent = "Автосбор Kuper: получаю список категорий…";
    const categoriesUrl = `/api/v3/stores/${sid}/categories`;
    const categoryTree = await fetchJson(categoriesUrl, { headers: requestHeaders });
    const excluded = /(skid|akts|promo|probovali|sezon|novink|rekomend|kosmetik|gigien|apte|bitov|dlya-doma|kukhni|zoot|pitom|detsk|dacha|sad-avto|odezh|obuv|aksess|podaro|sertifikat|kantsel|tvorch|elektron)/i;
    const categories = (categoryTree.categories || []).filter((category) =>
      category && category.slug && Number(category.products_count) > 0 &&
      (category.category_type === "main" || !category.category_type) &&
      !excluded.test(`${category.slug} ${category.name}`)
    );
    if (!categories.length) throw new Error("Kuper не вернул продуктовые категории.");

    const pathSlug = location.pathname.split("/").filter(Boolean)[0] || "kuper";
    const suggestedName = /hleb|sol/i.test(pathSlug) ? "Хлеб&Соль" :
      /pyat|5ka|five/i.test(pathSlug) ? "Пятёрочка" : pathSlug;
    const storeName = prompt("Название магазина для Excel:", suggestedName) || suggestedName;
    const estimatedProducts = categories.reduce((sum, item) => sum + Number(item.products_count || 0), 0);
    if (!confirm(`Собрать ${categories.length} продуктовых категорий (${estimatedProducts} позиций до удаления дублей)?`)) return;

    const entries = [];
    const makeEntry = (url, method, requestBody, responseBody) => ({
      startedDateTime: new Date().toISOString(), time: 0,
      request: {
        method, url: new URL(url, location.origin).href, httpVersion: "HTTP/2",
        headers: [], queryString: [], cookies: [], headersSize: -1, bodySize: requestBody ? requestBody.length : 0,
        ...(requestBody ? { postData: { mimeType: "application/json", text: requestBody } } : {})
      },
      response: {
        status: 200, statusText: "OK", httpVersion: "HTTP/2", headers: [], cookies: [],
        content: { mimeType: "application/json", text: JSON.stringify(responseBody) },
        redirectURL: "", headersSize: -1, bodySize: -1
      }, cache: {}, timings: { send: 0, wait: 0, receive: 0 }
    });
    entries.push(makeEntry(categoriesUrl, "GET", "", categoryTree));
    entries.push(makeEntry(`/api/v3/mweb/stores/${sid}`, "GET", "", { retailer: { name: storeName } }));

    let requestCount = 0;
    for (let categoryIndex = 0; categoryIndex < categories.length; categoryIndex += 1) {
      const category = categories[categoryIndex];
      let page = 1;
      let totalPages = Math.max(1, Math.ceil(Number(category.products_count) / 24));
      while (page <= totalPages) {
        panel.textContent = `Kuper: ${categoryIndex + 1}/${categories.length} — ${category.name}, страница ${page}/${totalPages}`;
        const body = {
          ...template,
          store_id: String(sid), category_permalink: category.slug, q: "",
          full_facets_list: true, filter: [], page: String(page), per_page: "24"
        };
        const bodyText = JSON.stringify(body);
        const response = await fetchJson("/api/v3/entities", {
          method: "POST", headers: requestHeaders, body: bodyText
        });
        entries.push(makeEntry("/api/v3/entities", "POST", bodyText, response));
        requestCount += 1;
        const reportedTotal = Number(response.meta && response.meta.total_pages);
        if (reportedTotal > 0 && reportedTotal < 500) totalPages = reportedTotal;
        page += 1;
        await sleep(350);
      }
    }

    const har = {
      log: {
        version: "1.2",
        creator: { name: "Kuper browser collector", version: "1.0" },
        comment: "Complete food-category capture without cookies or request headers",
        entries
      }
    };
    const safeStem = /пят/i.test(storeName) ? "pyaterochka" : /хлеб|соль/i.test(storeName) ? "hleb&sol" : pathSlug;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([JSON.stringify(har)], { type: "application/json" }));
    link.download = `${safeStem}.complete.har`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 30000);
    panel.textContent = `Готово: ${categories.length} категорий, ${requestCount} страниц`;
    alert("Автосбор Kuper завершён. Добавьте скачанный HAR в программу и нажмите «Импортировать HAR».");
  } catch (error) {
    panel.textContent = "Автосбор Kuper остановлен";
    alert(`Kuper: ${error.message}`);
  } finally {
    window.fetch = originalFetch;
    XMLHttpRequest.prototype.open = originalOpen;
    XMLHttpRequest.prototype.setRequestHeader = originalSetHeader;
    XMLHttpRequest.prototype.send = originalSend;
    setTimeout(() => panel.remove(), 20000);
  }
})();
