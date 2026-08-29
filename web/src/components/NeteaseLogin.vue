<script setup>
// 网易云登录(设置-账号 Tab 内嵌区块):扫码(本机)或粘贴浏览器 cookie(跨设备通用)。
// 后端 2s 轮询语义:scan(等待扫码)/confirm(已扫码待确认)/done/expired。
import { onMounted, onUnmounted, ref } from "vue";
import {
  neteaseCookieLogin,
  neteaseLogout,
  neteaseQrcode,
  neteaseQrcodeStatus,
  neteaseStatus,
} from "../api";

const emit = defineEmits(["login-success"]);

const status = ref({ logged_in: false, user: null });
const qrImage = ref("");
const qrText = ref("加载登录二维码…");
const sessionId = ref("");
const expired = ref(false);
const showManual = ref(false);
const manualCookie = ref("");
const manualError = ref("");
const manualBusy = ref(false);
let timer = null;

async function startQrcode() {
  expired.value = false;
  try {
    const res = await neteaseQrcode();
    sessionId.value = res.session_id;
    qrImage.value = res.image_data_url;
    qrText.value = "请用网易云音乐 App 扫码";
    clearInterval(timer);
    timer = setInterval(poll, 2000);
  } catch (e) {
    qrText.value = `二维码获取失败: ${e.message}`;
  }
}

async function poll() {
  try {
    const res = await neteaseQrcodeStatus(sessionId.value);
    if (res.status === "scan") {
      qrText.value = "请用网易云音乐 App 扫码";
    } else if (res.status === "confirm") {
      qrText.value = `已在「${res.user?.name || "App"}」上确认,正在登录…`;
    } else if (res.status === "done") {
      clearInterval(timer);
      qrText.value = "登录成功";
      status.value = { logged_in: true, user: res.user };
      emit("login-success");
    } else if (res.status === "expired") {
      clearInterval(timer);
      expired.value = true;
      qrText.value = "二维码已过期";
    }
  } catch {
    /* 轮询瞬断忽略 */
  }
}

async function fetchStatus() {
  try {
    status.value = await neteaseStatus();
  } catch {
    /* 静默 */
  }
}

async function doLogout() {
  await neteaseLogout().catch(() => {});
  status.value = { logged_in: false, user: null };
  await startQrcode();
}

async function doCookieLogin() {
  if (!manualCookie.value.trim()) {
    manualError.value = "请先粘贴 cookie";
    return;
  }
  manualBusy.value = true;
  manualError.value = "";
  try {
    const res = await neteaseCookieLogin(manualCookie.value.trim());
    status.value = { logged_in: true, user: res.user };
    manualCookie.value = "";
    showManual.value = false;
    emit("login-success");
  } catch (e) {
    manualError.value = e.message || "导入失败";
  } finally {
    manualBusy.value = false;
  }
}

onMounted(async () => {
  await fetchStatus();
  if (!status.value.logged_in) await startQrcode();
});

onUnmounted(() => clearInterval(timer));
</script>

<template>
  <div class="netease-login">
    <template v-if="status.logged_in">
      <div class="logged-row">
        <img v-if="status.user?.face" class="face" :src="status.user.face" alt="" />
        <span class="name">{{ status.user?.name || "已登录" }}</span>
        <button class="logout-btn" @click="doLogout">退出</button>
      </div>
    </template>
    <template v-else>
      <img v-if="qrImage" class="qr" :src="qrImage" alt="网易云登录二维码" />
      <div class="qr-text">{{ qrText }}</div>
      <button v-if="expired" class="refresh-btn" @click="startQrcode">
        重新获取二维码
      </button>
      <button v-if="!showManual" class="manual-toggle" @click="showManual = true">
        粘贴浏览器 cookie 登录
      </button>
      <div v-else class="manual-box">
        <div class="desc">
          浏览器登录过网易云后,F12 → Application → Cookies → 复制
          <b>MUSIC_U</b> 和 <b>__csrf</b> 的值,按「MUSIC_U=xxx; __csrf=xxx」格式粘贴:
        </div>
        <textarea
          v-model="manualCookie"
          class="manual-input"
          placeholder="MUSIC_U=...; __csrf=..."
        ></textarea>
        <div class="manual-actions">
          <button class="primary-btn" :disabled="manualBusy" @click="doCookieLogin">
            {{ manualBusy ? "验证中…" : "登录" }}
          </button>
          <button class="manual-toggle" @click="showManual = false">取消</button>
        </div>
        <div v-if="manualError" class="manual-error">{{ manualError }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.netease-login {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.qr {
  width: 180px;
  height: 180px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: #fff;
}
.qr-text {
  font-size: 12px;
  color: var(--text-dim);
}
.refresh-btn {
  font-size: 12px;
  color: var(--accent);
  padding: 4px 12px;
  border-radius: 12px;
  border: 1px solid var(--accent);
}
.logged-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.face {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
}
.name {
  font-size: 13px;
}
.logout-btn {
  font-size: 12px;
  color: var(--text-dim);
  padding: 4px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
}
.logout-btn:hover {
  color: #e56d6d;
}
.manual-toggle {
  font-size: 12px;
  color: var(--text-dim);
  padding: 4px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
}
.manual-toggle:hover {
  color: var(--accent);
}
.manual-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.desc {
  font-size: 11px;
  color: var(--text-dim);
  line-height: 1.6;
}
.manual-input {
  width: 100%;
  min-height: 60px;
  padding: 8px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  outline: none;
  font-size: 12px;
  font-family: monospace;
  resize: vertical;
}
.manual-actions {
  display: flex;
  gap: 8px;
}
.primary-btn {
  padding: 5px 14px;
  border-radius: 12px;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
}
.primary-btn:disabled {
  opacity: 0.5;
}
.manual-error {
  font-size: 12px;
  color: #e56d6d;
}
</style>
