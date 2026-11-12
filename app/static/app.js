const state = {
  products: [],
  category: "All",
  query: "",
  cart: {},
  user: null,
  csrfToken: null,
};

try {
  state.cart = JSON.parse(localStorage.getItem("northstar-cart") || "{}");
} catch {
  state.cart = {};
}

const $ = (selector) => document.querySelector(selector);
const money = (value) => `$${Number(value).toFixed(2)}`;
let authMode = "login";
let reviewProductId = null;
let cartSyncTimer = null;

async function api(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && state.csrfToken) {
    headers["X-CSRF-Token"] = state.csrfToken;
  }
  const response = await fetch(url, {
    ...options,
    headers,
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
        <div class="product-category-row"><span>${escapeHtml(product.category)}</span><button class="rating-button" data-reviews="${escapeHtml(product.id)}" aria-label="Read reviews for ${escapeHtml(product.name)}">★ ${Number(product.rating).toFixed(1)} · reviews</button></div>
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
  if (state.user) {
    window.clearTimeout(cartSyncTimer);
    cartSyncTimer = window.setTimeout(syncCart, 180);
  }
}

async function syncCart() {
  try {
    await api("/api/cart", {
      method: "PUT",
      body: JSON.stringify({
        items: Object.entries(state.cart).map(([product_id, quantity]) => ({ product_id, quantity })),
      }),
    });
  } catch (error) {
    showToast(`Your bag is saved on this device. ${error.message}`);
  }
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

function updateAccountButtons() {
  const accountButton = $("#account-open");
  accountButton.textContent = state.user ? state.user.name.split(/\s+/)[0] : "Sign in";
  accountButton.title = state.user ? state.user.email : "Sign in or create an account";
  $("#admin-open").classList.toggle("hidden", !state.user || state.user.role !== "admin");
}

function showAuthMode(mode) {
  authMode = mode;
  const registering = mode === "register";
  $("#account-title").textContent = registering ? "A good thing starts here." : "Welcome back.";
  $("#auth-description").textContent = registering
    ? "Create an account to save your bag and follow your orders."
    : "Sign in to save your bag and keep track of your orders.";
  $("#auth-name-label").classList.toggle("hidden", !registering);
  $("#auth-name").classList.toggle("hidden", !registering);
  $("#auth-name").required = registering;
  $("#auth-password").autocomplete = registering ? "new-password" : "current-password";
  $("#auth-password").minLength = registering ? 10 : 1;
  $("#auth-submit").innerHTML = `${registering ? "Create account" : "Sign in"} <span>→</span>`;
  $("#auth-switch").textContent = registering ? "Already have an account? Sign in" : "New here? Create an account";
  $("#auth-feedback").textContent = "";
  $("#account-view").classList.add("hidden");
  $("#auth-view").classList.remove("hidden");
}

async function loadAccountCart() {
  const localCart = { ...state.cart };
  const data = await api("/api/cart");
  const savedCart = Object.fromEntries(data.items.map((item) => [item.id, item.quantity]));
  state.cart = { ...savedCart };
  for (const [id, quantity] of Object.entries(localCart)) {
    state.cart[id] = Math.min(20, (state.cart[id] || 0) + Number(quantity));
  }
  localStorage.setItem("northstar-cart", JSON.stringify(state.cart));
  renderCart();
  await syncCart();
}

async function loadOrderHistory() {
  const target = $("#order-history");
  target.innerHTML = "<p class='empty-state'>Loading your orders…</p>";
  try {
    const orders = await api("/api/orders");
    target.innerHTML = orders.length ? orders.map((order) => `
      <article class="order-card">
        <div class="order-card-top"><span>Order #${order.id}</span><span>${money(order.total)}</span></div>
        <small>${escapeHtml(order.created_at)} · ${escapeHtml(order.tracking_number || "Tracking assigned soon")}</small>
        <span class="order-status">${escapeHtml(order.status)}</span>
        <small>${order.items.map((item) => `${escapeHtml(item.product_name)} × ${item.quantity}`).join(" · ")}</small>
      </article>`).join("") : "<p class='empty-state'>No orders yet. Your next good thing is waiting.</p>";
  } catch (error) {
    target.textContent = error.message;
  }
}

function openAccount() {
  $("#account-modal").classList.remove("hidden");
  $("#auth-feedback").textContent = "";
  if (!state.user) {
    showAuthMode("login");
    $("#auth-email").focus();
    return;
  }
  $("#auth-view").classList.add("hidden");
  $("#account-view").classList.remove("hidden");
  $("#account-greeting").textContent = `Hello, ${state.user.name.split(/\s+/)[0]}.`;
  loadOrderHistory();
}

async function openReviews(productId) {
  const product = state.products.find((item) => item.id === productId);
  if (!product) return;
  reviewProductId = productId;
  $("#reviews-title").textContent = product.name;
  $("#reviews-feedback").textContent = "";
  $("#reviews-list").innerHTML = "<p class='empty-state'>Loading reviews…</p>";
  $("#review-form-area").classList.toggle("hidden", !state.user);
  $("#review-signin").classList.toggle("hidden", Boolean(state.user));
  $("#reviews-modal").classList.remove("hidden");
  try {
    const data = await api(`/api/products/${encodeURIComponent(productId)}/reviews`);
    $("#reviews-summary").textContent = data.count
      ? `${data.average} out of 5 · ${data.count} ${data.count === 1 ? "review" : "reviews"}`
      : "No reviews yet. Be the first to share a thought.";
    $("#reviews-list").innerHTML = data.reviews.length ? data.reviews.map((review) => `
      <article class="review-card"><strong><span class="review-stars">${"★".repeat(review.rating)}${"☆".repeat(5 - review.rating)}</span>${escapeHtml(review.title)}</strong>
        <p>${escapeHtml(review.body)}</p><small>By ${escapeHtml(review.customer_name)} · ${escapeHtml(review.created_at.slice(0, 10))}</small></article>`).join("") : "";
  } catch (error) {
    $("#reviews-list").innerHTML = "";
    $("#reviews-feedback").textContent = error.message;
    $("#reviews-feedback").classList.add("error");
  }
}

function resetAdminProductForm() {
  $("#admin-product-form").reset();
  $("#admin-product-id").disabled = false;
  $("#admin-product-form-title").textContent = "Add a product";
  $("#admin-cancel-edit").classList.add("hidden");
}

async function loadAdminDashboard() {
  $("#admin-modal").classList.remove("hidden");
  $("#admin-feedback").textContent = "";
  try {
    const [products, orders] = await Promise.all([
      api("/api/admin/products"),
      api("/api/admin/orders"),
    ]);
    $("#admin-product-list").innerHTML = products.map((product) => `
      <div class="admin-row"><span><strong>${escapeHtml(product.name)}</strong><small>${escapeHtml(product.id)} · ${product.stock} in stock · ${money(product.price)}</small></span><button data-edit-product="${escapeHtml(product.id)}">Edit</button></div>`).join("");
    const transitions = {
      processing: ["processing", "packed", "cancelled"],
      packed: ["packed", "shipped", "cancelled"],
      shipped: ["shipped", "delivered"],
      delivered: ["delivered"],
      cancelled: ["cancelled"],
    };
    $("#admin-order-list").innerHTML = orders.length ? orders.map((order) => `
      <div class="admin-row"><span><strong>#${order.id} · ${escapeHtml(order.customer_name)}</strong><small>${money(order.total)} · ${escapeHtml(order.tracking_number || "")}</small></span>
        <div class="admin-order-actions"><select data-order-status="${order.id}" aria-label="Order ${order.id} status">
          ${(transitions[order.status] || [order.status]).map((status) => `<option ${status === order.status ? "selected" : ""}>${escapeHtml(status)}</option>`).join("")}</select>
          <button data-save-order="${order.id}">Save</button></div></div>`).join("") : "<p class='empty-state'>No orders yet.</p>";
  } catch (error) {
    $("#admin-feedback").textContent = error.message;
    $("#admin-feedback").classList.add("error");
  }
}

$("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#auth-submit");
  const feedback = $("#auth-feedback");
  button.disabled = true;
  feedback.classList.remove("error");
  feedback.textContent = authMode === "register" ? "Creating your account…" : "Signing you in…";
  try {
    const payload = {
      email: $("#auth-email").value,
      password: $("#auth-password").value,
    };
    if (authMode === "register") payload.name = $("#auth-name").value;
    const data = await api(`/api/auth/${authMode}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.user = data.user;
    state.csrfToken = data.csrf_token;
    updateAccountButtons();
    await loadAccountCart();
    $("#auth-view").classList.add("hidden");
    $("#account-view").classList.remove("hidden");
    $("#account-greeting").textContent = `Hello, ${state.user.name.split(/\s+/)[0]}.`;
    await loadOrderHistory();
  } catch (error) {
    feedback.classList.add("error");
    feedback.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("#review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const feedback = $("#reviews-feedback");
  feedback.classList.remove("error");
  try {
    await api(`/api/products/${encodeURIComponent(reviewProductId)}/reviews`, {
      method: "POST",
      body: JSON.stringify({
        rating: Number($("#review-rating").value),
        title: $("#review-title").value,
        body: $("#review-body").value,
      }),
    });
    $("#review-form").reset();
    await openReviews(reviewProductId);
  } catch (error) {
    feedback.classList.add("error");
    feedback.textContent = error.message;
  }
});

$("#admin-product-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("#admin-product-id").value;
  const payload = {
    name: $("#admin-product-name").value,
    category: $("#admin-product-category").value,
    price: Number($("#admin-product-price").value),
    stock: Number($("#admin-product-stock").value),
    description: $("#admin-product-description").value,
    emoji: $("#admin-product-emoji").value,
    color: $("#admin-product-color").value,
    rating: Number($("#admin-product-rating").value),
  };
  const editing = $("#admin-product-id").disabled;
  try {
    await api(editing ? `/api/admin/products/${encodeURIComponent(id)}` : "/api/admin/products", {
      method: editing ? "PUT" : "POST",
      body: JSON.stringify(editing ? payload : { id, ...payload }),
    });
    await loadProducts();
    await loadAdminDashboard();
    $("#admin-feedback").classList.remove("error");
    $("#admin-feedback").textContent = "Product saved.";
    resetAdminProductForm();
  } catch (error) {
    $("#admin-feedback").classList.add("error");
    $("#admin-feedback").textContent = error.message;
  }
});

$("#admin-product-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-edit-product]");
  if (!button) return;
  try {
    const product = await api(`/api/products/${encodeURIComponent(button.dataset.editProduct)}`);
    $("#admin-product-form").reset();
    $("#admin-product-id").value = product.id;
    $("#admin-product-id").disabled = true;
    $("#admin-product-name").value = product.name;
    $("#admin-product-category").value = product.category;
    $("#admin-product-price").value = product.price;
    $("#admin-product-stock").value = product.stock;
    $("#admin-product-description").value = product.description;
    $("#admin-product-emoji").value = product.emoji;
    $("#admin-product-color").value = product.color;
    $("#admin-product-rating").value = product.rating;
    $("#admin-product-form-title").textContent = `Edit ${product.name}`;
    $("#admin-cancel-edit").classList.remove("hidden");
    $("#admin-product-form").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    $("#admin-feedback").textContent = error.message;
  }
});

$("#admin-order-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-save-order]");
  if (!button) return;
  const orderId = button.dataset.saveOrder;
  const status = $(`[data-order-status="${orderId}"]`).value;
  try {
    await api(`/api/admin/orders/${orderId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    await loadAdminDashboard();
    $("#admin-feedback").classList.remove("error");
    $("#admin-feedback").textContent = `Order #${orderId} updated.`;
  } catch (error) {
    $("#admin-feedback").classList.add("error");
    $("#admin-feedback").textContent = error.message;
  }
});

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
  const reviews = event.target.closest("[data-reviews]");
  if (button) addToCart(button.dataset.add);
  if (reviews) openReviews(reviews.dataset.reviews);
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
  if (!state.user) {
    showToast("Sign in to place an order and track it.");
    openAccount();
    return;
  }
  $("#customer-name").value = state.user.name;
  $("#customer-email").value = state.user.email;
  $("#checkout-modal").classList.remove("hidden");
  $("#checkout-modal").querySelector("button[type=submit]").focus();
});
$("#checkout-close").addEventListener("click", () => $("#checkout-modal").classList.add("hidden"));
$("#checkout-modal").addEventListener("click", (event) => {
  if (event.target === $("#checkout-modal")) $("#checkout-modal").classList.add("hidden");
});
$("#account-open").addEventListener("click", openAccount);
$("#account-close").addEventListener("click", () => $("#account-modal").classList.add("hidden"));
$("#auth-switch").addEventListener("click", () => showAuthMode(authMode === "login" ? "register" : "login"));
$("#account-logout").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
    state.user = null;
    state.csrfToken = null;
    state.cart = {};
    localStorage.removeItem("northstar-cart");
    renderCart();
    updateAccountButtons();
    $("#account-modal").classList.add("hidden");
    showToast("You’ve signed out.");
  } catch (error) {
    $("#auth-feedback").classList.add("error");
    $("#auth-feedback").textContent = error.message;
  }
});
$("#admin-open").addEventListener("click", loadAdminDashboard);
$("#admin-close").addEventListener("click", () => $("#admin-modal").classList.add("hidden"));
$("#admin-cancel-edit").addEventListener("click", resetAdminProductForm);
$("#reviews-close").addEventListener("click", () => $("#reviews-modal").classList.add("hidden"));
$("#review-signin-button").addEventListener("click", () => {
  $("#reviews-modal").classList.add("hidden");
  openAccount();
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
    ["#checkout-modal", "#account-modal", "#reviews-modal", "#admin-modal"].forEach((selector) => {
      $(selector).classList.add("hidden");
    });
  }
});

async function loadProducts() {
  state.products = await api("/api/products");
  $("#all-count").textContent = `(${state.products.length})`;
  renderProducts();
  renderCart();
}

async function initializeStorefront() {
  await loadProducts();
  try {
    const session = await api("/api/auth/me");
    state.user = session.user;
    state.csrfToken = session.csrf_token;
    updateAccountButtons();
    if (state.user) await loadAccountCart();
  } catch (error) {
    showToast(`Could not restore your sign-in: ${error.message}`);
  }
}

initializeStorefront().catch((error) => {
  $("#product-grid").innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
});
