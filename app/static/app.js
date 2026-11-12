const state = {
  products: [],
  category: "All",
  query: "",
  cart: JSON.parse(localStorage.getItem("northstar-cart") || "{}"),
};

const $ = (selector) => document.querySelector(selector);
const money = (value) => `$${Number(value).toFixed(2)}`;

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Something went wrong. Please try again.");
  return data;
}

function visibleProducts() {
  const query = state.query.trim().toLowerCase();
  return state.products.filter((product) => {
    const categoryMatch = state.category === "All" || product.category === state.category;
    const queryMatch = !query || `${product.name} ${product.category} ${product.description}`.toLowerCase().includes(query);
    return categoryMatch && queryMatch;
  });
}

function renderProducts() {
  const products = visibleProducts();
  $("#product-grid").innerHTML = products.map((product) => `
    <article class="product-card">
      <div class="product-visual" style="--product-bg:linear-gradient(145deg,${colorFor(product.color)})">
        <span class="product-badge">${product.stock > 0 ? (product.rating >= 4.8 ? "A good favorite" : product.category) : "Sold out"}</span>
        <span class="product-emoji" aria-hidden="true">${escapeHtml(product.emoji)}</span>
        ${product.stock > 0 ? `<button class="quick-add" data-add="${escapeHtml(product.id)}" aria-label="Add ${escapeHtml(product.name)} to bag">+</button>` : ""}
      </div>
      <div class="product-meta">
        <div class="product-name-row"><span class="product-name">${escapeHtml(product.name)}</span><span class="product-price">${money(product.price)}</span></div>
        <div class="product-category-row"><span>${escapeHtml(product.category)}</span><span class="rating">★ ${Number(product.rating).toFixed(1)}</span></div>
      </div>
    </article>`).join("");
  $("#empty-state").classList.toggle("hidden", products.length > 0);
  $("#product-grid").classList.toggle("hidden", products.length === 0);
}

function colorFor(value) {
  const palette = {
    "from-violet-500 to-indigo-700": "#9c90d8,#5553a1",
    "from-amber-300 to-orange-500": "#f0d998,#df9e5e",
    "from-emerald-300 to-teal-600": "#a7d6bc,#57a18b",
    "from-rose-300 to-pink-600": "#f1c0c5,#cf7b8e",
    "from-sky-300 to-blue-600": "#afd5e5,#6390c1",
    "from-orange-300 to-rose-500": "#edc39c,#d98579",
    "from-fuchsia-400 to-purple-700": "#d2a3d5,#80558e",
    "from-lime-300 to-green-600": "#d1d99c,#81a16b",
  };
  return palette[value] || "#deded2,#bfc3ad";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function saveCart() {
  localStorage.setItem("northstar-cart", JSON.stringify(state.cart));
  renderCart();
}

function addToCart(productId) {
  const product = state.products.find((item) => item.id === productId);
  if (!product || product.stock < 1) return;
  state.cart[productId] = Math.min(20, (state.cart[productId] || 0) + 1);
  saveCart();
  showToast(`${product.name} added to your bag`);
}

function changeQuantity(productId, amount) {
  const next = (state.cart[productId] || 0) + amount;
  if (next <= 0) delete state.cart[productId];
  else state.cart[productId] = Math.min(20, next);
  saveCart();
}

function renderCart() {
  const entries = Object.entries(state.cart)
    .map(([id, quantity]) => ({ product: state.products.find((item) => item.id === id), quantity }))
    .filter((entry) => entry.product);
  const count = entries.reduce((sum, entry) => sum + entry.quantity, 0);
  const subtotal = entries.reduce((sum, entry) => sum + entry.product.price * entry.quantity, 0);
  $("#bag-count").textContent = count;
  $("#bag-title-count").textContent = `(${count})`;
  $("#bag-subtotal").textContent = money(subtotal);
  $("#bag-items").innerHTML = entries.map(({ product, quantity }) => `
    <div class="bag-item">
      <div class="bag-thumb" style="--product-bg:linear-gradient(145deg,${colorFor(product.color)})">${escapeHtml(product.emoji)}</div>
      <div><div class="bag-item-name">${escapeHtml(product.name)}</div><div class="bag-item-category">${escapeHtml(product.category)}</div>
        <div class="quantity-control"><button data-quantity="${escapeHtml(product.id)}" data-change="-1" aria-label="Decrease quantity">−</button><span>${quantity}</span><button data-quantity="${escapeHtml(product.id)}" data-change="1" aria-label="Increase quantity">+</button></div>
      </div>
      <div class="bag-item-price">${money(product.price * quantity)}<button class="remove-item" data-remove="${escapeHtml(product.id)}">Remove</button></div>
    </div>`).join("");
  $("#bag-empty").classList.toggle("hidden", entries.length > 0);
  $("#bag-footer").classList.toggle("hidden", entries.length === 0);
  const remaining = Math.max(0, 75 - subtotal);
  $("#shipping-message").textContent = remaining ? `You're ${money(remaining)} away from free shipping` : "You've unlocked free shipping!";
  $("#shipping-progress-fill").style.width = `${Math.min(100, subtotal / 75 * 100)}%`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2200);
}

function openBag() {
  $("#bag-panel").classList.add("open");
  $("#bag-panel").setAttribute("aria-hidden", "false");
  $("#overlay").classList.remove("hidden");
}

