<script setup>
import { computed, ref } from "vue";
import { usePlayerStore } from "../stores/player";
import LoginDialog from "./LoginDialog.vue";

const props = defineProps({
  initialTab: { type: String, default: "settings" }, // account / settings
  loggedIn: { type: Boolean, default: false }, // 登录态,控制退出按钮显示
});
const emit = defineEmits(["close", "login-success", "logout"]);

const store = usePlayerStore();
// 组件由 v-if 控制,每次打开重新创建,直接用 initialTab 初始化
const tab = ref(props.initialTab);

const sizeText = computed(() => {
  const s = store.cacheTotalSize;
  if (s >= 1024 * 1024 * 1024) return (s / 1024 / 1024 / 1024).toFixed(2) + " GB";
  if (s >= 1024 * 1024) return (s / 1024 / 1024).toFixed(1) + " MB";
  return Math.round(s / 1024) + " KB";
});

async function toggleCleanup() {
  const enabled = store.settings.cleanup_old_quality;
  await store.saveSetting({ cleanup_old_quality: enabled });
  if (enabled) {
    // 开启时立即遍历现有缓存,每首只保留最高档
    await store.cleanupAllCache();
  }
}

async function doClearCache() {
  if (!confirm("确定清空全部本地缓存吗?")) return;
  await store.clearAllCache();
}

/** 布尔开关保存(自动加入/自动缓存等) */
async function saveBoolSetting(key, value) {
  await store.saveSetting({ [key]: value });
}

/** 关闭「自动加入列表」时联动关闭「自动缓存」(用户可再单独打开) */
async function onAutoAddChange(value) {
  if (!value) {
    store.settings.auto_cache_on_play = false;
    await store.saveSetting({
      auto_add_on_play: false,
      auto_cache_on_play: false,
    });
  } else {
    await store.saveSetting({ auto_add_on_play: true });
  }
}

function doLogout() {
  // 二次确认,防止误点
  if (!confirm("确定退出登录吗?")) return;
  emit("logout");
}
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="dialog">
      <div class="head">
        <span class="title">设置</span>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="tabs">
        <button :class="{ on: tab === 'account' }" @click="tab = 'account'">
          账号
        </button>
        <button :class="{ on: tab === 'settings' }" @click="tab = 'settings'">
          设置
        </button>
      </div>

      <!-- 账号 -->
      <div v-if="tab === 'account'" class="tab-body">
        <LoginDialog embedded @login-success="emit('login-success')" @close="() => {}" />
        <button v-if="loggedIn" class="danger" @click="doLogout">退出登录</button>
      </div>

      <!-- 设置 -->
      <div v-else class="tab-body">
        <div class="row">
          <div class="row-label">
            <span>下载更高档后自动清理旧档缓存</span>
            <span class="desc">开启后,补下更高音质/画质完成时删除该曲目更低的旧档文件</span>
          </div>
          <label class="switch">
            <input
              v-model="store.settings.cleanup_old_quality"
              type="checkbox"
              @change="toggleCleanup"
            />
            <span class="slider"></span>
          </label>
        </div>

        <div class="row">
          <div class="row-label">
            <span>播放视频时自动加入播放列表</span>
            <span class="desc">关闭后从搜索结果点播为临时播放,不留在列表;并联动关闭下方「自动缓存」</span>
          </div>
          <label class="switch">
            <input
              v-model="store.settings.auto_add_on_play"
              type="checkbox"
              @change="onAutoAddChange($event.target.checked)"
            />
            <span class="slider"></span>
          </label>
        </div>

        <div class="row">
          <div class="row-label">
            <span>播放时自动缓存到本地</span>
            <span class="desc">仅对播放列表内的曲目生效(临时播放不缓存),手动「下载全部」不受影响</span>
          </div>
          <label class="switch">
            <input
              v-model="store.settings.auto_cache_on_play"
              type="checkbox"
              @change="saveBoolSetting('auto_cache_on_play', $event.target.checked)"
            />
            <span class="slider"></span>
          </label>
        </div>

        <div class="row">
          <div class="row-label">
            <span>本地缓存占用</span>
            <span class="desc">data/cache/ 目录</span>
          </div>
          <span class="size">{{ sizeText }}</span>
        </div>

        <button class="danger" @click="doClearCache">清空全部缓存</button>
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
.dialog {
  width: 440px;
  max-height: 80vh;
  overflow-y: auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.close-btn {
  color: var(--text-dim);
  padding: 4px;
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
  gap: 14px;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.row-label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 13px;
}
.desc {
  font-size: 11px;
  color: var(--text-dim);
}
.size {
  font-size: 13px;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}
.danger {
  align-self: flex-start;
  padding: 8px 18px;
  border-radius: 16px;
  border: 1px solid #e56d6d;
  color: #e56d6d;
  font-size: 13px;
}
.danger:hover {
  background: rgba(229, 109, 109, 0.1);
}

/* 开关 */
.switch {
  position: relative;
  display: inline-block;
  width: 42px;
  height: 24px;
  flex-shrink: 0;
}
.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}
.slider {
  position: absolute;
  inset: 0;
  border-radius: 12px;
  background: #3a3a46;
  transition: background 0.2s;
  cursor: pointer;
}
.slider::before {
  content: "";
  position: absolute;
  width: 18px;
  height: 18px;
  left: 3px;
  top: 3px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s;
}
.switch input:checked + .slider {
  background: var(--accent);
}
.switch input:checked + .slider::before {
  transform: translateX(18px);
}
</style>
