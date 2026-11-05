// 前端诊断:最近的 console / 异常日志环形缓冲,供应用内反馈上报。
// 语言层面无法拿到后端日志,这里补上前端视角(player.js 的 console.debug 等)。

const MAX_LOGS = 200;
const MAX_TEXT = 600;
const buffer = [];

function formatArg(value) {
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null) {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function stamp() {
  return new Date().toTimeString().slice(0, 8);
}

function push(level, args) {
  const text = args
    .map(formatArg)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_TEXT);
  if (!text) return;
  buffer.push(`${stamp()} ${level} ${text}`);
  if (buffer.length > MAX_LOGS) buffer.splice(0, buffer.length - MAX_LOGS);
}

let installed = false;

/** 接管 console 与全局异常(幂等,应用启动时调用一次)。 */
export function installDiagnostics() {
  if (installed) return;
  installed = true;
  for (const level of ["log", "debug", "info", "warn", "error"]) {
    const original = console[level]?.bind(console);
    if (!original) continue;
    console[level] = (...args) => {
      push(level, args);
      original(...args);
    };
  }
  window.addEventListener("error", (event) => {
    const where = event.filename ? ` ${event.filename}:${event.lineno}:${event.colno}` : "";
    push("error", [`未捕获异常: ${event.message}${where}`]);
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason =
      event.reason instanceof Error
        ? `${event.reason.name}: ${event.reason.message}`
        : event.reason;
    push("error", [`未处理的 Promise 拒绝: ${formatArg(reason)}`]);
  });
}

/** 最近的前端日志(新的在末尾)。 */
export function recentLogs(limit = MAX_LOGS) {
  return buffer.slice(-limit);
}

/**
 * 反馈请求携带的客户端环境。
 * playerState: { loggedIn, neteaseLoggedIn, track, playing, quality, mv }
 */
export function clientContext(playerState = {}) {
  let track = null;
  if (playerState.track?.title) {
    track = {
      id: playerState.track.id || "",
      title: playerState.track.title,
      artist: playerState.track.artist || "",
      playing: !!playerState.playing,
      quality: playerState.quality || "",
      mv: !!playerState.mv,
    };
  }
  return {
    user_agent: navigator.userAgent,
    language: navigator.language,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    screen: `${window.screen.width}x${window.screen.height}`,
    device_pixel_ratio: window.devicePixelRatio || 1,
    logged_in: playerState.loggedIn ?? null,
    netease_logged_in: playerState.neteaseLoggedIn ?? null,
    current_track: track,
    frontend_logs: recentLogs(),
  };
}