function closeBag() {
  $("#bag-panel").classList.remove("open");
  $("#bag-panel").setAttribute("aria-hidden", "true");
  $("#overlay").classList.add("hidden");
}

function appendMessage(message, type) {
  const row = document.createElement("div");
  row.className = `chat-message ${type === "user" ? "user-message" : "assistant-message"}`;
  if (type !== "user") {
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.textContent = "✳";
    row.append(avatar);
  }
  const text = document.createElement("p");
  text.textContent = message;
  row.append(text);
  $("#chat-messages").append(row);
  $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
  return row;
}

async function sendChat(message) {
  appendMessage(message, "user");
  const typing = appendMessage("One sec, finding a good answer…", "assistant");
  typing.classList.add("typing");
  $("#chat-input").disabled = true;
  try {
    const data = await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
    typing.querySelector("p").textContent = data.reply;
    typing.classList.remove("typing");
  } catch (error) {
    typing.querySelector("p").textContent = error.message;
    typing.classList.remove("typing");
  } finally {
    $("#chat-input").disabled = false;
    $("#chat-input").focus();
    $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
  }
}

$("#category-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("[data-category]");
  if (!tab) return;
  state.category = tab.dataset.category;
  document.querySelectorAll(".category-tab").forEach((item) => item.classList.toggle("active", item === tab));
  renderProducts();
});

document.querySelectorAll("[data-nav-category]").forEach((link) => {
  link.addEventListener("click", () => {
    state.category = link.dataset.navCategory;
    document.querySelectorAll(".category-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.category === state.category));
    renderProducts();
    $(".main-nav").classList.remove("open");
  });
});

$("#product-grid").addEventListener("click", (event) => {
  const button = event.target.closest("[data-add]");
  if (button) addToCart(button.dataset.add);
});
$("#bag-items").addEventListener("click", (event) => {
  const quantity = event.target.closest("[data-quantity]");
  const remove = event.target.closest("[data-remove]");
  if (quantity) changeQuantity(quantity.dataset.quantity, Number(quantity.dataset.change));
  if (remove) {
    delete state.cart[remove.dataset.remove];
    saveCart();
  }
});
$("#search-input").addEventListener("input", (event) => {
  state.query = event.target.value;
  renderProducts();
});
$(".search-toggle").addEventListener("click", () => {
  $("#search-box").scrollIntoView({ behavior: "smooth", block: "center" });
  $("#search-input").focus();
});
$("#bag-open").addEventListener("click", openBag);
$("#bag-close").addEventListener("click", closeBag);
$("#overlay").addEventListener("click", closeBag);
$("#continue-shopping").addEventListener("click", closeBag);
$("#continue-shopping-footer").addEventListener("click", closeBag);
$("#menu-toggle").addEventListener("click", () => $(".main-nav").classList.toggle("open"));
$("#chat-launcher").addEventListener("click", () => {
  const panel = $("#chat-panel");
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
  $("#chat-input").focus();
});
$("#chat-close").addEventListener("click", () => {
  $("#chat-panel").classList.remove("open");
  $("#chat-panel").setAttribute("aria-hidden", "true");
});
$("#chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  sendChat(message);
});
$(".chat-suggestions").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (button) sendChat(button.textContent);
});
$("#checkout-open").addEventListener("click", () => {
  if (!Object.keys(state.cart).length) return;
  closeBag();
  $("#checkout-modal").classList.remove("hidden");
  $("#customer-name").focus();
});
$("#checkout-close").addEventListener("click", () => $("#checkout-modal").classList.add("hidden"));
$("#checkout-modal").addEventListener("click", (event) => {
  if (event.target === $("#checkout-modal")) $("#checkout-modal").classList.add("hidden");
});
$("#checkout-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const feedback = $("#checkout-feedback");
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  feedback.classList.remove("error");
  feedback.textContent = "Placing your order…";
  try {
    const data = await api("/api/orders", {
      method: "POST",
      body: JSON.stringify({
        customer_name: $("#customer-name").value,
        customer_email: $("#customer-email").value,
        items: Object.entries(state.cart).map(([product_id, quantity]) => ({ product_id, quantity })),
      }),
    });
    state.cart = {};
    saveCart();
    await loadProducts();
    $("#checkout-form").classList.add("hidden");
    feedback.textContent = `You're all set! Order #${data.order_id} is confirmed. Your total is ${money(data.total)}.`;
  } catch (error) {
    feedback.classList.add("error");
    feedback.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
$("#newsletter-form").addEventListener("submit", (event) => {
  event.preventDefault();
  $("#newsletter-message").textContent = "You're on the list. Keep an eye out for a good note from us!";
  $("#newsletter-email").value = "";
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    $("#search-box").scrollIntoView({ behavior: "smooth", block: "center" });
    $("#search-input").focus();
  }
  if (event.key === "Escape") {
    closeBag();
    $("#chat-panel").classList.remove("open");
    $("#checkout-modal").classList.add("hidden");
  }
});

async function loadProducts() {
  state.products = await api("/api/products");
  $("#all-count").textContent = `(${state.products.length})`;
  renderProducts();
  renderCart();
}

loadProducts().catch((error) => {
  $("#product-grid").innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
});
