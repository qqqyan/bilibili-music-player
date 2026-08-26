<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import {
  authCredential,
  authQrcode,
  authQrcodeStatus,
  passwordGeetestStatus,
  passwordLogin,
  passwordPrepare,
} from "../api";

defineProps({
  embedded: { type: Boolean, default: false }, // 嵌入 Settings 面板时无遮罩
});
const emit = defineEmits(["login-success", "close"]);

const tab = ref("qrcode");
const qrImage = ref("");
const qrStatus = ref(""); // waiting / scanned / timeout / done / error
const qrTimer = ref(null);
const sessionId = ref("");
const qrError = ref("");

const form = ref({ sessdata: "", bili_jct: "", dedeuserid: "", buvid3: "", buvid4: "" });
const formError = ref("");
const submitting = ref(false);

async function startQrcode() {
  stopPolling();
  qrError.value = "";
  qrStatus.value = "waiting";
  try {
    const data = await authQrcode();
    sessionId.value = data.session_id;
    qrImage.value = data.image_data_url;
    qrTimer.value = setInterval(poll, 2000);
  } catch (e) {
    qrError.value = e.message;
    qrStatus.value = "error";
  }
}

async function poll() {
  if (!sessionId.value) return;
  try {
    const res = await authQrcodeStatus(sessionId.value);
    if (res.status === "scan") qrStatus.value = "waiting";
    else if (res.status === "confirm") qrStatus.value = "scanned";
    else if (res.status === "timeout") {
      qrStatus.value = "timeout";
      stopPolling();
    } else if (res.status === "error") {
      qrStatus.value = "error";
      qrError.value = res.message || "登录接口出错";
      stopPolling();
    } else if (res.status === "done") {
      qrStatus.value = "done";
      stopPolling();
      emit("login-success", res.user);
    }
  } catch {
    /* 网络抖动,下轮重试 */
  }
}

function stopPolling() {
  if (qrTimer.value) {
    clearInterval(qrTimer.value);
    qrTimer.value = null;
  }
}

async function submitForm() {
  formError.value = "";
  submitting.value = true;
  try {
    const res = await authCredential({ ...form.value });
    emit("login-success", res.user);
  } catch (e) {
    formError.value = e.message;
  } finally {
    submitting.value = false;
  }
}

// ---------------------------------------------------------------- 密码登录
const pwForm = ref({ username: "", password: "" });
const pwState = ref("idle"); // idle / verifying / submitting
const pwError = ref("");
const geetestUrl = ref("");
const pwSessionId = ref("");
const pwTimer = ref(null);

function stopPwPoll() {
  if (pwTimer.value) {
    clearInterval(pwTimer.value);
    pwTimer.value = null;
  }
}

async function doPasswordLogin() {
  pwError.value = "";
  if (!pwForm.value.username || !pwForm.value.password) {
    pwError.value = "请输入账号和密码";
    return;
  }
  pwState.value = "verifying";
  try {
    // 1. 后端创建极验验证并启动官方验证页服务(127.0.0.1 随机端口)
    const prep = await passwordPrepare();
    geetestUrl.value = prep.geetest_url;
    pwSessionId.value = prep.session_id;
    // 2. 轮询验证完成状态,完成后自动提交登录
    stopPwPoll();
    pwTimer.value = setInterval(async () => {
      try {
        const st = await passwordGeetestStatus(pwSessionId.value);
        if (st.expired) {
          stopPwPoll();
          pwError.value = "验证会话过期,请重新点击登录";
          pwState.value = "idle";
          return;
        }
        if (st.done) {
          stopPwPoll();
          pwState.value = "submitting";
          try {
            const res = await passwordLogin({
              session_id: pwSessionId.value,
              username: pwForm.value.username,
              password: pwForm.value.password,
            });
            emit("login-success", res.user);
          } catch (e) {
            pwError.value = e.message;
            pwState.value = "idle";
          }
        }
      } catch {
        /* 网络抖动,下轮重试 */
      }
    }, 2000);
  } catch (e) {
    pwError.value = e.message;
    pwState.value = "idle";
  }
}

onMounted(() => {
  startQrcode(); // 打开弹窗即自动生成二维码
});
onUnmounted(() => {
  stopPolling();
  stopPwPoll();
});

defineExpose({ startQrcode });
</script>

<template>
  <div class="mask" :class="{ embedded }" @click.self="emit('close')">
    <div class="dialog">
      <div class="head">
        <span class="title">登录 bilibili</span>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="tabs">
        <button :class="{ on: tab === 'qrcode' }" @click="tab = 'qrcode'">
          扫码登录
        </button>
        <button :class="{ on: tab === 'password' }" @click="tab = 'password'">
          账号密码
        </button>
        <button :class="{ on: tab === 'manual' }" @click="tab = 'manual'">
          手动填写凭证
        </button>
      </div>

      <!-- 扫码登录 -->
      <div v-if="tab === 'qrcode'" class="tab-body">
        <template v-if="qrImage && qrStatus !== 'timeout' && qrStatus !== 'error'">
          <img class="qr" :src="qrImage" alt="登录二维码" />
          <div class="status">
            <span v-if="qrStatus === 'waiting'">请使用 bilibili 手机 App 扫码</span>
            <span v-else-if="qrStatus === 'scanned'">已扫码,请在手机上确认登录</span>
          </div>
        </template>
        <template v-else>
          <div class="status error">
            {{ qrError || "二维码已过期" }}
          </div>
          <button class="primary" @click="startQrcode">重新获取二维码</button>
        </template>
      </div>

      <!-- 账号密码登录 -->
      <div v-else-if="tab === 'password'" class="tab-body">
        <p class="hint">
          密码仅用于本次登录请求,不会保存。B 站强制人机验证,点击登录后将弹出验证码。
        </p>
        <label>账号</label>
        <input v-model="pwForm.username" type="text" placeholder="手机号或邮箱" />
        <label>密码</label>
        <input
          v-model="pwForm.password"
          type="password"
          placeholder="bilibili 密码"
          @keyup.enter="doPasswordLogin"
        />
        <iframe
          v-if="geetestUrl"
          class="geetest-frame"
          :src="geetestUrl"
          title="人机验证"
        ></iframe>
        <div v-if="pwError" class="status error">{{ pwError }}</div>
        <button class="primary" :disabled="pwState !== 'idle'" @click="doPasswordLogin">
          {{ pwState === "idle" ? "登录" : pwState === "verifying" ? "请在下方完成人机验证…" : "提交中…" }}
        </button>
      </div>

      <!-- 手动填写 -->
      <div v-else class="tab-body">
        <p class="hint">
          从浏览器登录 bilibili.com 后,F12 → Application → Cookies 复制以下字段:
        </p>
        <label>SESSDATA <span class="req">*</span></label>
        <input v-model="form.sessdata" type="text" placeholder="必填" />
        <label>bili_jct</label>
        <input v-model="form.bili_jct" type="text" placeholder="可选" />
        <label>DedeUserID</label>
        <input v-model="form.dedeuserid" type="text" placeholder="可选" />
        <label>buvid3</label>
        <input v-model="form.buvid3" type="text" placeholder="可选" />
        <div v-if="formError" class="status error">{{ formError }}</div>
        <button class="primary" :disabled="submitting" @click="submitForm">
          {{ submitting ? "验证中…" : "登录" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.mask.embedded {
  position: static;
  inset: auto;
  background: none;
  z-index: auto;
}
.dialog {
  width: 420px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.close-btn {
  color: var(--text-dim);
  font-size: 14px;
  padding: 4px;
}
.close-btn:hover {
  color: var(--text);
}
.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.tabs button {
  padding: 8px 14px;
  color: var(--text-dim);
  border-bottom: 2px solid transparent;
}
.tabs button.on {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 200px;
  align-items: center;
}
.qr {
  width: 180px;
  height: 180px;
  border-radius: 8px;
  background: #fff;
}
.status {
  font-size: 13px;
  color: var(--text-dim);
}
.status.error {
  color: #e56d6d;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  align-self: flex-start;
  line-height: 1.7;
}
label {
  font-size: 12px;
  color: var(--text-dim);
  align-self: flex-start;
}
.req {
  color: #e56d6d;
}
input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  outline: none;
  font-size: 12px;
}
input:focus {
  border-color: var(--accent);
}
.primary {
  margin-top: 6px;
  height: 36px;
  padding: 0 32px;
  border-radius: 18px;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}
.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.geetest-frame {
  width: 100%;
  height: 340px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
}
</style>
